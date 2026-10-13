@echo off
setlocal enabledelayedexpansion
title inFlow Premium - GitHub Sync ^& Cloudflare Remote Access
color 0B

echo =====================================================================
echo          inFlow Premium Enterprise - Cloud Bridge
echo          Sync to GitHub ^& Cloudflare Remote Access Tunnel
echo =====================================================================
echo.

:: Check git availability
where git >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Git is not installed or not found in system PATH.
    echo Please install Git from https://git-scm.com/
    pause
    exit /b 1
)

:MENU
echo What would you like to do?
echo   [1] Push all changes to GitHub (origin ^& inflow-repo)
echo   [2] Launch Cloudflare Remote Access Tunnel (share_online.bat)
echo   [3] Check Git Status ^& Remote URLs
echo   [4] Install Cloudflare Tunnel as 24/7 Windows Service
echo   [5] Exit
echo.
set /p CHOICE="Select an option (1-5) [default: 1]: "
if "%CHOICE%"=="" set CHOICE=1

if "%CHOICE%"=="1" goto PUSH_GITHUB
if "%CHOICE%"=="2" goto LAUNCH_TUNNEL
if "%CHOICE%"=="3" goto CHECK_STATUS
if "%CHOICE%"=="4" goto INSTALL_SERVICE
if "%CHOICE%"=="5" goto EXIT
echo Invalid choice. Please select 1 to 5.
echo.
goto MENU

:PUSH_GITHUB
echo.
echo =====================================================================
echo  Step 1: Staging and Committing Changes
echo =====================================================================
set /p COMMIT_MSG="Enter commit message (Press Enter for auto timestamp): "
if "%COMMIT_MSG%"=="" (
    for /f "tokens=1-4 delims=/ " %%a in ("%DATE%") do set TDATE=%%a-%%b-%%c
    set COMMIT_MSG=feat: update and sync inFlow Premium - !DATE! !TIME!
)

git add .
git commit -m "%COMMIT_MSG%"

echo.
echo =====================================================================
echo  Step 2: Pushing to GitHub Remotes
echo =====================================================================
echo Pushing to origin (dukphichenda/Premium-Pos)...
git push origin main
if %ERRORLEVEL% equ 0 (
    echo [OK] Successfully pushed to origin!
) else (
    echo [WARNING] Push to origin encountered an issue. Check connection or token.
)

echo.
echo Pushing to inflow-repo (dukphichenda/inflow-premium)...
git push inflow-repo main
if %ERRORLEVEL% equ 0 (
    echo [OK] Successfully pushed to inflow-repo!
) else (
    echo [NOTE] inflow-repo remote might not be set or already in sync.
)

echo.
echo =====================================================================
echo  GitHub Sync Completed!
echo =====================================================================
echo Repositories updated:
echo   - https://github.com/dukphichenda/Premium-Pos
echo   - https://github.com/dukphichenda/inflow-premium
echo.
pause
goto MENU

:LAUNCH_TUNNEL
call "%~dp0share_online.bat"
goto MENU

:CHECK_STATUS
echo.
echo =====================================================================
echo  Git Status and Configured Remotes
echo =====================================================================
git status
echo.
echo Remotes:
git remote -v
echo.
pause
goto MENU

:INSTALL_SERVICE
echo.
echo =====================================================================
echo  Cloudflare Tunnel - 24/7 Windows Background Service Setup
echo =====================================================================
echo 1. Go to Cloudflare Zero Trust: https://dash.cloudflare.com
echo 2. Go to: Networks -^> Tunnels -^> Create a Tunnel (Cloudflared)
echo 3. Choose Windows 64-bit and copy your tunnel token.
echo.
set /p CF_TOKEN="Paste your Cloudflare Tunnel Token here (or press Enter to cancel): "
if "%CF_TOKEN%"=="" (
    echo Operation cancelled.
    pause
    goto MENU
)

set CLOUDFLARED_BIN=C:\Program Files (x86)\cloudflared\cloudflared.exe
if not exist "%CLOUDFLARED_BIN%" set CLOUDFLARED_BIN=cloudflared

echo Installing service...
"%CLOUDFLARED_BIN%" service install %CF_TOKEN%
if %ERRORLEVEL% equ 0 (
    echo [OK] Cloudflare Tunnel Windows Service installed and running 24/7!
) else (
    echo [ERROR] Installation failed. Make sure you run this script as Administrator.
)
pause
goto MENU

:EXIT
echo Goodbye!
endlocal
