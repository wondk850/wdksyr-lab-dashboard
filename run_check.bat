@echo off
title WDK LAB - Signal Check
color 0B
echo ============================================
echo  WDK LAB Signal 체크 중...
echo ============================================
cd /d %~dp0
python wdklab_monitor.py check
if %ERRORLEVEL% NEQ 0 (
    color 0C
    echo.
    echo [ERROR] 실패. 에러 확인:
    echo https://github.com/wondk850/wdksyr-lab-dashboard/actions
) else (
    echo.
    echo [OK] 완료! (신호 변경 시에만 텔레그램 옴)
)
echo.
pause
