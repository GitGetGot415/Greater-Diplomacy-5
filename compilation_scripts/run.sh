#!/usr/bin/env bash

# This script normally lives in compilation_scripts/, with venv/requirements.txt/main.py
# at the project root one level up. But if someone moves/copies this script to the
# project root itself (e.g. for easier double-clicking), going up a level would land
# one folder too high. So check both spots and use whichever actually has main.py.
SCRIPT_DIR="$(dirname "$0")"
if [ -f "$SCRIPT_DIR/../main.py" ]; then
    cd "$SCRIPT_DIR/.." || exit 1
elif [ -f "$SCRIPT_DIR/main.py" ]; then
    cd "$SCRIPT_DIR" || exit 1
else
    echo "============================================================"
    echo "ERROR: Could not find main.py near this script."
    echo "============================================================"
    echo "This script expects to be inside the \"compilation_scripts\" folder"
    echo "of the Greater Diplomacy 5 project, with main.py one level up."
    echo ""
    echo "Please make sure you kept the full project folder intact and run"
    echo "this script from its original location inside compilation_scripts."
    echo "============================================================"
    exit 1
fi

echo "Starting Greater Diplomacy 5..."

# 1. Check if virtual environment already exists
if [ ! -f "venv/bin/python" ]; then
    # 2. Find Python executable (try python3 first, then python)
    PYTHON_EXE=""
    if command -v python3 >/dev/null 2>&1; then
        PYTHON_EXE="python3"
    elif command -v python >/dev/null 2>&1; then
        PYTHON_EXE="python"
    fi

    if [ -z "$PYTHON_EXE" ]; then
        echo "============================================================"
        echo "ERROR: Python 3 was not found on your system."
        echo "============================================================"
        echo "Please install Python 3 using your package manager or from:"
        echo "https://www.python.org/"
        echo "============================================================"
        exit 1
    fi

    echo "Creating virtual environment using $PYTHON_EXE..."
    "$PYTHON_EXE" -m venv venv

    if [ ! -f "venv/bin/python" ]; then
        echo "ERROR: Failed to create virtual environment."
        echo "If you are on Debian/Ubuntu, run: sudo apt install python3-venv"
        exit 1
    fi
fi

# 3. Install dependencies using venv's python
echo "Checking dependencies..."
./venv/bin/python -m pip install -r requirements.txt

# 4. Launch the game
echo "Launching Greater Diplomacy 5..."
./venv/bin/python main.py
