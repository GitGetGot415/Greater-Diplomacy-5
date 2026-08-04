@echo off
title GD5 Web Build Server
:: This script lives in compilation_scripts/, but web_stage/ and venv/ are both at
:: the project root, so hop up one level from this script's own directory.
cd /d "%~dp0.."

if not exist "web_stage\build\web\index.html" (
    echo ============================================================
    echo No web build found yet. Run html_compilation.py first:
    echo     venv\Scripts\python.exe compilation_scripts\html_compilation.py
    echo ============================================================
    pause
    exit /b 1
)

:: Kill any server already bound to port 8000 from a previous run of this
:: script -- two pygbag servers racing for the same port is what causes the
:: browser to hang forever on "Loading... please wait" (requests get split
:: unpredictably between the two processes).
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000" ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F >nul 2>&1
)

echo Starting local web server for the browser build...
echo Close this window to stop the server.
echo.

:: Open the browser a few seconds after this window starts, giving the
:: server below (which blocks this window until closed) time to come up.
start "" cmd /c "timeout /t 3 /nobreak >nul && start "" http://localhost:8000/"

:: --template must match html_compilation.py's build, or this regenerates index.html
:: from pygbag's stock template and undoes the aspect-ratio fix in web_index.tmpl.
.\venv\Scripts\python.exe -m pygbag --app_name "Greater Diplomacy 5" --disable-sound-format-error --ume_block 0 --template compilation_scripts\web_index.tmpl web_stage

pause
