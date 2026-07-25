@echo off
title Starting Greater Diplomacy 5...

:: Ensure script operates in its own directory
cd /d "%~dp0"

:: 1. Create venv if python.exe doesn't exist inside it
if not exist "venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv venv
)

:: 2. Install dependencies using venv's python
echo Checking dependencies...
.\venv\Scripts\python.exe -m pip install -r requirements.txt

:: 3. Launch the game using venv's python
echo Launching Greater Diplomacy 5...
.\venv\Scripts\python.exe main.py

pause

