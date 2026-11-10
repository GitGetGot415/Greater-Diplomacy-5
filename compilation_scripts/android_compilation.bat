@echo off
title GD5 Android Build
cd /d "%~dp0.."
if not exist "venv\Scripts\python.exe" (
    echo Project Python not found. Run compilation_scripts\run.bat once first.
    pause
    exit /b 1
)
"venv\Scripts\python.exe" "compilation_scripts\android_compilation.py" %*
set "android_build_exit=%errorlevel%"
pause
exit /b %android_build_exit%
