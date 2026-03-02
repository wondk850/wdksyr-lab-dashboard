@echo off
title WDK LAB - Morning Digest 강제 발송 (state 무시)
color 0D
echo ============================================
echo  WDK LAB Morning Digest 강제 발송 중...
echo  (오늘 이미 보냈어도 다시 보냄)
echo ============================================
cd /d %~dp0

echo [*] 의존성 확인 중...
pip install -r requirements.txt -q 2>nul || echo [WARN] 일부 패키지 설치 실패 - 계속 진행

echo [*] state 초기화 중...
if exist wdk_state.json (
    python -c "import json; s=json.load(open('wdk_state.json',encoding='utf-8')); s.pop('last_sent',None); json.dump(s, open('wdk_state.json','w',encoding='utf-8'), ensure_ascii=False)"
    echo [OK] state 초기화 완료
)

python wdklab_monitor.py daily
if %ERRORLEVEL% NEQ 0 (
    color 0C
    echo.
    echo [ERROR] 실패. 에러 확인:
    echo https://github.com/wondk850/wdksyr-lab-dashboard/actions
) else (
    echo.
    echo [OK] 강제 발송 완료!
)
echo.
pause
