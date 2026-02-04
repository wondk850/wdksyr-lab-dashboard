"""
바텀업 데이터 생성기 v2.1 - 장기 투자자용
- Min-Max Normalization (상대 비교)
- 펀더멘탈 중심 (55%) - 실력만 본다!
- 리스크는 사람이 판단
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

# 장기 투자자용 가중치 (펀더멘탈 중심!)
WEIGHTS = {
    'momentum': 0.25,      # 25% (장기라 단기 추세 덜 중요)
    'fundamental': 0.55,   # 55% (핵심! 성장성) ← 5% 추가!
    'valuation': 0.20      # 20% (유지)
    # risk 제거: 변동성은 사람이 판단!
}


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


def collect_all_data():
    """모든 종목 데이터 수집"""
    all_data = []
    
    for i, ticker in enumerate(TICKERS, 1):
        print(f"[{i}/{len(TICKERS)}] {ticker}...", end=" ")
        
        info = fetch_stock_data(ticker)
        if not info:
            print("❌ Failed")
            all_data.append({'ticker': ticker, 'info': None, 'error': True})
            time.sleep(0.5)
            continue
        
        print("✅ OK")
        all_data.append({'ticker': ticker, 'info': info, 'error': False})
        time.sleep(0.3)
    
    return all_data


def minmax_normalize(values, inverse=False):
    """Min-Max 정규화 (-1 ~ +1 범위)
    inverse=True면 낮은 값이 좋은 것 (PE, PEG 등)
    """
    valid = [v for v in values if v is not None]
    if not valid or len(valid) < 2:
        return [0] * len(values)
    
    min_val = min(valid)
    max_val = max(valid)
    
    if max_val == min_val:
        return [0] * len(values)
    
    result = []
    for v in values:
        if v is None:
            result.append(0)
        else:
            # 0~1 범위로 정규화 후 -1~+1로 변환
            normalized = (v - min_val) / (max_val - min_val)
            if inverse:
                normalized = 1 - normalized  # 역전: 낮을수록 좋음
            # -1 ~ +1로 변환
            scaled = (normalized * 2) - 1
            result.append(scaled)
    
    return result


def calculate_raw_metrics(all_data):
    """원시 지표 추출"""
    metrics = []
    
    for item in all_data:
        if item['error']:
            metrics.append(None)
            continue
        
        info = item['info']
        
        # 모멘텀 지표
        perf_52w = safe_get(info, 'fiftyTwoWeekChange', 0) or 0
        current_price = safe_get(info, 'regularMarketPrice', 0) or 0
        sma200 = safe_get(info, 'twoHundredDayAverage', current_price) or current_price
        sma50 = safe_get(info, 'fiftyDayAverage', current_price) or current_price
        
        # 펀더멘탈 지표
        eps_growth = safe_get(info, 'earningsQuarterlyGrowth', 0) or 0
        revenue_growth = safe_get(info, 'revenueGrowth', 0) or 0
        profit_margin = safe_get(info, 'profitMargins', 0) or 0
        roe = safe_get(info, 'returnOnEquity', 0) or 0
        fcf = safe_get(info, 'freeCashflow', 0) or 0
        revenue = safe_get(info, 'totalRevenue', 1) or 1
        fcf_margin = fcf / revenue if revenue > 0 else 0
        
        # 밸류에이션 지표
        pe = safe_get(info, 'trailingPE', 50) or 50
        forward_pe = safe_get(info, 'forwardPE', 50) or 50
        peg = safe_get(info, 'pegRatio', 2) or 2
        price_to_book = safe_get(info, 'priceToBook', 5) or 5
        
        # 리스크 지표
        beta = safe_get(info, 'beta', 1.0) or 1.0
        
        metrics.append({
            'ticker': item['ticker'],
            # 모멘텀
            'perf_52w': perf_52w,
            'above_sma200': 1 if current_price > sma200 else -1,
            'above_sma50': 1 if current_price > sma50 else -1,
            # 펀더멘탈
            'eps_growth': eps_growth,
            'revenue_growth': revenue_growth,
            'profit_margin': profit_margin,
            'roe': roe,
            'fcf_margin': fcf_margin,
            # 밸류에이션 (낮을수록 좋음)
            'pe': pe,
            'forward_pe': forward_pe,
            'peg': peg,
            'price_to_book': price_to_book,
            # 리스크
            'beta': beta,
            # 원시 데이터
            'price': current_price,
            'sma200': sma200,
            'sma50': sma50
        })
    
    return metrics


def normalize_and_score(metrics):
    """정규화 및 점수 계산"""
    # 유효한 데이터만 추출
    valid_metrics = [m for m in metrics if m is not None]
    
    if len(valid_metrics) < 2:
        return []
    
    # 각 지표별 정규화
    # 모멘텀 (높을수록 좋음)
    perf_52w_norm = minmax_normalize([m['perf_52w'] for m in valid_metrics])
    
    # 펀더멘탈 (높을수록 좋음)
    eps_norm = minmax_normalize([m['eps_growth'] for m in valid_metrics])
    rev_norm = minmax_normalize([m['revenue_growth'] for m in valid_metrics])
    margin_norm = minmax_normalize([m['profit_margin'] for m in valid_metrics])
    roe_norm = minmax_normalize([m['roe'] for m in valid_metrics])
    fcf_norm = minmax_normalize([m['fcf_margin'] for m in valid_metrics])
    
    # 밸류에이션 (낮을수록 좋음 → inverse)
    pe_norm = minmax_normalize([m['pe'] for m in valid_metrics], inverse=True)
    fpe_norm = minmax_normalize([m['forward_pe'] for m in valid_metrics], inverse=True)
    peg_norm = minmax_normalize([m['peg'] for m in valid_metrics], inverse=True)
    
    # 리스크 (Beta: 1에 가까울수록 좋음, 1.5 이상이면 패널티)
    beta_scores = []
    for m in valid_metrics:
        if m['beta'] < 0.5:
            beta_scores.append(-0.3)  # 너무 낮은 베타 = 방어적
        elif m['beta'] <= 1.5:
            beta_scores.append(0.5)   # 적정 범위 = 좋음
        else:
            beta_scores.append(-0.5)  # 고베타 = 리스크 패널티
    
    # 최종 점수 계산
    results = []
    
    for i, m in enumerate(valid_metrics):
        # 모멘텀 점수 (52주 수익률 70% + SMA200 위치 20% + SMA50 위치 10%)
        momentum = (
            perf_52w_norm[i] * 0.7 +
            m['above_sma200'] * 0.2 +
            m['above_sma50'] * 0.1
        )
        # -1 ~ +1 범위로 제한
        momentum = max(-1, min(1, momentum))
        
        # 펀더멘탈 점수 (EPS 25% + Revenue 20% + Margin 20% + ROE 20% + FCF 15%)
        fundamental = (
            eps_norm[i] * 0.25 +
            rev_norm[i] * 0.20 +
            margin_norm[i] * 0.20 +
            roe_norm[i] * 0.20 +
            fcf_norm[i] * 0.15
        )
        fundamental = max(-1, min(1, fundamental))
        
        # 밸류에이션 점수 (Forward PE 40% + PEG 35% + Trailing PE 25%)
        valuation = (
            fpe_norm[i] * 0.40 +
            peg_norm[i] * 0.35 +
            pe_norm[i] * 0.25
        )
        valuation = max(-1, min(1, valuation))
        
        # 리스크 점수
        risk = beta_scores[i]
        
        # 최종 점수 (가중 합계) - 리스크 제외!
        final = (
            WEIGHTS['momentum'] * momentum +
            WEIGHTS['fundamental'] * fundamental +
            WEIGHTS['valuation'] * valuation
        )
        final = max(-1, min(1, final))
        
        results.append({
            'ticker': m['ticker'],
            'error': False,
            'scores': {
                'momentum': round(momentum, 2),
                'fundamental': round(fundamental, 2),
                'valuation': round(valuation, 2),
                'risk': round(risk, 2),
                'final': round(final, 2)
            },
            'raw': {
                'price': m['price'],
                'sma200': m['sma200'],
                '52w_change': m['perf_52w'],
                'eps_growth': m['eps_growth'],
                'revenue_growth': m['revenue_growth'],
                'profit_margin': m['profit_margin'],
                'roe': m['roe'],
                'fcf_margin': m['fcf_margin'],
                'pe': m['pe'],
                'forward_pe': m['forward_pe'],
                'peg': m['peg'],
                'beta': m['beta']
            }
        })
    
    return results


def main():
    """메인 함수"""
    print("=" * 50)
    print("WDK LAB 바텀업 데이터 생성기 v2.0")
    print("📊 장기 투자자용 (Min-Max 상대 비교)")
    print("=" * 50)
    
    # 1. 데이터 수집
    print("\n📡 데이터 수집 중...")
    all_data = collect_all_data()
    
    # 2. 지표 추출
    print("\n📈 지표 분석 중...")
    metrics = calculate_raw_metrics(all_data)
    
    # 3. 정규화 및 점수 계산
    print("🔢 점수 계산 중...")
    results = normalize_and_score(metrics)
    
    # 4. 정렬
    results.sort(key=lambda x: x['scores']['final'], reverse=True)
    
    # 5. 순위 추가
    for i, r in enumerate(results, 1):
        r['rank'] = i
    
    # 6. 에러 항목 추가
    error_tickers = [d['ticker'] for d in all_data if d['error']]
    for ticker in error_tickers:
        results.append({
            'ticker': ticker,
            'error': True,
            'scores': None,
            'rank': len(results) + 1
        })
    
    # 메타데이터
    kst = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst)
    
    output = {
        'version': '2.0',
        'updated': now_kst.isoformat(),
        'updated_display': now_kst.strftime('%Y. %m. %d. %p %I:%M:%S'),
        'count': len([r for r in results if not r.get('error', False)]),
        'total': len(TICKERS),
        'weights': WEIGHTS,
        'data': results
    }
    
    # JSON 저장
    output_path = os.path.join(os.path.dirname(__file__), 'bottomup_data.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print("\n" + "=" * 50)
    print(f"✅ 저장 완료: {output_path}")
    print(f"📊 성공: {output['count']}/{output['total']}")
    print("=" * 50)
    
    # 상위 5개 출력
    print("\n🏆 TOP 5:")
    for r in results[:5]:
        if r.get('error'):
            continue
        s = r['scores']
        print(f"  {r['rank']}. {r['ticker']}: {s['final']:+.2f}")
        print(f"      M:{s['momentum']:+.2f} F:{s['fundamental']:+.2f} V:{s['valuation']:+.2f} R:{s['risk']:+.2f}")
    
    # 하위 3개 출력
    print("\n⚠️ BOTTOM 3:")
    valid_results = [r for r in results if not r.get('error', False)]
    for r in valid_results[-3:]:
        s = r['scores']
        print(f"  {r['rank']}. {r['ticker']}: {s['final']:+.2f}")
    
    return output


if __name__ == '__main__':
    main()
