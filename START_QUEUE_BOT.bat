@echo off
setlocal
title QueuePass Bot — Easy One-Click Launcher
cd /d "%~dp0"

echo ============================================================================
echo   QueuePass Bot — Easy Launcher (No Technical Knowledge Required)
echo ============================================================================
echo.

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not added to PATH.
    echo Please install Python 3.11+ from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] First-time setup: Creating isolated Python environment ^(.venv^)...
    python -m venv .venv
)

if exist ".venv\Scripts\python.exe" (
    set "PY_CMD=.venv\Scripts\python.exe"
) else (
    set "PY_CMD=python"
)

if not exist ".venv\.installed_ok" (
    echo [2/3] Installing required packages and Chromium browser ^(first run only^)...
    "%PY_CMD%" -m pip install --upgrade pip >nul 2>nul
    "%PY_CMD%" -m pip install -r requirements.txt
    "%PY_CMD%" -m playwright install chromium
    if exist ".venv" (
        echo ok > ".venv\.installed_ok"
    )
)

echo [3/3] Opening QueuePass Bot Dashboard at http://127.0.0.1:5055 ...
echo       Keep this window open while using the bot.
echo.
start "" "http://127.0.0.1:5055"
"%PY_CMD%" run.py

pause

