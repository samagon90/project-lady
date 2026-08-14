@echo off
title Leia bot
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo ERROR: Python is not installed.
    echo.
    echo Install Python 3.12 from:  https://www.python.org/downloads/
    echo IMPORTANT: during install check the box "Add Python to PATH".
    echo.
    echo Then run this file again.
    echo.
    pause
    exit /b 1
)

python "%~dp0launcher.py" start
echo.
pause
