@echo off
title WDK LAB - Morning Digest 발송
color 0A
echo ============================================
echo  WDK LAB Morning Digest 텔레그램 발송 중...
echo ============================================
cd /d %~dp0
python wdklab_monitor.py daily
if %ERRORLEVEL% NEQ 0 (
    color 0C
    echo.
    echo [ERROR] 실패했습니다. GitHub Actions 탭에서 확인하세요.
    echo https://github.com/wondk850/wdksyr-lab-dashboard/actions
) else (
    echo.
    echo [OK] 텔레그램 발송 완료!
)
echo.
pause
