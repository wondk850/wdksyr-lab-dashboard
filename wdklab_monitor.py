"""
WDK LAB Signal Monitor - GitHub Actions용 스크립트
FRED 데이터 수집 → 신호등 계산 → 바텀업 분석 → 텔레그램 발송
"""

import os
import json
import requests
import time
from datetime import datetime, timezone, timedelta

# ===== 설정 =====
FRED_API_KEY = os.environ.get('FRED_API_KEY', 'bd2f35437a05410f3f72fa653ab8935c')
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '8209005017:AAH1IOr7h49dI3lX2TSBNOrvMsQEIcHCouM')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '1489387702')

# FRED 시리즈 ID
FRED_SERIES = {
    'DGS2': 'DGS2',           # 2년물 국채
    'DGS10': 'DGS10',         # 10년물 국채
    'VIXCLS': 'VIXCLS',       # VIX
    'BAMLC0A0CM': 'BAMLC0A0CM',  # BAA 스프레드
    'UNRATE': 'UNRATE',       # 실업률
    'DTWEXBGS': 'DTWEXBGS',   # 달러 인덱스
    'PCEPILFE': 'PCEPILFE',   # Core PCE
}

# 바텀업 티커
TICKERS = [
    'MSFT', 'AAPL', 'GOOGL', 'AMZN', 'META', 'TSLA',  # Big Tech
    'NVDA', 'TSM', 'ASML',                             # Semiconductors
    'LLY',                                             # Healthcare
    'JPM', 'V',                                        # Financials
    'XOM',                                             # Energy
    'WMT', 'COST',                                     # Consumer Staples
    'GE', 'CAT'                                        # Industrials
]

# 바텀업 가중치
BOTTOMUP_WEIGHTS = {'momentum': 0.45, 'fundamental': 0.35, 'valuation': 0.20}

# 탑다운 가중치
WEIGHTS = {'fed': 50, 'inflation': 30, 'context': 20}

# 임계값
THRESHOLDS = {
    'king': 10,      # bp
    'pce_yoy': 2.6,  # %
    'pce_3m': 2.2,   # %
    'vix': 18,
}

# 상태 저장 파일
STATE_FILE = 'signal_state.json'


def fetch_fred_series(series_id, limit=252):
    """FRED API에서 데이터 가져오기"""
    url = f"https://api.stlouisfed.org/fred/series/observations"
    params = {
        'series_id': series_id,
        'api_key': FRED_API_KEY,
        'file_type': 'json',
        'sort_order': 'desc',
        'limit': limit
    }
    
    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        
        observations = data.get('observations', [])
        result = []
        for obs in observations:
            if obs['value'] not in ['.', '']:
                result.append({
                    'date': obs['date'],
                    'value': float(obs['value'])
                })
        
        return list(reversed(result))  # oldest first
    except Exception as e:
        print(f"[FRED] Error fetching {series_id}: {e}")
        return []


def fetch_yahoo_data(ticker):
    """yfinance 라이브러리로 주식 데이터 가져오기 (GitHub Actions 호환!)"""
    try:
        import yfinance as yf
        stock = yf.Ticker(ticker)
        info = stock.info
        
        if not info or 'regularMarketPrice' not in info:
            print(f"[yfinance] No data for {ticker}")
            return None
        
        # yfinance 형식으로 반환 (기존 코드와 호환)
        return {
            'price': {
                'regularMarketPrice': {'raw': info.get('regularMarketPrice', 0)}
            },
            'summaryDetail': {
                'twoHundredDayAverage': {'raw': info.get('twoHundredDayAverage', 0)},
                'trailingPE': {'raw': info.get('trailingPE', 50)},
                'forwardPE': {'raw': info.get('forwardPE', 50)}
            },
            'defaultKeyStatistics': {
                'fiftyTwoWeekChange': {'raw': info.get('fiftyTwoWeekChange', 0)},
                'earningsQuarterlyGrowth': {'raw': info.get('earningsQuarterlyGrowth', 0)},
                'pegRatio': {'raw': info.get('pegRatio', 2)}
            },
            'financialData': {
                'profitMargins': {'raw': info.get('profitMargins', 0)},
                'returnOnEquity': {'raw': info.get('returnOnEquity', 0)}
            }
        }
    except Exception as e:
        print(f"[yfinance] Error fetching {ticker}: {e}")
        return None


def safe_get(data, *keys, default=None):
    """중첩 딕셔너리에서 안전하게 값 가져오기"""
    for key in keys:
        if isinstance(data, dict):
            data = data.get(key, {})
        else:
            return default
    if isinstance(data, dict):
        return data.get('raw', data.get('fmt', default))
    return data if data else default


def calculate_bottomup_scores():
    """바텀업 점수 계산"""
    print("[BOTTOMUP] Fetching stock data...")
    scores = []
    
    for ticker in TICKERS:
        print(f"  - {ticker}...", end=" ")
        data = fetch_yahoo_data(ticker)
        
        if not data:
            print("❌ Failed")
            scores.append({'ticker': ticker, 'score': None, 'error': True})
            time.sleep(0.5)
            continue
        
        try:
            price = data.get('price', {})
            summary = data.get('summaryDetail', {})
            keyStats = data.get('defaultKeyStatistics', {})
            financial = data.get('financialData', {})
            
            # 모멘텀 지표
            perf_52w = safe_get(keyStats, 'fiftyTwoWeekChange', default=0) or 0
            current_price = safe_get(price, 'regularMarketPrice', default=0) or 0
            sma200 = safe_get(summary, 'twoHundredDayAverage', default=current_price) or current_price
            above_sma200 = 1 if current_price > sma200 else -1
            
            # 펀더멘탈 지표
            eps_growth = safe_get(keyStats, 'earningsQuarterlyGrowth', default=0) or 0
            profit_margin = safe_get(financial, 'profitMargins', default=0) or 0
            roe = safe_get(financial, 'returnOnEquity', default=0) or 0
            
            # 밸류에이션 지표
            pe = safe_get(summary, 'trailingPE', default=50) or 50
            forward_pe = safe_get(summary, 'forwardPE', default=50) or 50
            peg = safe_get(keyStats, 'pegRatio', default=2) or 2
            
            # 정규화 (간단한 버전)
            momentum_score = (perf_52w * 2) + (above_sma200 * 0.3)
            fundamental_score = (eps_growth * 2) + (profit_margin * 3) + (roe * 2)
            
            # PE가 낮을수록 좋음 (역수 사용)
            valuation_score = 1 - min(pe / 100, 1)  # PE 100 이상이면 0
            
            # 최종 점수
            final_score = (
                BOTTOMUP_WEIGHTS['momentum'] * momentum_score +
                BOTTOMUP_WEIGHTS['fundamental'] * fundamental_score +
                BOTTOMUP_WEIGHTS['valuation'] * valuation_score
            )
            
            scores.append({
                'ticker': ticker,
                'score': round(final_score, 2),
                'momentum': round(momentum_score, 2),
                'fundamental': round(fundamental_score, 2),
                'valuation': round(valuation_score, 2),
                'error': False
            })
            print(f"✅ {final_score:.2f}")
            
        except Exception as e:
            print(f"❌ Error: {e}")
            scores.append({'ticker': ticker, 'score': None, 'error': True})
        
        time.sleep(0.3)  # Rate limit 방지
    
    # 점수로 정렬
    valid_scores = [s for s in scores if s['score'] is not None]
    valid_scores.sort(key=lambda x: x['score'], reverse=True)
    
    return valid_scores


def calculate_signal():
    """신호등 계산"""
    data = {}
    
    # 데이터 수집
    print("[DATA] Fetching FRED data...")
    for key, series_id in FRED_SERIES.items():
        data[key] = fetch_fred_series(series_id)
        print(f"  - {key}: {len(data[key])} points")
    
    # 최신 값 추출
    latest = {}
    for key, values in data.items():
        if values:
            latest[key] = values[-1]['value']
        else:
            latest[key] = 0
    
    # === King (연준) 계산 ===
    dgs2_data = data.get('DGS2', [])
    if len(dgs2_data) >= 21:
        dgs2_now = dgs2_data[-1]['value']
        dgs2_20d_ago = dgs2_data[-21]['value']
        dgs2_change_bp = (dgs2_now - dgs2_20d_ago) * 100
    else:
        dgs2_change_bp = 0
    
    if dgs2_change_bp <= -THRESHOLDS['king']:
        fed_signal = 1
    elif dgs2_change_bp >= THRESHOLDS['king']:
        fed_signal = -1
    else:
        fed_signal = 0
    
    # === Queen (인플레이션) 계산 ===
    pce_data = data.get('PCEPILFE', [])
    if len(pce_data) >= 12:
        pce_now = pce_data[-1]['value']
        pce_12m_ago = pce_data[-12]['value']
        pce_yoy = ((pce_now / pce_12m_ago) - 1) * 100
    else:
        pce_yoy = 2.5
    
    if len(pce_data) >= 3:
        pce_3m_ago = pce_data[-3]['value']
        pce_3m_ann = ((pce_now / pce_3m_ago) ** 4 - 1) * 100
    else:
        pce_3m_ann = 2.5
    
    if pce_yoy <= THRESHOLDS['pce_yoy'] and pce_3m_ann <= THRESHOLDS['pce_3m']:
        inflation_signal = 1
    elif pce_yoy > THRESHOLDS['pce_yoy'] and pce_3m_ann > THRESHOLDS['pce_3m']:
        inflation_signal = -1
    else:
        inflation_signal = 0
    
    # === Context (리스크) 계산 ===
    context_scores = []
    
    # VIX
    vix = latest.get('VIXCLS', 20)
    if vix <= THRESHOLDS['vix']:
        context_scores.append(1)
    elif vix >= 30:
        context_scores.append(-1)
    else:
        context_scores.append(0)
    
    # 10Y-2Y 스프레드
    spread = latest.get('DGS10', 0) - latest.get('DGS2', 0)
    if spread >= 0.25:
        context_scores.append(1)
    elif spread <= -0.25:
        context_scores.append(-1)
    else:
        context_scores.append(0)
    
    # BAA 스프레드
    baa = latest.get('BAMLC0A0CM', 2)
    if baa <= 2.0:
        context_scores.append(1)
    elif baa >= 3.0:
        context_scores.append(-1)
    else:
        context_scores.append(0)
    
    context_mean = sum(context_scores) / len(context_scores) if context_scores else 0
    if context_mean > 0.33:
        context_signal = 1
    elif context_mean < -0.33:
        context_signal = -1
    else:
        context_signal = 0
    
    # === 종합 점수 ===
    composite = (
        (WEIGHTS['fed'] / 100) * fed_signal +
        (WEIGHTS['inflation'] / 100) * inflation_signal +
        (WEIGHTS['context'] / 100) * context_signal
    )
    
    # 최종 신호
    if composite > 0.2:
        final_signal = 'GREEN'
    elif composite < -0.2:
        final_signal = 'RED'
    else:
        final_signal = 'YELLOW'
    
    return {
        'signal': final_signal,
        'composite': composite,
        'fed_signal': fed_signal,
        'inflation_signal': inflation_signal,
        'context_signal': context_signal,
        'dgs2_change_bp': dgs2_change_bp,
        'pce_yoy': pce_yoy,
        'pce_3m_ann': pce_3m_ann,
        'vix': vix,
        'spread': spread,
        'timestamp': datetime.now(timezone.utc).isoformat()
    }


def send_telegram(message):
    """텔레그램 메시지 발송"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message,
        'parse_mode': 'HTML'
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        print("[Telegram] Message sent successfully")
        return True
    except Exception as e:
        print(f"[Telegram] Error: {e}")
        return False


def load_state():
    """이전 상태 로드"""
    try:
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    except:
        return {'previous_signal': None}


def check_vix_alert(vix_value, state):
    """VIX 25+ 알림 체크 (공포 구간 = 매수 기회!)"""
    VIX_ALERT_THRESHOLD = 25
    
    # 이전 VIX 알림 상태 확인
    last_vix_alert = state.get('last_vix_alert', False)
    
    if vix_value >= VIX_ALERT_THRESHOLD and not last_vix_alert:
        # VIX가 25 넘었고, 이전에 알림 안 보냈으면 알림!
        kst = timezone(timedelta(hours=9))
        now_kst = datetime.now(kst).strftime('%Y-%m-%d %H:%M KST')
        
        alert_level = "🚨 공포" if vix_value >= 30 else "⚠️ 경계"
        
        msg = f"""🔔 <b>VIX Alert! 공포 구간 진입!</b>

{alert_level} <b>VIX: {vix_value:.1f}</b>

📌 <b>의미:</b>
• VIX 25+ = 시장 공포 구간
• 역사적으로 매수 기회일 가능성!

💡 <b>액션:</b>
• 바텀업 종목 확인하기
• 현금 확보 상태 점검
• 분할 매수 고려

⚠️ 주의: 하락이 더 올 수 있음!

⏰ {now_kst}"""
        
        send_telegram(msg)
        print(f"[VIX ALERT] VIX {vix_value:.1f} - Alert sent!")
        return True
    
    elif vix_value < VIX_ALERT_THRESHOLD and last_vix_alert:
        # VIX가 25 미만으로 돌아왔으면 알림 해제
        print(f"[VIX] VIX {vix_value:.1f} - Below threshold, resetting alert")
        return False
    
    return last_vix_alert


def save_state(state):
    """상태 저장"""
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f)
    except Exception as e:
        print(f"[State] Error saving: {e}")


def format_signal_message(result, is_change=False):
    """신호 메시지 포맷팅"""
    signal_emoji = {
        'GREEN': '🟢',
        'YELLOW': '🟡',
        'RED': '🔴'
    }
    
    emoji = signal_emoji.get(result['signal'], '⚪')
    
    # 한국 시간
    kst = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst).strftime('%Y-%m-%d %H:%M KST')
    
    if is_change:
        title = "🚨 <b>WDK LAB Signal Change!</b>"
    else:
        title = "📊 <b>WDK LAB Signal Report</b>"
    
    msg = f"""{title}

{emoji} <b>Current Signal: {result['signal']}</b>

<b>📈 Details:</b>
• King (Fed): {'+1' if result['fed_signal'] > 0 else ('-1' if result['fed_signal'] < 0 else '0')} (2Y Δ: {result['dgs2_change_bp']:.0f}bp)
• Queen (Inflation): {'+1' if result['inflation_signal'] > 0 else ('-1' if result['inflation_signal'] < 0 else '0')} (PCE YoY: {result['pce_yoy']:.1f}%)
• Context (Risk): {'+1' if result['context_signal'] > 0 else ('-1' if result['context_signal'] < 0 else '0')} (VIX: {result['vix']:.1f})

<b>📊 Composite Score:</b> {result['composite']:.2f}

⏰ {now_kst}"""
    
    return msg


def format_daily_report(result, bottomup_scores=None):
    """일일 리포트 포맷팅 (바텀업 포함)"""
    signal_emoji = {
        'GREEN': '🟢 GREEN - 비중 확대',
        'YELLOW': '🟡 YELLOW - 비중 유지',
        'RED': '🔴 RED - 비중 축소'
    }
    
    kst = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst)
    date_str = now_kst.strftime('%Y년 %m월 %d일 %A')
    
    msg = f"""📋 <b>WDK LAB Daily Report</b>
{date_str}

🚦 <b>Today's Signal:</b>
{signal_emoji.get(result['signal'], result['signal'])}

<b>📊 Key Indicators:</b>
• VIX: {result['vix']:.1f}
• 10Y-2Y Spread: {result['spread']:.2f}%
• PCE YoY: {result['pce_yoy']:.1f}%
• 2Y Treasury Δ20d: {result['dgs2_change_bp']:.0f}bp

<b>📈 Composite Score:</b> {result['composite']:.2f}"""
    
    # 바텀업 추가
    if bottomup_scores and len(bottomup_scores) >= 5:
        top5 = bottomup_scores[:5]
        worst3 = bottomup_scores[-3:]
        
        msg += "\n\n<b>🏆 Bottom-Up TOP 5:</b>"
        for i, s in enumerate(top5, 1):
            msg += f"\n{i}. {s['ticker']} ({s['score']:+.2f})"
        
        msg += "\n\n<b>⚠️ WORST 3:</b>"
        for i, s in enumerate(reversed(worst3), 1):
            msg += f"\n{i}. {s['ticker']} ({s['score']:+.2f})"
        
        # 추천
        if result['signal'] == 'GREEN':
            msg += f"\n\n💡 <b>추천:</b> {top5[0]['ticker']}, {top5[1]['ticker']} 비중 확대 고려"
        elif result['signal'] == 'RED':
            msg += f"\n\n💡 <b>추천:</b> 신규 매수 자제, 현금 비중 확대"
        else:
            msg += f"\n\n💡 <b>추천:</b> 관망, {top5[0]['ticker']} 분할 매수 고려"
    
    msg += "\n\nHave a great trading day! 🚀"
    
    return msg


def main(mode='check'):
    """메인 함수"""
    print(f"[WDK LAB] Running in {mode} mode...")
    
    # 신호 계산
    result = calculate_signal()
    print(f"[Signal] Current: {result['signal']} (score: {result['composite']:.2f})")
    
    # 이전 상태 로드
    state = load_state()
    previous_signal = state.get('previous_signal')
    
    # VIX 알림 체크 (공포 구간!)
    vix_alert_status = check_vix_alert(result['vix'], state)
    state['last_vix_alert'] = vix_alert_status
    
    if mode == 'daily':
        # 일일 리포트 (바텀업 포함!)
        bottomup_scores = calculate_bottomup_scores()
        msg = format_daily_report(result, bottomup_scores)
        send_telegram(msg)
        
    elif mode == 'check':
        # 신호 변경 체크
        if previous_signal and previous_signal != result['signal']:
            print(f"[Signal] Changed! {previous_signal} → {result['signal']}")
            msg = format_signal_message(result, is_change=True)
            send_telegram(msg)
        else:
            print(f"[Signal] No change ({result['signal']})")
            # 변경 없으면 알림 안 보냄 (로그만)
    
    elif mode == 'report':
        # 신호 리포트 (바텀업 포함!)
        bottomup_scores = calculate_bottomup_scores()
        msg = format_daily_report(result, bottomup_scores)
        send_telegram(msg)
    
    # 상태 저장
    state['previous_signal'] = result['signal']
    state['last_check'] = result['timestamp']
    save_state(state)
    
    print("[WDK LAB] Done!")


if __name__ == '__main__':
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else 'check'
    main(mode)
