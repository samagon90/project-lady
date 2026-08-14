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

rem --- find Python: prefer py launcher, fall back to python; auto-install via winget ---
set "PYTHONCMD="
where py >nul 2>nul
if not errorlevel 1 (
    py -3 -c "pass" >nul 2>nul
    if not errorlevel 1 set "PYTHONCMD=py -3"
)
if "%PYTHONCMD%"=="" (
    where python >nul 2>nul
    if not errorlevel 1 set "PYTHONCMD=python"
)
if "%PYTHONCMD%"=="" (
    echo.
    echo Python is not installed. Trying to install it automatically...
    echo.
    winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
    echo.
    echo Python has been installed. Close this window and run start_windows.bat again.
    echo.
    pause
    exit /b 1
)

rem --- run: all logic and Russian hints live in launcher.py ---
%PYTHONCMD% "%~dp0launcher.py" start
echo.
pause
