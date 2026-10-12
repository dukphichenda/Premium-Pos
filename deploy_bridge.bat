@echo off
setlocal enabledelayedexpansion
title inFlow Premium - GitHub ^& Vercel Deployment Bridge

echo =====================================================================
echo          inFlow Premium Enterprise - Deployment Bridge
echo          Sync to GitHub ^& Deploy to Vercel (Cloud Hosting)
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
echo   [1] Push all changes to GitHub (Auto-triggers Vercel if connected)
echo   [2] Deploy directly to Vercel (using Vercel CLI)
echo   [3] All-In-One: Push to GitHub AND Deploy to Vercel
echo   [4] Check Git Status ^& Remote URLs
echo   [5] Exit
echo.
set /p CHOICE="Select an option (1-5) [default: 1]: "
if "%CHOICE%"=="" set CHOICE=1

if "%CHOICE%"=="1" goto PUSH_GITHUB
if "%CHOICE%"=="2" goto DEPLOY_VERCEL
if "%CHOICE%"=="3" goto ALL_IN_ONE
if "%CHOICE%"=="4" goto CHECK_STATUS
if "%CHOICE%"=="5" goto EXIT
echo Invalid choice. Please select 1, 2, 3, 4, or 5.
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
    set COMMIT_MSG=feat: update and sync inFlow Premium project - !DATE! !TIME!
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
    echo [WARNING] Push to origin encountered an issue. Check your connection or token.
)

echo.
echo Pushing to inflow-repo (dukphichenda/inflow-premium)...
git push inflow-repo main
if %ERRORLEVEL% equ 0 (
    echo [OK] Successfully pushed to inflow-repo!
) else (
    echo [NOTE] inflow-repo remote might not be set or requires authorization.
)

echo.
echo =====================================================================
echo  GitHub Sync Completed!
echo =====================================================================
echo If your Vercel project is connected to GitHub, your deployment will
echo trigger automatically at: https://vercel.com/dashboard
echo.
pause
goto MENU

:DEPLOY_VERCEL
echo.
echo =====================================================================
echo  Deploying directly to Vercel CLI
echo =====================================================================
call cmd.exe /c vercel --prod
echo.
pause
goto MENU

:ALL_IN_ONE
echo.
echo =====================================================================
echo  Running All-In-One: Git Push + Vercel Deployment
echo =====================================================================
set /p COMMIT_MSG="Enter commit message (Press Enter for auto timestamp): "
if "%COMMIT_MSG%"=="" (
    set COMMIT_MSG=feat: update inFlow Premium and deploy to Vercel - !DATE! !TIME!
)

git add .
git commit -m "%COMMIT_MSG%"
echo Pushing to GitHub...
git push origin main
git push inflow-repo main

echo.
echo Triggering Vercel deployment...
call cmd.exe /c vercel --prod
echo.
pause
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

:EXIT
echo Goodbye!
endlocal
