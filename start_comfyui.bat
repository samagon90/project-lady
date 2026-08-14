@echo off
title ComfyUI for Leia bot (CPU mode)
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
    echo First run the bot launcher and choose to install ComfyUI.
    pause
    exit /b 1
)
echo Starting ComfyUI in CPU mode. Keep this window open while you want images.
echo Close this window to stop ComfyUI.
echo.
echo If you have an NVIDIA GPU, you can install the CUDA version of torch
echo to make images MUCH faster (see README, section 7).
echo.
set PYTORCH_ENABLE_MPS_FALLBACK=1
venv\Scripts\python.exe main.py --listen 127.0.0.1 --port 8188 --cpu
pause
