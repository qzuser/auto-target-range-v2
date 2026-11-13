@echo off
chcp 65001 >nul
title 灵枢 SpiritScout - 启动
cd /d "%~dp0"
echo.
echo =============================================
echo   灵枢 SpiritScout - 一键启动
echo =============================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-all.ps1"
if errorlevel 1 (
  echo.
  echo [启动失败] 看上面的提示，或 _workgent-server.log
  pause
)
