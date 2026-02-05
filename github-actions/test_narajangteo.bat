@echo off
chcp 65001 > nul
echo ========================================
echo   나라장터 입찰공고 모니터 테스트
echo ========================================
echo.

:: API 키 설정
set NARAJANGTEO_API_KEY=9bf968fe1df144ce606f4125fcb05441cbc25dd48d4de931803bad2956cd4d91

:: 스크립트 경로
cd /d "%~dp0"

echo [테스트 모드] 텔레그램 발송 없이 결과만 확인
echo.
python narajangteo_monitor.py test

echo.
echo ========================================
echo   완료! 실제 발송은 'bid' 모드로 실행
echo   python narajangteo_monitor.py bid
echo ========================================
pause
