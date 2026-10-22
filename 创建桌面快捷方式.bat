@echo off
chcp 65001 >nul
title 创建桌面快捷方式
cd /d "%~dp0"

echo 正在桌面创建「农智云演示」快捷方式...
powershell -NoProfile -Command ^
  "$w = New-Object -ComObject WScript.Shell; $d = [Environment]::GetFolderPath('Desktop'); $s = $w.CreateShortcut((Join-Path $d '农智云演示.lnk')); $s.TargetPath = '%~dp0启动演示系统.bat'; $s.WorkingDirectory = '%~dp0'; $s.Description = '一键启动农智云演示（服务器 + 演示指挥台）'; $s.Save(); if (Test-Path (Join-Path $d '农智云演示.lnk')) { exit 0 } else { exit 1 }"
if errorlevel 1 (
  echo [失败] 创建快捷方式失败。你可以直接双击「启动演示系统.bat」。
) else (
  echo [完成] 桌面已生成「农智云演示」，以后只双击它。
)
echo.
pause
