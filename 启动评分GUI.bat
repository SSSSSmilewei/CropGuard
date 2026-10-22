@echo off
chcp 65001 >nul
title CropGuard 评分 GUI（20 样本 / 180 秒）
cd /d "%~dp0"

REM 没有 NVIDIA 显卡就用 CPU（不改配置文件）
nvidia-smi >nul 2>nul
if errorlevel 1 set "CG_DEVICE=cpu"

echo 正在打开评分 GUI（约 5-10 秒）...
py -3.14 -B main.py
if errorlevel 1 python -B main.py

echo.
echo GUI 已退出。评分报告在 output\ 目录下（未导出时程序会自动静默导出一份）。
pause
