@echo off
title Starting Greater Diplomacy 5...

:: 1. Create venv if it doesn't exist yet
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

:: 2. Activate venv & install dependencies
call venv\Scripts\activate.bat
echo Checking dependencies...
pip install -r requirements.txt

:: 3. Launch the game
echo Launching Greater Diplomacy 5...
python main.py
