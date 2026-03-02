@echo off
title WDK LAB - Morning Digest 강제 발송 (state 무시)
color 0D
echo ============================================
echo  WDK LAB Morning Digest 강제 발송 중...
echo  (오늘 이미 보냈어도 다시 보냄)
echo ============================================
cd /d %~dp0

echo [*] 의존성 확인 중... (Python 3.12)
py -3.12 -m pip install -r requirements.txt -q 2>nul || echo [WARN] 일부 패키지 설치 실패 - 계속 진행

echo [*] state 초기화 중...
if exist signal_state.json (
    del signal_state.json
    echo [OK] signal_state.json 삭제 완료
) else (
    echo [OK] state 파일 없음 - 바로 진행
)

py -3.12 wdklab_monitor.py daily
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
