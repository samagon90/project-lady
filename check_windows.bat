@echo off
chcp 65001 >nul
title Лея — проверка готовности
cd /d "%~dp0"

if not exist .venv (
    echo Сначала запустите start_windows.bat
    pause
    exit /b 1
)

echo Проверяем, всё ли готово к запуску...
echo.
.venv\Scripts\python.exe scripts\doctor.py
echo.
pause
