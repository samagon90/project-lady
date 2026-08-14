@echo off
setlocal
title Leia bot launcher
cd /d "%~dp0"

rem --- guard: old versions have no launcher.py ---
if not exist "%~dp0launcher.py" (
    echo.
    echo ERROR: launcher.py is missing in this folder.
    echo You are using an OLD copy of the bot.
    echo.
    echo Please download the NEW version from:
    echo   https://github.com/samagon90/project-lady/releases/tag/v0.1.2
    echo Click "Source code (zip)", extract it, then run start_windows.bat
    echo from the NEW folder. The new folder contains a file named launcher.py.
    echo.
    pause
    exit /b 1
)

rem --- find Python: prefer py launcher, fall back to python ---
set "PYTHONCMD=python"
where py >nul 2>nul
if not errorlevel 1 (
    py -3 -c "pass" >nul 2>nul
    if not errorlevel 1 set "PYTHONCMD=py -3"
)

if "%PYTHONCMD%"=="python" (
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
)

rem --- run: all logic and Russian hints live in launcher.py ---
%PYTHONCMD% "%~dp0launcher.py" start
echo.
pause
