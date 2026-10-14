@echo off
title inFlow Premium - HQ Sync from Legacy inFlow Inventory
color 0B
echo ===================================================================
echo     inFlow Premium - Sync HQ Products, Customers, Orders
echo     Source: C:\Program Files (x86)\inFlow Inventory (.\INFLOWSQL)
echo ===================================================================

set RUNTIME_BASE=E:\odoo-ai-19.0\odoo-ai-19.0\runtime
set PYTHON_EXE=%RUNTIME_BASE%\python3\python.exe

if not exist "%PYTHON_EXE%" (
    set PYTHON_EXE=python
)

echo Starting selective purge and HQ synchronization...
%PYTHON_EXE% scripts\sync_hq_from_inflow.py

echo.
echo Process completed.
pause
