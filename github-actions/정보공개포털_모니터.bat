@echo off
chcp 65001 > nul
echo ========================================
echo   정보공개포털 (open.go.kr) 모니터
echo ========================================
echo.

:: 텔레그램 설정
set TELEGRAM_BOT_TOKEN=8209005017:AAH1IOr7h49dI3lX2TSBNOrvMsQEIcHCouM
set TELEGRAM_CHAT_ID=1489387702

:: 스크립트 경로 (절대경로)
set SCRIPT_DIR=c:\Users\wondk\.gemini\antigravity\scratch\wdksyr-lab-dashboard\github-actions
cd /d "%SCRIPT_DIR%"

echo [주의] 정보공개포털은 속도가 매우 느립니다 (1~2분 소요).
echo        Playwright가 설치되어 있어야 합니다 (playwright_설치.bat 실행).
echo.
echo [1] 테스트 모드 (텔레그램 발송 안 함)
echo [2] 실제 발송 모드 (텔레그램 발송!)
echo.
set /p choice="선택 (1 or 2): "

if "%choice%"=="1" (
    echo.
    echo [테스트 모드] 실행 중... (시간이 좀 걸립니다)
    python "%SCRIPT_DIR%\opengo_monitor.py" test
) else if "%choice%"=="2" (
    echo.
    echo [실제 발송 모드] 실행 중... (시간이 좀 걸립니다)
    python "%SCRIPT_DIR%\opengo_monitor.py" opengo
) else (
    echo 잘못된 선택입니다.
)

echo.
echo ========================================
echo   완료!
echo ========================================
pause
