"""
바텀업 데이터 생성기 - yfinance 기반
JSON 파일로 출력하여 HTML 대시보드에서 사용
"""

import json
import time
from datetime import datetime, timezone, timedelta
import os

import yfinance as yf

# 티커 목록
TICKERS = [
    'MSFT', 'AAPL', 'GOOGL', 'AMZN', 'META', 'TSLA',  # Big Tech
    'NVDA', 'TSM', 'ASML',                             # Semiconductors
    'LLY',                                             # Healthcare
    'JPM', 'V',                                        # Financials
    'XOM',                                             # Energy
    'WMT', 'COST',                                     # Consumer Staples
    'GE', 'CAT'                                        # Industrials
]

# 가중치
WEIGHTS = {'momentum': 0.45, 'fundamental': 0.35, 'valuation': 0.20}


def safe_get(info, key, default=None):
    """안전하게 값 가져오기"""
    value = info.get(key)
    if value is None or (isinstance(value, float) and not value == value):  # NaN check
        return default
    return value


def fetch_stock_data(ticker):
    """yfinance로 주식 데이터 가져오기"""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        
        if not info or 'regularMarketPrice' not in info:
            return None
            
        return info
    except Exception as e:
        print(f"  [ERROR] {ticker}: {e}")
        return None


def calculate_scores(info):
    """점수 계산"""
    
    def clamp(value, min_val=-1, max_val=1):
        """값을 min_val ~ max_val 범위로 제한"""
        return max(min_val, min(max_val, value))
    
    try:
        # 모멘텀 지표
        perf_52w = safe_get(info, 'fiftyTwoWeekChange', 0) or 0
        current_price = safe_get(info, 'regularMarketPrice', 0) or 0
        sma200 = safe_get(info, 'twoHundredDayAverage', current_price) or current_price
        above_sma200 = 1 if current_price > sma200 else -1
        
        # 펀더멘탈 지표
        eps_growth = safe_get(info, 'earningsQuarterlyGrowth', 0) or 0
        profit_margin = safe_get(info, 'profitMargins', 0) or 0
        roe = safe_get(info, 'returnOnEquity', 0) or 0
        
        # 밸류에이션 지표
        pe = safe_get(info, 'trailingPE', 50) or 50
        forward_pe = safe_get(info, 'forwardPE', 50) or 50
        peg = safe_get(info, 'pegRatio', 2) or 2
        
        # 점수 계산 (기존 공식)
        momentum_raw = (perf_52w * 2) + (above_sma200 * 0.3)
        fundamental_raw = (eps_growth * 2) + (profit_margin * 3) + (roe * 2)
        valuation_raw = 1 - min(pe / 100, 1)
        
        # ✅ -1 ~ +1 범위로 정규화 (기존 HTML과 동일!)
        momentum_score = clamp(momentum_raw)
        fundamental_score = clamp(fundamental_raw)
        valuation_score = clamp(valuation_raw)
        
        # 최종 점수 (가중 합계 후 다시 정규화)
        final_raw = (
            WEIGHTS['momentum'] * momentum_score +
            WEIGHTS['fundamental'] * fundamental_score +
            WEIGHTS['valuation'] * valuation_score
        )
        final_score = clamp(final_raw)
        
        return {
            'momentum': round(momentum_score, 2),
            'fundamental': round(fundamental_score, 2),
            'valuation': round(valuation_score, 2),
            'final': round(final_score, 2),
            'raw': {
                'price': current_price,
                'sma200': sma200,
                '52w_change': perf_52w,
                'eps_growth': eps_growth,
                'profit_margin': profit_margin,
                'roe': roe,
                'pe': pe,
                'forward_pe': forward_pe,
                'peg': peg
            }
        }
    except Exception as e:
        print(f"  [CALC ERROR] {e}")
        return None


def main():
    """메인 함수"""
    print("=" * 50)
    print("WDK LAB 바텀업 데이터 생성기")
    print("=" * 50)
    
    results = []
    
    for i, ticker in enumerate(TICKERS, 1):
        print(f"[{i}/{len(TICKERS)}] {ticker}...", end=" ")
        
        info = fetch_stock_data(ticker)
        if not info:
            print("❌ Failed")
            results.append({
                'ticker': ticker,
                'error': True,
                'scores': None
            })
            time.sleep(0.5)
            continue
        
        scores = calculate_scores(info)
        if scores:
            print(f"✅ Final: {scores['final']:+.2f}")
            results.append({
                'ticker': ticker,
                'error': False,
                'scores': scores
            })
        else:
            print("❌ Calc failed")
            results.append({
                'ticker': ticker,
                'error': True,
                'scores': None
            })
        
        time.sleep(0.3)  # Rate limit
    
    # 점수로 정렬
    valid_results = [r for r in results if not r['error']]
    valid_results.sort(key=lambda x: x['scores']['final'], reverse=True)
    
    # 순위 추가
    for i, r in enumerate(valid_results, 1):
        r['rank'] = i
    
    # 에러 항목 추가
    error_results = [r for r in results if r['error']]
    for r in error_results:
        r['rank'] = len(valid_results) + 1
    
    all_results = valid_results + error_results
    
    # 메타데이터
    kst = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst)
    
    output = {
        'updated': now_kst.isoformat(),
        'updated_display': now_kst.strftime('%Y. %m. %d. %p %I:%M:%S'),
        'count': len(valid_results),
        'total': len(TICKERS),
        'data': all_results
    }
    
    # JSON 파일 저장
    output_path = os.path.join(os.path.dirname(__file__), 'bottomup_data.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print("\n" + "=" * 50)
    print(f"✅ 저장 완료: {output_path}")
    print(f"📊 성공: {len(valid_results)}/{len(TICKERS)}")
    print("=" * 50)
    
    # 상위 5개 출력
    print("\n🏆 TOP 5:")
    for r in valid_results[:5]:
        s = r['scores']
        print(f"  {r['rank']}. {r['ticker']}: {s['final']:+.2f} (M:{s['momentum']:.2f}, F:{s['fundamental']:.2f}, V:{s['valuation']:.2f})")
    
    return output


if __name__ == '__main__':
    main()
