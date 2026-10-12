@echo off
title inFlow Premium ERP (PostgreSQL 16)
color 0A
echo ===================================================================
echo     inFlow Premium - Enterprise Inventory & Wholesale ERP
echo              Running on Modern PostgreSQL 16
echo ===================================================================

set RUNTIME_BASE=E:\odoo-ai-19.0\odoo-ai-19.0\runtime
set PG_BIN=%RUNTIME_BASE%\pgsql\bin
set PG_DATA=%RUNTIME_BASE%\pgsql\data
set PYTHON_EXE=%RUNTIME_BASE%\python3\python.exe

if not exist "%PYTHON_EXE%" (
    echo [ERROR] Python runtime not found at %PYTHON_EXE%
    echo Falling back to system python...
    set PYTHON_EXE=python
)

echo [1/3] Checking PostgreSQL Server status...
if exist "%PG_BIN%\pg_ctl.exe" (
    %PG_BIN%\pg_ctl.exe -D "%PG_DATA%" status >nul 2>&1
    if %errorlevel% neq 0 (
        echo [1/3] Starting PostgreSQL Server on port 5432...
        %PG_BIN%\pg_ctl.exe -D "%PG_DATA%" -l "%RUNTIME_BASE%\pgsql\logfile" start
        timeout /t 2 /nobreak >nul
    ) else (
        echo [1/3] PostgreSQL Server is active and ready.
    )
)

echo [2/3] Checking database connection and schema...
%PYTHON_EXE% database.py

:: Detect LAN IP address for other devices
for /f "tokens=*" %%i in ('%PYTHON_EXE% -c "import socket; print(socket.gethostbyname(socket.gethostname()))"') do set LAN_IP=%%i

echo [3/3] Launching inFlow Premium Web Application on http://localhost:5050 ...
start "" "http://localhost:5050"

echo.
echo ===================================================================
echo   inFlow Premium Server is ACTIVE and READY!
echo ===================================================================
echo   [THIS COMPUTER] : http://localhost:5050
echo   [OTHER DEVICES] : http://%LAN_IP%:5050
echo.
echo   * Keep this window OPEN while you or other devices are working.
echo   * Connect other devices (Phone, Tablet, PC) to the same Wi-Fi.
echo   * Open browser on other device and go to: http://%LAN_IP%:5050
echo   * If connecting from outside Wi-Fi (Cellular/Internet),
echo     double-click 'share_online.bat' for a secure public link.
echo ===================================================================
echo.
%PYTHON_EXE% app.py
pause
