@echo off
chcp 65001 >nul
title 灵枢 SpiritScout - 停止
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-all.ps1"
timeout /t 5 >nul
