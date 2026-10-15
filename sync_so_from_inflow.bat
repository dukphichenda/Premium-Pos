@echo off
title inFlow Premium - Sync Sales Orders from inFlow (from SO-022821)
color 0B
echo ===================================================================
echo     inFlow Premium - Sync Sales Orders from inFlow Inventory
echo     Scope: Only orders starting from SO-022821
echo     Source: C:\Program Files (x86)\inFlow Inventory (.\INFLOWSQL)
echo ===================================================================

set RUNTIME_BASE=E:\odoo-ai-19.0\odoo-ai-19.0\runtime
set PYTHON_EXE=%RUNTIME_BASE%\python3\python.exe

if not exist "%PYTHON_EXE%" (
    set PYTHON_EXE=python
)

echo Starting Sales Orders sync (SO-022821 and above)...
"%PYTHON_EXE%" scripts\sync_sales_orders_from_22821.py

echo.
echo Process completed.
pause
