"""
바텀업 데이터 생성기 v3.0 — 단기 민감도 개선 + 히스토리 Gist 저장
- Min-Max Normalization (상대 비교)
- 모멘텀: 52주 수익률(40%) + 5일 수익률(30%) + RSI(20%) + MACD(10%)
- 펀더멘탈 중심 (55%)
- Gist에 히스토리 누적 저장 (최대 180일)
"""

import json
import time
import os
import requests
from datetime import datetime, timezone, timedelta

import yfinance as yf
try:
    import pandas_ta as ta
    HAS_PANDAS_TA = True
except ImportError:
    HAS_PANDAS_TA = False
    print("[WARNING] pandas_ta not installed — 단기 지표 비활성화. pip install pandas_ta")

# ===== 설정 =====
TICKERS = [
    'MSFT', 'AAPL', 'GOOGL', 'AMZN', 'META', 'TSLA',  # Big Tech
    'NVDA', 'TSM', 'ASML',                              # Semiconductors
    'LLY',                                              # Healthcare
    'JPM', 'V',                                         # Financials
    'XOM',                                              # Energy
    'WMT', 'COST',                                      # Consumer Staples
    'GE', 'CAT'                                         # Industrials
]

WEIGHTS = {
    'momentum': 0.25,
    'fundamental': 0.55,
    'valuation': 0.20
}

OUTPUT_FILE = 'bottomup_data.json'

# Gist 설정 (Actions Secrets에서 가져옴)
GIST_ID    = os.environ.get('GIST_ID', '')
GIST_TOKEN = os.environ.get('GIST_TOKEN', '')

# FRED API (탑다운 데이터용 — Secrets로 주입됨)
FRED_API_KEY = os.environ.get('FRED_API_KEY', '')


# ===== 유틸리티 =====

def safe_get(info, key, default=None):
    """안전하게 값 가져오기"""
    value = info.get(key)
    if value is None or (isinstance(value, float) and value != value):  # NaN check
        return default
    return value


def minmax_normalize(values, inverse=False):
    """
    Min-Max 정규화 → -1 ~ +1 범위
    inverse=True: 낮은 값이 좋음 (PE, PEG 등)
    """
    valid = [v for v in values if v is not None]
    if not valid or len(valid) < 2:
        return [0.0] * len(values)

    min_val = min(valid)
    max_val = max(valid)

    if max_val == min_val:
        return [0.0] * len(values)

    result = []
    for v in values:
        if v is None:
            result.append(0.0)
        else:
            normalized = (v - min_val) / (max_val - min_val)
            if inverse:
                normalized = 1 - normalized
            scaled = (normalized * 2) - 1  # 0~1 → -1~+1
            result.append(scaled)
    return result


# ===== 단기 지표 계산 (pandas_ta 사용) =====

def calc_short_term_indicators(ticker):
    """
    yfinance 3개월 일봉으로 단기 지표 산출
    반환: {'rsi': float, 'macd_cross': float, 'perf_5d': float}
    실패 시: None 반환
    """
    if not HAS_PANDAS_TA:
        return None

    try:
        hist = yf.Ticker(ticker).history(period='3mo')
        if len(hist) < 20:
            return None

        close = hist['Close']

        # RSI (14일)
        rsi_series = ta.rsi(close, length=14)
        latest_rsi = float(rsi_series.dropna().iloc[-1]) if not rsi_series.dropna().empty else 50.0

        # MACD (12, 26, 9) → 골든크로스: MACD > Signal이면 +1, 아니면 -1
        macd_df = ta.macd(close, fast=12, slow=26, signal=9)
        if macd_df is not None and len(macd_df.dropna()) > 0:
            last = macd_df.dropna().iloc[-1]
            macd_val   = last['MACD_12_26_9']
            signal_val = last['MACDs_12_26_9']
            macd_cross = 1.0 if macd_val > signal_val else -1.0
        else:
            macd_cross = 0.0

        # 5일 수익률
        if len(close) >= 6:
            perf_5d = float((close.iloc[-1] / close.iloc[-5]) - 1)
        else:
            perf_5d = 0.0

        return {'rsi': latest_rsi, 'macd_cross': macd_cross, 'perf_5d': perf_5d}

    except Exception as e:
        print(f"  [SHORT_TERM_ERROR] {ticker}: {e}")
        return None


# ===== 장기 데이터 수집 =====

def fetch_stock_data(ticker):
    """yfinance .info로 장기 지표 수집"""
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
    """모든 종목 장기 + 단기 데이터 수집"""
    all_data = []

    for i, ticker in enumerate(TICKERS, 1):
        print(f"[{i}/{len(TICKERS)}] {ticker}...", end=" ")

        info = fetch_stock_data(ticker)
        if not info:
            print("❌ Failed (info)")
            all_data.append({'ticker': ticker, 'info': None, 'short_term': None, 'error': True})
            time.sleep(0.5)
            continue

        # 단기 지표 별도 수집 (history API 사용)
        short = calc_short_term_indicators(ticker)
        rsi_str = f"RSI:{short['rsi']:.0f}" if short else "RSI:N/A"
        print(f"✅ ({rsi_str})")

        all_data.append({'ticker': ticker, 'info': info, 'short_term': short, 'error': False})
        time.sleep(0.3)

    return all_data


# ===== 지표 추출 =====

def calculate_raw_metrics(all_data):
    """원시 지표 추출 (장기 + 단기 통합)"""
    metrics = []

    for item in all_data:
        if item['error']:
            metrics.append(None)
            continue

        info  = item['info']
        short = item['short_term']  # None 가능

        # 장기 모멘텀
        perf_52w      = safe_get(info, 'fiftyTwoWeekChange', 0) or 0
        current_price = safe_get(info, 'regularMarketPrice', 0) or 0
        sma200        = safe_get(info, 'twoHundredDayAverage', current_price) or current_price
        sma50         = safe_get(info, 'fiftyDayAverage', current_price) or current_price

        # 단기 모멘텀 (short_term이 없으면 중립)
        rsi       = short['rsi']       if short else 50.0
        macd_cross = short['macd_cross'] if short else 0.0
        perf_5d   = short['perf_5d']   if short else 0.0

        # 펀더멘탈
        eps_growth     = safe_get(info, 'earningsQuarterlyGrowth', 0) or 0
        revenue_growth = safe_get(info, 'revenueGrowth', 0) or 0
        profit_margin  = safe_get(info, 'profitMargins', 0) or 0
        roe            = safe_get(info, 'returnOnEquity', 0) or 0
        fcf            = safe_get(info, 'freeCashflow', 0) or 0
        revenue        = safe_get(info, 'totalRevenue', 1) or 1
        fcf_margin     = fcf / revenue if revenue > 0 else 0

        # 밸류에이션
        pe            = safe_get(info, 'trailingPE', 50) or 50
        forward_pe    = safe_get(info, 'forwardPE', 50) or 50
        peg           = safe_get(info, 'pegRatio', 2) or 2
        price_to_book = safe_get(info, 'priceToBook', 5) or 5

        # 리스크
        beta = safe_get(info, 'beta', 1.0) or 1.0

        metrics.append({
            'ticker': item['ticker'],
            # 장기 모멘텀
            'perf_52w':    perf_52w,
            'above_sma200': 1 if current_price > sma200 else -1,
            'above_sma50':  1 if current_price > sma50  else -1,
            # 단기 모멘텀 (NEW)
            'perf_5d':    perf_5d,
            'rsi':        rsi,
            'macd_cross': macd_cross,
            # 펀더멘탈
            'eps_growth':     eps_growth,
            'revenue_growth': revenue_growth,
            'profit_margin':  profit_margin,
            'roe':            roe,
            'fcf_margin':     fcf_margin,
            # 밸류에이션
            'pe':            pe,
            'forward_pe':    forward_pe,
            'peg':           peg,
            'price_to_book': price_to_book,
            # 리스크
            'beta':  beta,
            # 원시
            'price': current_price,
            'sma200': sma200,
            'sma50':  sma50,
        })

    return metrics


# ===== 정규화 및 점수 계산 =====

def normalize_and_score(metrics):
    valid_metrics = [m for m in metrics if m is not None]

    if len(valid_metrics) < 2:
        return []

    # --- 장기 모멘텀 정규화 ---
    perf_52w_norm  = minmax_normalize([m['perf_52w']  for m in valid_metrics])

    # --- 단기 모멘텀 정규화 (NEW) ---
    perf_5d_norm   = minmax_normalize([m['perf_5d']   for m in valid_metrics])

    # RSI 정규화: 30~70이 정상 구간. 70 초과(과매수) → 패널티, 30 미만(과매도) → 보너스
    def rsi_to_score(rsi):
        if rsi >= 70:   return -0.5              # 과매수 패널티
        elif rsi <= 30: return  0.5              # 과매도 보너스 (대칭)
        else:           return (rsi - 50) / 20 * 0.5  # 30~70 선형: -0.5 ~ +0.5

    rsi_scores = [rsi_to_score(m['rsi']) for m in valid_metrics]

    # MACD: 이미 -1 or +1 (골든/데드크로스)
    macd_scores = [m['macd_cross'] for m in valid_metrics]

    # --- 펀더멘탈 정규화 ---
    eps_norm    = minmax_normalize([m['eps_growth']     for m in valid_metrics])
    rev_norm    = minmax_normalize([m['revenue_growth'] for m in valid_metrics])
    margin_norm = minmax_normalize([m['profit_margin']  for m in valid_metrics])
    roe_norm    = minmax_normalize([m['roe']            for m in valid_metrics])
    fcf_norm    = minmax_normalize([m['fcf_margin']     for m in valid_metrics])

    # --- 밸류에이션 정규화 (낮을수록 좋음) ---
    pe_norm  = minmax_normalize([m['pe']         for m in valid_metrics], inverse=True)
    fpe_norm = minmax_normalize([m['forward_pe'] for m in valid_metrics], inverse=True)
    peg_norm = minmax_normalize([m['peg']        for m in valid_metrics], inverse=True)

    # --- 리스크: Beta 1 근처가 좋음 ---
    def beta_score(beta):
        if beta < 0.5:   return -0.3
        elif beta <= 1.5: return  0.5
        else:             return -0.5

    beta_scores = [beta_score(m['beta']) for m in valid_metrics]

    results = []
    for i, m in enumerate(valid_metrics):

        # 모멘텀 점수 (장기 40% + 단기 60%)
        momentum = (
            perf_52w_norm[i] * 0.40    # 52주 수익률 (장기 추세)
            + perf_5d_norm[i]  * 0.30  # 5일 수익률  (주간 모멘텀)
            + rsi_scores[i]    * 0.20  # RSI         (과매수/과매도)
            + macd_scores[i]   * 0.10  # MACD 크로스 (단기 방향성)
        )
        momentum = max(-1.0, min(1.0, momentum))

        # 펀더멘탈 점수
        fundamental = (
            eps_norm[i]    * 0.25
            + rev_norm[i]    * 0.20
            + margin_norm[i] * 0.20
            + roe_norm[i]    * 0.20
            + fcf_norm[i]    * 0.15
        )
        fundamental = max(-1.0, min(1.0, fundamental))

        # 밸류에이션 점수
        valuation = (
            fpe_norm[i] * 0.40
            + peg_norm[i] * 0.35
            + pe_norm[i]  * 0.25
        )
        valuation = max(-1.0, min(1.0, valuation))

        # 리스크
        risk = beta_scores[i]

        # 최종 점수
        final = (
            WEIGHTS['momentum']    * momentum
            + WEIGHTS['fundamental'] * fundamental
            + WEIGHTS['valuation']   * valuation
        )
        final = max(-1.0, min(1.0, final))

        results.append({
            'ticker': m['ticker'],
            'error': False,
            'scores': {
                'momentum':    round(momentum, 2),
                'fundamental': round(fundamental, 2),
                'valuation':   round(valuation, 2),
                'risk':        round(risk, 2),
                'final':       round(final, 2),
            },
            'raw': {
                'price':          m['price'],
                'sma200':         m['sma200'],
                '52w_change':     round(m['perf_52w'], 4),
                '5d_change':      round(m['perf_5d'], 4),    # NEW
                'rsi':            round(m['rsi'], 1),         # NEW
                'macd_cross':     m['macd_cross'],            # NEW
                'eps_growth':     m['eps_growth'],
                'revenue_growth': m['revenue_growth'],
                'profit_margin':  m['profit_margin'],
                'roe':            m['roe'],
                'fcf_margin':     m['fcf_margin'],
                'pe':             m['pe'],
                'forward_pe':     m['forward_pe'],
                'peg':            m['peg'],
                'beta':           m['beta'],
            }
        })

    return results


# ===== 탑다운 스냅샷 (Gist td 필드용) =====

def fetch_topdown_snapshot():
    """
    Gist td 필드용 — VIX, Composite, Spread, PCE만 미니 조회
    실패해도 None 반환 (Gist 저장 자체를 막지 않음)
    """
    if not FRED_API_KEY:
        print("[TD] FRED_API_KEY 없음 — td 스냅샷 건너뜀")
        return None

    def _fred(series_id, limit=30):
        try:
            r = requests.get(
                'https://api.stlouisfed.org/fred/series/observations',
                params={
                    'series_id': series_id,
                    'api_key': FRED_API_KEY,
                    'file_type': 'json',
                    'sort_order': 'desc',
                    'limit': limit
                },
                timeout=15
            )
            obs = r.json().get('observations', [])
            vals = [float(o['value']) for o in obs if o['value'] not in ['.', '']]
            return list(reversed(vals))  # oldest first
        except:
            return []

    try:
        dgs2  = _fred('DGS2', 25)
        dgs10 = _fred('DGS10', 5)
        vix   = _fred('VIXCLS', 5)
        pce   = _fred('PCEPILFE', 14)
        baa   = _fred('BAMLC0A0CM', 5)

        vix_val = vix[-1] if vix else 20.0
        spread  = (dgs10[-1] - dgs2[-1]) if dgs10 and dgs2 else 0.0
        pce_yoy = ((pce[-1] / pce[-13]) - 1) * 100 if len(pce) >= 13 else 2.5
        dgs2_change_bp = (dgs2[-1] - dgs2[-21]) * 100 if len(dgs2) >= 21 else 0.0

        # King 신호 (Fed, 2Y 20일 변화량)
        if dgs2_change_bp <= -10:  fed = 1
        elif dgs2_change_bp >= 10: fed = -1
        else:                      fed = 0

        # Queen 신호 (PCE YoY + 3m)
        pce_3m = ((pce[-1] / pce[-4]) ** 4 - 1) * 100 if len(pce) >= 4 else 2.5
        if pce_yoy <= 2.6 and pce_3m <= 2.2:   infl = 1
        elif pce_yoy > 2.6 and pce_3m > 2.2:   infl = -1
        else:                                    infl = 0

        # Context 신호 (VIX + Spread + BAA)
        ctx_scores = []
        if vix_val <= 18:    ctx_scores.append(1)
        elif vix_val >= 30:  ctx_scores.append(-1)
        else:                ctx_scores.append(0)
        if spread >= 0.25:   ctx_scores.append(1)
        elif spread <= -0.25: ctx_scores.append(-1)
        else:                ctx_scores.append(0)
        baa_val = baa[-1] if baa else 2.0
        if baa_val <= 2.0:   ctx_scores.append(1)
        elif baa_val >= 3.0: ctx_scores.append(-1)
        else:                ctx_scores.append(0)
        ctx_mean = sum(ctx_scores) / len(ctx_scores)
        ctx = 1 if ctx_mean > 0.33 else (-1 if ctx_mean < -0.33 else 0)

        # Composite (wdklab_monitor.py와 동일 가중치)
        composite = round(0.50 * fed + 0.30 * infl + 0.20 * ctx, 3)

        print(f"[TD] ✅ VIX:{vix_val:.1f} Spread:{spread:.2f} PCE:{pce_yoy:.1f}% Composite:{composite:.3f}")
        return {
            'comp': composite,
            'vix':  round(vix_val, 1),
            'sp':   round(spread, 3),
            'pce':  round(pce_yoy, 2),
            'fed':  fed,
            'infl': infl,
            'ctx':  ctx
        }

    except Exception as e:
        print(f"[TD] ❌ 실패: {e}")
        return None


# ===== Gist 히스토리 업데이트 =====

def push_to_gist(snapshot):
    """공개 Gist에 오늘 스냅샷 추가 (최대 180일 보관)"""
    if not GIST_ID or not GIST_TOKEN:
        print("[GIST] GIST_ID 또는 GIST_TOKEN 없음 — 히스토리 저장 건너뜀")
        return

    try:
        headers = {'Authorization': f'token {GIST_TOKEN}'}

        # 기존 Gist 읽기
        r = requests.get(f'https://api.github.com/gists/{GIST_ID}', headers=headers, timeout=15)
        r.raise_for_status()

        raw_content = r.json()['files'].get('history_data.json', {}).get('content', '{"snapshots":[]}')
        history = json.loads(raw_content)

        # 오늘 날짜 중복 제거 후 append
        today = snapshot['d']
        history['snapshots'] = [s for s in history['snapshots'] if s['d'] != today]
        history['snapshots'].append(snapshot)
        history['snapshots'] = history['snapshots'][-180:]  # 최대 180일

        # Gist 업데이트
        payload = {'files': {'history_data.json': {'content': json.dumps(history, ensure_ascii=False)}}}
        r2 = requests.patch(f'https://api.github.com/gists/{GIST_ID}', headers=headers,
                            json=payload, timeout=15)
        r2.raise_for_status()

        print(f"[GIST] ✅ 히스토리 업데이트 완료 (총 {len(history['snapshots'])}일)")

    except Exception as e:
        print(f"[GIST] ❌ 업데이트 실패: {e}")


# ===== 메인 =====

def main():
    kst = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst)
    today_str = now_kst.strftime('%Y-%m-%d')

    print("=" * 55)
    print("WDK LAB 바텀업 데이터 생성기 v3.0")
    print("📊 단기 민감도 개선 (RSI + MACD + 5일 모멘텀)")
    print("=" * 55)

    # 1. 데이터 수집
    print("\n📡 데이터 수집 중...")
    all_data = collect_all_data()

    # 2. 지표 추출
    print("\n📈 지표 분석 중...")
    metrics = calculate_raw_metrics(all_data)

    # 3. 정규화 및 점수 계산
    print("🔢 점수 계산 중...")
    results = normalize_and_score(metrics)

    # 4. 정렬 및 순위
    results.sort(key=lambda x: x['scores']['final'], reverse=True)
    for i, r in enumerate(results, 1):
        r['rank'] = i

    # 5. 에러 종목 추가
    error_tickers = [d['ticker'] for d in all_data if d['error']]
    for ticker in error_tickers:
        results.append({'ticker': ticker, 'error': True, 'scores': None, 'rank': len(results) + 1})

    # 6. bottomup_data.json 저장 (기존 방식)
    output = {
        'version': '3.0',
        'updated': now_kst.isoformat(),
        'updated_display': now_kst.strftime('%Y. %m. %d. %p %I:%M:%S'),
        'count': len([r for r in results if not r.get('error', False)]),
        'total': len(TICKERS),
        'weights': WEIGHTS,
        'data': results
    }
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), OUTPUT_FILE)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n✅ {OUTPUT_FILE} 저장 완료")

    # 7. 탑다운 스냅샷 (Gist td 필드)
    print("\n🚦 탑다운 데이터 조회 중...")
    td_snapshot = fetch_topdown_snapshot()

    # 8. Gist 히스토리 업데이트 (Phase 2)
    valid_bu = [r for r in results if not r.get('error', False)]
    snapshot = {
        'd': today_str,
        'ts': now_kst.isoformat(),
        'td': td_snapshot,         # None이면 null로 저장 (허용)
        'bu': [
            [r['ticker'],
             r['scores']['final'],
             r['scores']['momentum'],
             r['scores']['fundamental'],
             r['scores']['valuation']]
            for r in valid_bu
        ]
    }
    push_to_gist(snapshot)

    # 8. 결과 출력
    print("\n" + "=" * 55)
    print(f"📊 성공: {output['count']}/{output['total']}")
    print("=" * 55)
    print("\n🏆 TOP 5:")
    for r in results[:5]:
        if r.get('error'):
            continue
        s = r['scores']
        raw = r.get('raw', {})
        rsi_disp = f"RSI:{raw.get('rsi', '?')}" if 'rsi' in raw else ""
        print(f"  {r['rank']}. {r['ticker']}: {s['final']:+.2f}  {rsi_disp}")
        print(f"      M:{s['momentum']:+.2f} F:{s['fundamental']:+.2f} V:{s['valuation']:+.2f}")

    print("\n⚠️  BOTTOM 3:")
    valid_results = [r for r in results if not r.get('error', False)]
    for r in valid_results[-3:]:
        s = r['scores']
        print(f"  {r['rank']}. {r['ticker']}: {s['final']:+.2f}")

    return output


if __name__ == '__main__':
    main()
