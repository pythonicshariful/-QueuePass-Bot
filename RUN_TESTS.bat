@echo off
setlocal
title QueuePass Bot — Run Automated Test Suite
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "PY_CMD=.venv\Scripts\python.exe"
) else (
    set "PY_CMD=python"
)

echo Running full pytest suite for QueuePass Bot...
"%PY_CMD%" -m pytest tests/ -v
pause

