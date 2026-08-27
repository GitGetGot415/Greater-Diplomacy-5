@echo off
title Starting Greater Diplomacy 5...

:: This script normally lives in compilation_scripts/, with venv/requirements.txt/main.py
:: at the project root one level up. But if someone moves/copies this .bat to the
:: project root itself (e.g. for easier double-clicking), going up a level would land
:: one folder too high. So check both spots and use whichever actually has main.py.
if exist "%~dp0..\main.py" (
    cd /d "%~dp0.."
) else if exist "%~dp0main.py" (
    cd /d "%~dp0"
) else (
    echo ============================================================
    echo ERROR: Could not find main.py near this script.
    echo ============================================================
    echo This script expects to be inside the "compilation_scripts" folder
    echo of the Greater Diplomacy 5 project, with main.py one level up.
    echo.
    echo Please make sure you kept the full project folder intact and run
    echo this script from its original location inside compilation_scripts.
    echo ============================================================
    pause
    exit /b 1
)
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


