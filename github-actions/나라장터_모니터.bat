@echo off
chcp 65001 > nul
echo ========================================
echo   나라장터 입찰공고 모니터
echo ========================================
echo.

:: API 키 설정
set NARAJANGTEO_API_KEY=9bf968fe1df144ce606f4125fcb05441cbc25dd48d4de931803bad2956cd4d91

:: 텔레그램 설정
set TELEGRAM_BOT_TOKEN=8209005017:AAH1IOr7h49dI3lX2TSBNOrvMsQEIcHCouM
set TELEGRAM_CHAT_ID=1489387702

:: 스크립트 경로 (절대경로!)
set SCRIPT_DIR=c:\Users\wondk\.gemini\antigravity\scratch\wdksyr-lab-dashboard\github-actions
cd /d "%SCRIPT_DIR%"

echo [1] 테스트 모드 (텔레그램 발송 안 함)
echo [2] 실제 발송 모드 (텔레그램 발송!)
echo.
set /p choice="선택 (1 or 2): "

if "%choice%"=="1" (
    echo.
    echo [테스트 모드] 실행 중...
    python "%SCRIPT_DIR%\narajangteo_monitor.py" test
) else if "%choice%"=="2" (
    echo.
    echo [실제 발송 모드] 실행 중...
    python "%SCRIPT_DIR%\narajangteo_monitor.py" bid
) else (
    echo 잘못된 선택입니다.
)

echo.
echo ========================================
echo   완료!
echo ========================================
pause
