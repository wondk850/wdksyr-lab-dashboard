@echo off
title WDK LAB - VIX Midcheck
color 0E
echo ============================================
echo  WDK LAB 장중 VIX 긴급체크 중...
echo ============================================
cd /d %~dp0
python wdklab_monitor.py midcheck
if %ERRORLEVEL% NEQ 0 (
    color 0C
    echo.
    echo [ERROR] 실패. 에러 확인:
    echo https://github.com/wondk850/wdksyr-lab-dashboard/actions
) else (
    echo.
    echo [OK] 완료! (VIX 22+ 또는 2pt 급변 시에만 텔레그램 옴)
)
echo.
pause
