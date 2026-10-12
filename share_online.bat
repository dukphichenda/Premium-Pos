@echo off
title inFlow Premium - Online Remote Access Tunnel
color 0B

echo ===================================================================
echo     inFlow Premium - Secure Online Access for Any Device
echo ===================================================================
echo.

set CLOUDFLARED_BIN=C:\Program Files (x86)\cloudflared\cloudflared.exe
if not exist "%CLOUDFLARED_BIN%" (
    where cloudflared >nul 2>nul
    if %errorlevel% equ 0 (
        set CLOUDFLARED_BIN=cloudflared
    ) else (
        echo [ERROR] cloudflared was not found.
        echo Please ensure cloudflared is installed or use Local Wi-Fi access.
        pause
        exit /b 1
    )
)

echo [1/2] Verifying that inFlow Premium is running on port 5050...
powershell -NoProfile -Command "try { (Invoke-WebRequest -Uri 'http://127.0.0.1:5050/health' -UseBasicParsing -TimeoutSec 3).StatusCode } catch { exit 1 }" >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARNING] inFlow Premium server is not running on port 5050.
    echo Please make sure you have run 'run.bat' first!
    echo.
)

echo [2/2] Generating secure temporary public HTTPS URL...
echo.
echo ===================================================================
echo   INSTRUCTIONS FOR OTHER DEVICES:
echo   1. Keep THIS window open while using the link.
echo   2. Look below for the URL ending with '.trycloudflare.com'
echo   3. Share that HTTPS link to your phone, tablet, or external PC!
echo ===================================================================
echo.

"%CLOUDFLARED_BIN%" tunnel --url http://127.0.0.1:5050
pause
