@echo off
title Lilith bot checker
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo First run start_windows.bat to install the bot.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" scripts\doctor.py
echo.
pause
