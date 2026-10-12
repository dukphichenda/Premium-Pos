@echo off
setlocal enabledelayedexpansion
title inFlow Premium - Upload Local Database to Neon.tech
color 0A

echo =====================================================================
echo      inFlow Premium - Upload Local Database to Neon.tech Cloud
echo =====================================================================
echo.
echo This tool uploads your complete local PostgreSQL 16 database
echo (406+ products, 2,602+ customers, orders, inventory, settings)
echo directly into your Neon.tech cloud database.
echo.

set PSQL_BIN=E:\odoo-ai-19.0\odoo-ai-19.0\runtime\pgsql\bin\psql.exe
if not exist "%PSQL_BIN%" (
    where psql >nul 2>nul
    if %errorlevel% equ 0 (
        set PSQL_BIN=psql
    ) else (
        echo [ERROR] PostgreSQL client (psql.exe) was not found.
        pause
        exit /b 1
    )
)

if not exist "%~dp0neon_database.sql" (
    echo [ERROR] Backup file 'neon_database.sql' was not found in:
    echo %~dp0
    pause
    exit /b 1
)

echo Step 1: Get your Neon Connection String
echo ---------------------------------------------------------------------
echo 1. Go to https://console.neon.tech
echo 2. Open your project Dashboard
echo 3. Copy the "Connection string" (Pooled or Direct)
echo    Format: postgresql://[user]:[password]@[host]/[database]?sslmode=require
echo.
set /p NEON_URL="Paste your Neon Connection String here: "

:: Remove any accidental quotes
set NEON_URL=%NEON_URL:"=%
set NEON_URL=%NEON_URL:'=%

if "%NEON_URL%"=="" (
    echo.
    echo [ERROR] No connection string entered. Operation cancelled.
    pause
    exit /b 1
)

echo.
echo =====================================================================
echo  Step 2: Uploading database to Neon.tech... Please wait...
echo =====================================================================
echo.

"%PSQL_BIN%" "%NEON_URL%" -f "%~dp0neon_database.sql"

if %errorlevel% neq 0 (
    echo.
    echo [WARNING] Import completed with some notices or errors.
    echo Checking data verification...
) else (
    echo.
    echo [OK] Database dump executed successfully!
)

echo.
echo =====================================================================
echo  Step 3: Verifying data in Neon.tech Cloud Database
echo =====================================================================
"%PSQL_BIN%" "%NEON_URL%" -c "SELECT count(*) AS total_products FROM products; SELECT count(*) AS total_customers FROM customers; SELECT count(*) AS total_orders FROM sales_orders;"

echo.
echo =====================================================================
echo  Next Steps for Vercel Deployment:
echo =====================================================================
echo 1. Open your Vercel Project Dashboard: https://vercel.com
echo 2. Go to: Settings -> Environment Variables
echo 3. Add/Update:
echo    Name  : DATABASE_URL
echo    Value : %NEON_URL%
echo 4. Redeploy your project on Vercel!
echo =====================================================================
echo.
pause
