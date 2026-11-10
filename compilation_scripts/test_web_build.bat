@echo off
title GD5 Web Build Server
:: This script lives in compilation_scripts/, but dist/ and venv/ are both at
:: the project root, so hop up one level from this script's own directory.
cd /d "%~dp0.."

.\venv\Scripts\python.exe compilation_scripts\test_web_build.py
set "web_test_exit=%errorlevel%"

pause
exit /b %web_test_exit%
