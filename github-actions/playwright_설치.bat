@echo off
chcp 65001 > nul
echo ========================================
echo   Playwright 설치
echo ========================================
echo.

echo [1/2] pip install playwright...
pip install playwright

echo.
echo [2/2] Chromium 브라우저 설치 중...
playwright install chromium

echo.
echo ========================================
echo   설치 완료!
echo ========================================
pause
