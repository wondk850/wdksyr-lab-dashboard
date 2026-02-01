# WDK LAB Signal Monitor

GitHub Actions를 사용한 자동 투자 신호 모니터링 시스템

## 🚀 설정 방법

### 1. GitHub Repository 생성

1. GitHub에서 새 Repository 생성 (예: `wdk-lab-monitor`)
2. Private으로 설정 (API 키 보안)

### 2. 파일 업로드

이 폴더의 파일들을 Repository에 업로드:
```
wdk-lab-monitor/
├── .github/
│   └── workflows/
│       └── signal-monitor.yml
├── wdklab_monitor.py
└── README.md
```

### 3. Secrets 설정 ⚠️ 중요!

Repository Settings → Secrets and variables → Actions → New repository secret

| Secret Name | Value |
|-------------|-------|
| `FRED_API_KEY` | `bd2f35437a05410f3f72fa653ab8935c` |
| `TELEGRAM_BOT_TOKEN` | `8209005017:AAH1IOr7h49dI3lX2TSBNOrvMsQEIcHCouM` |
| `TELEGRAM_CHAT_ID` | `1489387702` |

### 4. 워크플로우 활성화

1. Actions 탭으로 이동
2. "I understand my workflows, go ahead and enable them" 클릭

## 📅 실행 스케줄

| 시간 (KST) | 모드 | 설명 |
|------------|------|------|
| 09:00 | daily | 아침 일일 리포트 |
| 23:00 | check | 장 시작 전 체크 |
| 23:30~06:00 | check | 30분마다 신호 체크 |
| 06:00 | report | 장 마감 리포트 |

## 🔔 알림 종류

1. **Signal Change** - 신호 변경 시 (GREEN↔YELLOW↔RED)
2. **Daily Report** - 매일 아침 요약
3. **End of Day Report** - 장 마감 후 요약

## 🧪 수동 테스트

Actions 탭 → "WDK LAB Signal Monitor" → "Run workflow" → 모드 선택 → Run

## 📊 분 사용량 예상

- 1회 실행: ~2분
- 하루: ~14회 = 28분
- 월간 (22거래일): ~616분
- 남은 여유: ~1384분/월

## ⚠️ 주의사항

1. Secrets는 절대 코드에 직접 넣지 마세요!
2. Repository를 Private으로 유지하세요
3. API 키가 노출되면 즉시 재발급하세요
