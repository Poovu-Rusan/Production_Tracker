@echo off
title Midwest Production Log
echo ====================================================
echo   Midwest Production Log - Local Web Server
echo ====================================================
echo.
echo Detecting your WiFi IP...
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /i "IPv4" ^| findstr /v "127.0.0.1"') do (
    set IP=%%a
    goto :found
)
:found
set IP=%IP: =%
echo.
echo  Open in your browser:
echo.
echo  Local:    http://localhost:5011
echo  Network:  http://%IP%:5011
echo.
echo  Share the Network URL with others on your WiFi.
echo  Press Ctrl+C to stop.
echo ====================================================
echo.
python app.py
pause
