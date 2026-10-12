@echo off
title inFlow Premium Data Migration (SQL Server -> PostgreSQL)
color 0B
echo ===================================================================
echo     inFlow Premium - Legacy SQL Server to PostgreSQL ETL Sync
echo ===================================================================

set RUNTIME_BASE=E:\odoo-ai-19.0\odoo-ai-19.0\runtime
set PYTHON_EXE=%RUNTIME_BASE%\python3\python.exe

if not exist "%PYTHON_EXE%" (
    set PYTHON_EXE=python
)

echo Starting automated ETL pipeline...
%PYTHON_EXE% migrate_inflow.py

echo.
echo Migration process finished.
pause
