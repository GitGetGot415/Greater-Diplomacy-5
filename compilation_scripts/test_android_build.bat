@echo off
title GD5 Android Test
cd /d "%~dp0.."
if not exist "venv\Scripts\python.exe" (
    echo Project Python not found. Run compilation_scripts\run.bat once first.
    pause
    exit /b 1
)
"venv\Scripts\python.exe" "compilation_scripts\test_android_build.py" %*
set "android_test_exit=%errorlevel%"
pause
exit /b %android_test_exit%
