#!/bin/bash
# QueuePass Bot — Mac one-click launcher (double-click to run).
# First run installs everything automatically. Keep the Terminal window
# open while using the bot. If macOS blocks it the first time, right-click
# the file and choose Open, then confirm.
cd "$(dirname "$0")"

echo "============================================================================"
echo "  QueuePass Bot — Easy Launcher (No Technical Knowledge Required)"
echo "============================================================================"
echo ""

if ! command -v python3 >/dev/null 2>&1; then
    echo "[ERROR] Python 3 is not installed."
    echo "Please install Python 3.11+ from https://www.python.org/downloads/ and try again."
    echo "Press Enter to close."
    read -r _
    exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
    echo "[1/3] First-time setup: Creating isolated Python environment (.venv)..."
    python3 -m venv .venv
fi

if [ ! -f ".venv/.installed_ok" ]; then
    echo "[2/3] Installing required packages and Chromium browser (first run only)..."
    .venv/bin/python -m pip install --upgrade pip >/dev/null 2>&1
    .venv/bin/python -m pip install -r requirements.txt
    .venv/bin/python -m playwright install chromium
    if [ -d ".venv" ]; then
        echo ok > ".venv/.installed_ok"
    fi
fi

echo "[3/3] Opening QueuePass Bot Dashboard at http://127.0.0.1:5055 ..."
echo "      Keep this window open while using the bot."
echo ""
open "http://127.0.0.1:5055" 2>/dev/null || true
.venv/bin/python run.py

echo ""
echo "QueuePass Bot stopped. Press Enter to close."
read -r _
