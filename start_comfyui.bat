@echo off
title ComfyUI for Leia bot
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
    echo First run the bot launcher and choose to install ComfyUI.
    pause
    exit /b 1
)
echo Starting ComfyUI. Keep this window open while you want images.
echo Close this window to stop ComfyUI.
venv\Scripts\python.exe main.py --listen 127.0.0.1 --port 8188
pause
