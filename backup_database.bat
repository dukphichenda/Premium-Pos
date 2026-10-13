@echo off
setlocal enabledelayedexpansion
title inFlow Premium - PostgreSQL Database Backup
color 0A

echo =====================================================================
echo         inFlow Premium - Automated Database Export
echo         Generates a complete PostgreSQL SQL dump for Hostinger/Cloud
echo =====================================================================
echo.

set PGDUMP_BIN=E:\odoo-ai-19.0\odoo-ai-19.0\runtime\pgsql\bin\pg_dump.exe
if not exist "!PGDUMP_BIN!" (
    where pg_dump >nul 2>nul
    if !ERRORLEVEL! equ 0 (
        set PGDUMP_BIN=pg_dump
    ) else (
        echo [ERROR] pg_dump.exe not found!
        pause
        exit /b 1
    )
)

echo [1/2] Exporting database 'inflow_premium'...
set OUTPUT_FILE=%~dp0inflow_premium_backup.sql

"!PGDUMP_BIN!" -U odoo -h 127.0.0.1 -p 5432 -d inflow_premium --no-owner --no-acl -f "!OUTPUT_FILE!"

if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Database backup failed. Ensure PostgreSQL is running on port 5432.
    pause
    exit /b 1
)

echo [2/2] Verifying backup file...
for %%A in ("!OUTPUT_FILE!") do set FILESIZE=%%~zA
set /a FILESIZE_MB=FILESIZE/1024/1024

echo.
echo =====================================================================
echo  Database Export SUCCESSFUL!
echo =====================================================================
echo  Output File : !OUTPUT_FILE!
echo  File Size   : ~!FILESIZE_MB! MB (!FILESIZE! bytes)
echo.
echo  Ready to upload to Hostinger or your production server!
echo =====================================================================
echo.
pause
