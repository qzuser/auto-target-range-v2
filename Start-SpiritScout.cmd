@echo off
chcp 65001 >nul
title SpiritScout
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

call "%~dp0scripts\windows\start-web.cmd" %*
exit /b %ERRORLEVEL%
