"""
WDK LAB Signal Monitor - GitHub Actions용 스크립트
FRED 데이터 수집 → 신호등 계산 → 바텀업 분석 → 텔레그램 발송
"""

import os
import json
import requests
import time
from datetime import datetime, timezone, timedelta

# pandas_ta 사용 가능 여부 (없으면 RSI/MACD graceful skip)
try:
    import pandas_ta  # noqa: F401
    HAS_PANDAS_TA = True
except ImportError:
    HAS_PANDAS_TA = False

# ===== 설정 =====
FRED_API_KEY = os.environ.get('FRED_API_KEY', 'bd2f35437a05410f3f72fa653ab8935c')
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '8209005017:AAH1IOr7h49dI3lX2TSBNOrvMsQEIcHCouM')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '1489387702')
FINNHUB_TOKEN = os.environ.get('FINNHUB_TOKEN', '')

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


def fetch_portfolio_summary():
    """
    portfolio.json → yfinance 1년치 데이터 → 당일손익 + Sharpe/MDD/Volatility + RSI/MACD
    반환: {'total_krw', 'day_pnl', 'day_pct', 'sharpe', 'mdd', 'volatility',
           'top_movers', 'scout_alerts', 'rsi_signals'}
    """
    pf_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'portfolio.json')
    if not os.path.exists(pf_path):
        print("[PF] portfolio.json 없음 — 건너뜀")
        return None

    try:
        import numpy as np
        import yfinance as yf

        with open(pf_path, encoding='utf-8') as f:
            pf = json.load(f)

        holdings        = pf.get('holdings', [])
        usd_krw         = pf.get('usd_krw', 1430)
        scout_threshold = pf.get('scout_drop_threshold_pct', 3.0)
        tickers         = [h['ticker'] for h in holdings]
        shares_map      = {h['ticker']: h['shares'] for h in holdings}
        type_map        = {h['ticker']: h.get('type', 'core') for h in holdings}

        if not tickers:
            return None

        # ── 1년치 데이터 다운로드 (Sharpe/MDD/RSI/MACD 모두 여기서 계산) ──
        data   = yf.download(tickers, period='1y', progress=False, auto_adjust=True)
        closes = data['Close'] if len(tickers) > 1 else data[['Close']]
        if len(tickers) == 1:
            closes.columns = tickers
        # ── closes 실제 가격 디버그 (비중 버그 원인 추적) ──────────────
        for _t in tickers[:3]:  # 첫 3종목만 출력
            try:
                _p = float(closes[_t].dropna().iloc[-1])
                print(f"[PF-DEBUG] {_t} close=${_p:.2f}")
            except Exception as _e:
                print(f"[PF-DEBUG] {_t} 오류: {_e}")

        # ── 현재 평가액 기준 비중 계산 ────────────────────────────────────
        weights   = {}
        total_val = 0.0
        for t in tickers:
            try:
                curr = float(closes[t].dropna().iloc[-1])
                val  = curr * shares_map[t]
                weights[t] = val
                total_val += val
            except Exception:
                weights[t] = 0.0

        # ── 당일 손익 + 평가액 계산 ───────────────────────────────────────
        daily_returns_list = []
        results   = []
        total_krw = 0.0
        day_pnl   = 0.0

        for h in holdings:
            t      = h['ticker']
            shares = h['shares']
            try:
                prices = closes[t].dropna()
                if len(prices) < 2:
                    continue
                prev     = float(prices.iloc[-2])
                curr     = float(prices.iloc[-1])
                val_krw  = curr * shares * usd_krw
                pnl_krw  = (curr - prev) * shares * usd_krw
                pct      = (curr / prev - 1) * 100
                total_krw += val_krw
                day_pnl   += pnl_krw
                results.append({'ticker': t, 'val_krw': round(val_krw),
                                'pnl_krw': round(pnl_krw), 'pct': round(pct, 2),
                                'type': type_map.get(t, 'core')})
                # 비중 반영 일일 수익률
                w = weights.get(t, 0) / total_val if total_val else 0
                daily_returns_list.append(prices.pct_change().dropna() * w)
            except Exception:
                continue

        # ── 리스크 지표 (risk-metrics-calculation 스킬 적용) ──────────────
        sharpe = mdd = volatility = None
        try:
            if daily_returns_list:
                port_returns = sum(daily_returns_list)
                ann_ret  = float(port_returns.mean() * 252)
                ann_vol  = float(port_returns.std() * np.sqrt(252))
                rf       = 0.04                              # 무위험수익률 4%
                sharpe     = round((ann_ret - rf) / ann_vol, 2) if ann_vol else None
                volatility = round(ann_vol * 100, 1)        # %/yr
                cum  = (1 + port_returns).cumprod()
                peak = cum.cummax()
                mdd  = round(float(((cum - peak) / peak).min()) * 100, 1)  # %
                print(f"[PF] 📐 Sharpe:{sharpe}  MDD:{mdd}%  Volatility:{volatility}%/yr")
        except Exception as e:
            print(f"[PF] 리스크 계산 실패: {e}")

        # ── RSI/MACD 직접 계산 (1y 데이터로 계산, bottomup_data.json 불필요) ─
        rsi_signals = {'overbought': [], 'oversold': [], 'macd_buy': [], 'macd_sell': []}
        try:
            if HAS_PANDAS_TA:
                import pandas_ta as ta
                for t in tickers:
                    try:
                        s = closes[t].dropna()
                        if len(s) < 30:
                            continue
                        rsi_val = float(ta.rsi(s, length=14).iloc[-1])
                        macd_df = ta.macd(s)
                        cross   = 0
                        if macd_df is not None and len(macd_df.columns) >= 2:
                            cross = 1 if float(macd_df.iloc[-1, 0]) > float(macd_df.iloc[-1, 1]) else -1
                        if rsi_val >= 65:
                            rsi_signals['overbought'].append(f"{t}({rsi_val:.0f})")
                        elif rsi_val <= 35:
                            rsi_signals['oversold'].append(f"{t}({rsi_val:.0f})")
                        if cross == 1:
                            rsi_signals['macd_buy'].append(t)
                        elif cross == -1:
                            rsi_signals['macd_sell'].append(t)
                    except Exception:
                        continue
                print(f"[PF] RSI 과매수:{rsi_signals['overbought']} 과매도:{rsi_signals['oversold']}")
        except Exception as e:
            print(f"[PF] RSI/MACD 계산 실패: {e}")

        # ── scout/core 분리 ───────────────────────────────────────────────
        scout_alerts, core_results = [], []
        for r in results:
            t = r['ticker']
            if type_map.get(t) == 'scout' and r['pct'] <= -scout_threshold:
                scout_alerts.append(r)
            if type_map.get(t) == 'core':
                core_results.append(r)

        core_sorted         = sorted(core_results, key=lambda x: x['pct'], reverse=True)
        top_movers          = core_sorted[:3] + core_sorted[-3:]
        scout_alerts_sorted = sorted(scout_alerts, key=lambda x: x['pct'])

        print(f"[PF] ✅ 총 {len(results)}종목  ₩{total_krw:,.0f}  당일 {day_pnl:+,.0f}원")
        if scout_alerts:
            print(f"[PF] 🎯 선발대: {[a['ticker'] for a in scout_alerts]}")

        return {
            'total_krw':    round(total_krw),
            'day_pnl':      round(day_pnl),
            'day_pct':      round(day_pnl / (total_krw - day_pnl) * 100, 2) if total_krw else 0,
            'sharpe':       sharpe,
            'mdd':          mdd,
            'volatility':   volatility,
            'results':      results,           # 전체 보유 종목 (ai_block + action_hint용)
            'top_movers':   top_movers,
            'scout_alerts': scout_alerts_sorted,
            'rsi_signals':  rsi_signals
        }

    except Exception as e:
        print(f"[PF] ❌ 실패: {e}")
        return None


def get_economic_calendar():
    """
    주요 경제 이벤트 D-N 카운트다운
    Finnhub 성공 시 실제 이벤트, 실패 시 하드코딩 fallback
    """
    kst = timezone(timedelta(hours=9))
    today = datetime.now(kst).date()

    events = []

    # Finnhub 시도
    if FINNHUB_TOKEN:
        try:
            from_date = today.strftime('%Y-%m-%d')
            to_date   = (today + timedelta(days=30)).strftime('%Y-%m-%d')
            r = requests.get(
                'https://finnhub.io/api/v1/calendar/economic',
                params={'token': FINNHUB_TOKEN, 'from': from_date, 'to': to_date},
                timeout=10
            )
            data = r.json().get('economicCalendar', [])
            keywords = ['FOMC', 'Federal Reserve', 'CPI', 'PCE', 'Nonfarm', 'GDP', 'Unemployment']
            for ev in data:
                name = ev.get('event', '')
                if any(k.lower() in name.lower() for k in keywords):
                    ev_date = datetime.strptime(ev['time'][:10], '%Y-%m-%d').date()
                    diff = (ev_date - today).days
                    if 0 <= diff <= 30:
                        events.append({'name': name[:30], 'days': diff})
            events.sort(key=lambda x: x['days'])
            events = events[:4]
            if events:
                print(f"[CAL] Finnhub 성공: {len(events)}개 이벤트")
                return events
        except Exception as e:
            print(f"[CAL] Finnhub 실패: {e} — fallback 사용")

    # Fallback: 하드코딩 주요 이벤트 (2026년)
    hardcoded = [
        {'name': 'FOMC 결정',  'date': '2026-04-30'},
        {'name': 'FOMC 결정',  'date': '2026-06-18'},
        {'name': 'CPI 발표',   'date': '2026-03-12'},
        {'name': 'PCE 발표',   'date': '2026-03-28'},
        {'name': 'Nonfarm 고용', 'date': '2026-04-03'},
        {'name': 'CPI 발표',   'date': '2026-04-10'},
        {'name': 'PCE 발표',   'date': '2026-04-30'},
    ]
    for ev in hardcoded:
        ev_date = datetime.strptime(ev['date'], '%Y-%m-%d').date()
        diff = (ev_date - today).days
        if 0 <= diff <= 30:
            events.append({'name': ev['name'], 'days': diff})
    events.sort(key=lambda x: x['days'])
    return events[:4]


def format_morning_digest(result, bottomup_scores=None, state=None, pf_summary=None):
    """🌅 Morning Digest: Composite Δ, 탑다운, 바텀업 TOP5, 경제캘린더, 포트폴리오"""
    signal_emoji = {'GREEN': '🟢 GREEN — 비중 확대',
                    'YELLOW': '🟡 YELLOW — 비중 유지',
                    'RED': '🔴 RED — 비중 축소'}
    kst = timezone(timedelta(hours=9))
    now_kst  = datetime.now(kst)
    date_str = now_kst.strftime('%m/%d (%a)')

    # 신호등 심볼
    sig_text = signal_emoji.get(result['signal'], result['signal'])

    # 전일比 Composite 변화량
    prev_comp  = state.get('prev_composite') if state else None
    curr_comp  = result['composite']
    if prev_comp is not None:
        delta = curr_comp - prev_comp
        delta_str = f" ({'+' if delta >= 0 else ''}{delta:.2f})"
    else:
        delta_str = ''

    # 전일比 VIX 변화량
    prev_vix = state.get('prev_vix') if state else None
    if prev_vix is not None:
        vix_delta  = result['vix'] - prev_vix
        if abs(vix_delta) < 0.05:
            vix_str = f"{result['vix']:.1f} (→)"
        else:
            vix_arrow = '▲' if vix_delta > 0 else '▼'
            vix_str   = f"{result['vix']:.1f} ({vix_arrow}{abs(vix_delta):.1f})"
    else:
        vix_str    = f"{result['vix']:.1f}"

    # 전일比 Spread 변화량
    prev_spread = state.get('prev_spread') if state else None
    if prev_spread is not None:
        sp_delta   = result['spread'] - prev_spread
        if abs(sp_delta) < 0.005:
            spread_str = f"{result['spread']:+.2f}% (→)"
        else:
            sp_arrow   = '▲' if sp_delta > 0 else '▼'
            spread_str = f"{result['spread']:+.2f}% ({sp_arrow}{abs(sp_delta):.2f}%)"
    else:
        spread_str = f"{result['spread']:+.2f}%"

    # 경제 캘린더
    cal_events = get_economic_calendar()
    cal_lines  = ''
    if cal_events:
        cal_lines = '\n\n📅 <b>예정 이벤트:</b>'
        for ev in cal_events:
            if ev['days'] == 0:
                cal_lines += f'\n• ⚠️ {ev["name"]} — <b>오늘!</b>'
            elif ev['days'] <= 3:
                cal_lines += f'\n• 🔔 {ev["name"]} — D-{ev["days"]}'
            else:
                cal_lines += f'\n• {ev["name"]} — D-{ev["days"]}'

    # 바텐업 TOP5
    bu_lines = ''
    if bottomup_scores and len(bottomup_scores) >= 5:
        top5  = bottomup_scores[:5]
        bu_lines = '\n\n🏆 <b>Bottom-Up TOP 5:</b>'
        for i, s in enumerate(top5, 1):
            # 전일 순위와 비교
            prev_rank = (state.get('prev_bottomup_ranks') or {}).get(s['ticker'])
            if prev_rank and prev_rank != i:
                rank_arrow = '↑' if prev_rank > i else '↓'
            else:
                rank_arrow = ''
            bu_lines += f'\n{i}. {s["ticker"]} ({s["score"]:+.2f}) {rank_arrow}'

    # 흐름
    action_hint = ''
    if result['signal'] == 'GREEN':
        top_ticker = top5[0]['ticker'] if bottomup_scores else ''
        # 당일 급락 중인지 체크 (-3% 이상이면 경고)
        crash_pct = None
        if pf_summary:
            for r in pf_summary.get('results', []):
                if r['ticker'] == top_ticker:
                    crash_pct = r['pct']
                    break
        # results에서 못 찾으면 top_movers에서 fallback
        if crash_pct is None and pf_summary:
            for r in pf_summary.get('top_movers', []):
                if r['ticker'] == top_ticker:
                    crash_pct = r['pct']
                    break
        if crash_pct is not None and crash_pct <= -3.0:
            action_hint = f'\n\n💡 <b>행동:</b> {top_ticker} 비중 확대 검토 ⚠️ 급락 중({crash_pct:.1f}%) — 분할 접근'
        else:
            action_hint = f'\n\n💡 <b>행동:</b> {top_ticker} 비중 확대 검토'
    elif result['signal'] == 'RED':
        action_hint = '\n\n💡 <b>행동:</b> 신규 매수 자제, 현금 비중 확대'
    else:
        action_hint = '\n\n💡 <b>행동:</b> 관망, 분할매수 검토'

    # 포트폴리오 요약
    pf_lines = ''
    if pf_summary:
        sign = '+' if pf_summary['day_pnl'] >= 0 else ''
        pf_lines = f"\n\n💼 <b>포트폴리오 (US주식):</b>"
        pf_lines += f"\n• 평가액: ₩{pf_summary['total_krw']:,}"
        pf_lines += f"\n• 당일 손익: {sign}₩{pf_summary['day_pnl']:,} ({sign}{pf_summary['day_pct']:.2f}%)"
        # 리스크 지표
        r_parts = []
        if pf_summary.get('sharpe') is not None:
            r_parts.append(f"Sharpe {pf_summary['sharpe']:.2f}")
        if pf_summary.get('mdd') is not None:
            r_parts.append(f"MDD {pf_summary['mdd']}%")
        if pf_summary.get('volatility') is not None:
            r_parts.append(f"변동성 {pf_summary['volatility']}%/yr")
        if r_parts:
            pf_lines += '\n• 📐 ' + '  |  '.join(r_parts)
        movers = pf_summary.get('top_movers', [])
        if movers:
            winners = [m for m in movers if m['pct'] >= 0][:3]
            losers  = [m for m in movers if m['pct'] <  0][-3:]
            if winners:
                pf_lines += '\n🔺 ' + '  '.join(f"{m['ticker']}({m['pct']:+.1f}%)" for m in winners)
            if losers:
                pf_lines += '\n🔻 ' + '  '.join(f"{m['ticker']}({m['pct']:+.1f}%)" for m in losers)
        # 선발대 매수 기회
        scouts = pf_summary.get('scout_alerts', [])
        if scouts:
            pf_lines += '\n\n🎯 <b>선발대 매수 기회:</b>'
            for s in scouts:
                pf_lines += f"\n• {s['ticker']} ({s['pct']:+.1f}%) — 추가매수 검토!"
        # RSI/MACD 신호 (bottomup_data.json 재사용)
        sig = pf_summary.get('rsi_signals', {})
        if sig.get('oversold'):
            pf_lines += '\n📉 <b>RSI 과매도(매수기회):</b> ' + '  '.join(sig['oversold'])
        if sig.get('overbought'):
            pf_lines += '\n📈 <b>RSI 과매수(주의):</b> ' + '  '.join(sig['overbought'])
        if sig.get('macd_buy'):
            pf_lines += '\n🟢 <b>MACD 골든:</b> ' + '  '.join(sig['macd_buy'])
        if sig.get('macd_sell'):
            pf_lines += '\n🔴 <b>MACD 데드:</b> ' + '  '.join(sig['macd_sell'])

    # ── AI 분석용 데이터 블록 (복붙 → AI에 던지면 100점 분석) ─────────
    ai_block = '\n\n<b>📋 AI 분석 데이터 (복붙용):</b>'
    if pf_summary:
        all_results = pf_summary.get('results', [])
        total_val   = pf_summary.get('total_krw', 0)
        # portfolio.json에서 전체 holding 목록 읽기 (순서 보장 + type 정보)
        try:
            _pf_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'portfolio.json')
            with open(_pf_path, encoding='utf-8') as _f:
                _pf_data = json.load(_f)
            _holdings_raw = _pf_data.get('holdings', [])
        except Exception:
            _holdings_raw = []

        # results를 ticker → dict 맵으로 변환
        results_map = {r['ticker']: r for r in all_results}

        if _holdings_raw and total_val:
            parts = []
            for _h in _holdings_raw:
                _t  = _h['ticker']
                _tp = _h.get('type', 'core')
                _r  = results_map.get(_t)
                if _r and _r.get('val_krw', 0) > 0:
                    _pct = round(_r['val_krw'] / total_val * 100, 1)
                    parts.append(f"{_t}({_tp},{_pct}%)")
                else:
                    parts.append(f"{_t}({_tp},N/A%)")
            if parts:
                ai_block += '\n• 종목: ' + '  '.join(parts)
        r_str = ''
        if pf_summary.get('sharpe') is not None:
            r_str += f"Sharpe {pf_summary['sharpe']}"
        if pf_summary.get('mdd') is not None:
            r_str += f"  MDD {pf_summary['mdd']}%"
        if pf_summary.get('volatility') is not None:
            r_str += f"  변동성 {pf_summary['volatility']}%/yr"
        if r_str:
            ai_block += f'\n• 리스크: {r_str}'
    ai_block += f'\n• 시그널: Composite {result["composite"]:+.2f} / VIX {result["vix"]:.1f} / Spread {result["spread"]:+.2f}%'
    msg = f"""🌅 <b>WDK LAB Morning Digest</b> {date_str}

🚦 <b>Today's Signal:</b>
{sig_text}

<b>📊 탑다운 지표:</b>
• Composite: {curr_comp:+.2f}{delta_str}
• VIX: {vix_str}
• 10Y-2Y Spread: {spread_str}
• PCE YoY: {result['pce_yoy']:.1f}%
• 2Y 변화: {result['dgs2_change_bp']:.0f}bp{bu_lines}{pf_lines}{cal_lines}{action_hint}{ai_block}

⏰ {now_kst.strftime('%H:%M KST')}"""
    return msg


def format_emergency_alert(result):
    """🚨 3단계: Emergency Alert (VIX 급등)"""
    kst = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst)

    lvl = '🚨 공포' if result['vix'] >= 30 else '⚠️ 경계'
    msg = f"""{lvl} <b>VIX Alert!</b>

<b>VIX: {result['vix']:.1f}</b> {'(시장 공포 구간!)' if result['vix'] >= 30 else '(경계 구간)'}
📊 Composite: {result['composite']:+.2f} / Signal: {result['signal']}

💡 구체적으로 편입 가능한 종목 매수 기회 검토
⚠️ 하락이 더 올 수 있음!

⏰ {now_kst.strftime('%H:%M KST')}"""
    return msg


def format_signal_alert(result, previous_signal):
    """🚨 2단계: Signal Alert (신호 변경 시)"""
    kst = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst)

    msg = f"""🚨 <b>Signal 변경!</b>

신호: {previous_signal} → <b>{result['signal']}</b>
📊 Composite: {result['composite']:+.2f}
• VIX: {result['vix']:.1f}
• Spread: {result['spread']:+.2f}%

💡 포트폴리오 점검 권고

⏰ {now_kst.strftime('%H:%M KST')}"""
    return msg



def main(mode='check'):
    """메인 함수"""
    print(f"[WDK LAB] Running in {mode} mode...")

    state = load_state()
    kst = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst)
    current_hour = now_kst.strftime('%Y-%m-%d-%H')

    last_sent = state.get('last_sent', {})
    if mode in ['daily', 'report'] and last_sent.get(mode) == current_hour:
        print(f"[SKIP] Already sent {mode} at {current_hour}")
        return

    # 신호 계산
    result = calculate_signal()
    print(f"[Signal] {result['signal']} (score: {result['composite']:.2f})")
    previous_signal = state.get('previous_signal')

    # ===== 향상된 3단계 알람 =====

    if mode in ['daily', 'report']:
        # 🌅 1단계: Morning Digest
        bottomup_scores = calculate_bottomup_scores()
        pf_summary = fetch_portfolio_summary()
        msg = format_morning_digest(result, bottomup_scores, state, pf_summary)
        send_telegram(msg)
        if 'last_sent' not in state: state['last_sent'] = {}
        state['last_sent'][mode] = current_hour
        # 전일 바텀업 순위 저장
        state['prev_bottomup_ranks'] = {
            s['ticker']: i+1 for i, s in enumerate(bottomup_scores)
        }
        state['prev_composite'] = result['composite']
        state['prev_vix']       = result['vix']      # Δ 비교용
        state['prev_spread']    = result['spread']   # Δ 비교용

    elif mode == 'check':
        # 🚨 2단계: Signal Alert (변경시만)
        if previous_signal and previous_signal != result['signal']:
            print(f"[Signal] Changed! {previous_signal} → {result['signal']}")
            msg = format_signal_alert(result, previous_signal)
            send_telegram(msg)
        else:
            print(f"[Signal] No change ({result['signal']})")

        # 🚨 3단계: Emergency (VIX 25+ 신규)
        vix_alert_status = check_vix_alert(result['vix'], state)
        state['last_vix_alert'] = vix_alert_status

    elif mode == 'bottomup':
        # 바텀업 전용 런 (알람 없음, generate_bottomup_data.py가 따로 실행됨)
        print("[bottomup mode] 바텀업 스크립트 분리 실행 중 — 신호 재계산만")
        pass

    elif mode == 'midcheck':
        # 📡 미장 중반 VIX 긴급 체크 (KST 01:30, 03:30)
        vix_now  = result['vix']
        vix_prev = state.get('prev_vix', vix_now)
        vix_diff = round(vix_now - vix_prev, 1)
        kst      = timezone(timedelta(hours=9))
        now_kst  = datetime.now(kst)

        print(f"[midcheck] VIX {vix_prev:.1f} → {vix_now:.1f} (Δ{vix_diff:+.1f})")

        should_alert = False
        alert_reason = ''
        if vix_now >= 22:
            should_alert = True
            alert_reason = f'VIX {vix_now:.1f} ≥ 22 (경계구간 진입)'
        elif abs(vix_diff) >= 2.0:
            should_alert = True
            arrow = '▲' if vix_diff > 0 else '▼'
            alert_reason = f'VIX {arrow}{abs(vix_diff):.1f} 급변 ({vix_prev:.1f} → {vix_now:.1f})'

        if should_alert:
            lvl = '🚨' if vix_now >= 25 else '⚠️'
            msg = f"""{lvl} <b>미장 중반 VIX 경보</b>

<b>사유:</b> {alert_reason}
📊 Composite: {result['composite']:+.2f} / Signal: {result['signal']}
• Spread: {result['spread']:+.2f}%

💡 Morning Digest 이후 시장 환경 변화 — 재점검 권고
⏰ {now_kst.strftime('%H:%M KST')}"""
            send_telegram(msg)
            print(f"[midcheck] 🚨 알림 발송: {alert_reason}")
        else:
            print(f"[midcheck] 이상 없음 — 알림 없음")

    # 상태 저장
    state['previous_signal'] = result['signal']
    state['last_check'] = result['timestamp']
    save_state(state)


if __name__ == '__main__':
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else 'check'
    main(mode)
