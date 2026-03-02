# WDK Syr Lab Dashboard 📊

> 개인 투자 의사결정을 위한 **자동화 리서치 시스템**
> 감정 배제 · 데이터 기반 · 완전 자동화

---

## 🎯 목적

미국 주식 투자에서 **거시경제(탑다운) + 기술적 지표(바텀업)** 를 매일 자동으로 수집·분석하고, Telegram으로 알림을 받는 개인용 투자 리서치 플랫폼.

---

## 🏗 시스템 구조

```
FRED API ─────────────────┐
Yahoo Finance (yfinance) ──┤──▶ generate_bottomup_data.py ──▶ bottomup_data.json
Finnhub (경제캘린더) ────────┘
                                        │
                                        ▼
                              wdklab_monitor.py
                                        │
                          ┌─────────────┼───────────────┐
                          ▼             ▼               ▼
                   🌅 Morning      📡 Signal       🚨 Emergency
                     Digest          Alert            Alert
                   (KST 09:00)   (VIX 급등시)    (신호 변경시)
                          │
                          ▼
                    Telegram Bot → 알림 수신
                          │
                    GitHub Gist → 히스토리 저장
                          │
                    GitHub Pages → 대시보드 서빙
```

---

## 📁 주요 파일

| 파일 | 역할 |
|------|------|
| `generate_bottomup_data.py` | 17개 종목 RSI/MACD/재무지표 수집 + Gist 저장 |
| `wdklab_monitor.py` | 탑다운 신호 계산 + 포트폴리오 요약 + Telegram 발송 |
| `wdklab_monitor.py` → `fetch_portfolio_summary()` | yfinance 1y 데이터로 Sharpe/MDD/변동성 계산 |
| `portfolio.json` | 보유 종목 목록 (수동 관리) |
| `bottomup_data.json` | 바텀업 점수 (Actions가 자동 갱신) |
| `index.html` | 대시보드 메인 (GitHub Pages) |
| `chart.html` | 탑다운/바텀업 통합 차트 |
| `.github/workflows/signal-monitor.yml` | 전체 자동화 워크플로우 |

---

## 🔄 GitHub Actions 스케줄

| KST 시간 | 모드 | 내용 |
|---------|------|------|
| 10:00 | `news` | 뉴스 수집 |
| 11:00 | `bid` | 나라장터 입찰 |
| 12:00 | `check` | 신호 체크 (변경시 Telegram) |
| 22:30 | `daily` | 🌅 Morning Digest 발송 |
| 23:30 | `bottomup` | 바텀업 데이터 갱신 |
| 01:30 | `report` | 종합 리포트 |

---

## 📊 Telegram 알림 3단계

### 🌅 Morning Digest (매일 22:30 KST)
- Composite Score (전일 Δ 포함)
- VIX / Spread / PCE / 2Y 변화 (전일 Δ 포함)
- 바텀업 TOP5 종목 + 순위 변동
- 포트폴리오: 평가액, 당일 손익, Sharpe / MDD / 변동성
- RSI 과매수/과매도 · MACD 골든/데드크로스
- 선발대 매수 기회 (scout 종목 -3% 이상 하락 시)
- 경제 캘린더 (FOMC, CPI, PCE 등)

### 📡 Signal Alert
- GREEN / YELLOW / RED 신호 변경 시

### 🚨 Emergency Alert
- VIX ≥ 25 급등 시

---

## 🧠 투자 전략 철학

1. **탑다운 우선** — 거시경제 환경이 GREEN일 때만 적극 매수
2. **바텀업 필터** — 재무 + 모멘텀 + 밸류에이션 종합 점수 상위 종목 집중
3. **선발대 전략** — 소액 포지션으로 관심 종목 선점, 급락 시 추가매수
4. **리스크 관리** — Sharpe / MDD / 변동성 일별 모니터링

---

## ⚙️ 로컬 실행

```bash
pip install -r requirements.txt

# 바텀업 데이터 생성
python generate_bottomup_data.py

# 신호 확인 (Telegram 미발송)
python wdklab_monitor.py check
```

### 필요한 환경변수 (GitHub Secrets)

| 변수 | 용도 |
|------|------|
| `TELEGRAM_BOT_TOKEN` | Telegram 봇 토큰 |
| `TELEGRAM_CHAT_ID` | 수신 채팅 ID |
| `GIST_ID` | 히스토리 저장용 Gist ID |
| `GIST_TOKEN` | Gist 쓰기 권한 PAT |
| `FRED_API_KEY` | FRED 경제지표 API |
| `FINNHUB_TOKEN` | 경제 캘린더 API |

---

## 📈 대시보드 (GitHub Pages)

| 페이지 | URL |
|--------|-----|
| 메인 | `/index.html` |
| 통합 차트 | `/chart.html` |
| 탑다운 | `/dashboard_topdown.html` |
| 바텀업 | `/dashboard_bottomup.html` |

---

*Built by WDK · Powered by FRED, Yahoo Finance, Finnhub, Telegram*