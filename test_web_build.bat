@echo off
title GD5 Web Build Server
cd /d "%~dp0"

if not exist "web_stage\build\web\index.html" (
    echo ============================================================
    echo No web build found yet. Run html_compilation.py first:
    echo     venv\Scripts\python.exe html_compilation.py
    echo ============================================================
    pause
    exit /b 1
)

echo Starting local web server for the browser build...
echo Close this window to stop the server.
echo.

:: Open the browser a few seconds after this window starts, giving the
:: server below (which blocks this window until closed) time to come up.
start "" cmd /c "timeout /t 3 /nobreak >nul && start "" http://localhost:8000/"

.\venv\Scripts\python.exe -m pygbag --app_name "Greater Diplomacy 5" --disable-sound-format-error --ume_block 0 web_stage

pause
