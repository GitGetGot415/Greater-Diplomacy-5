@echo off
title Starting Greater Diplomacy 5...

:: This script lives in compilation_scripts/, but venv/requirements.txt/main.py are all
:: at the project root, so hop up one level from this script's own directory.
cd /d "%~dp0.."

:: 1. Check if virtual environment already exists
if exist "venv\Scripts\python.exe" goto RUN_GAME

:: 2. Find Python launcher (try 'py' first, then 'python')
set "PYTHON_EXE="
py -0 >nul 2>&1
if %errorlevel%==0 (
    set "PYTHON_EXE=py"
) else (
    python --version >nul 2>&1
    if %errorlevel%==0 (
        set "PYTHON_EXE=python"
    )
)

if "%PYTHON_EXE%"=="" (
    echo ============================================================
    echo ERROR: Python was not found on your system.
    echo ============================================================
    echo Please install Python from https://www.python.org/
    echo IMPORTANT: Make sure to check "Add Python to PATH" during setup.
    echo.
    echo If Python is already installed, turn off the Windows App Alias:
    echo Windows Settings -^> Apps -^> Advanced app settings -^> App execution aliases
    echo and turn OFF "python.exe" and "python3.exe".
    echo ============================================================
    pause
    exit /b 1
)

echo Creating virtual environment using %PYTHON_EXE%...
%PYTHON_EXE% -m venv venv

if not exist "venv\Scripts\python.exe" (
    echo ERROR: Failed to create virtual environment.
    pause
    exit /b 1
)

:RUN_GAME
echo Checking dependencies...
.\venv\Scripts\python.exe -m pip install -r requirements.txt

echo Launching Greater Diplomacy 5...
.\venv\Scripts\python.exe main.py

pause


