@echo off
chcp 65001 >nul
title SpiritScout 灵枢 - 前台服务（关闭本窗口即全部停止）
cd /d "%~dp0"

rem -------------------------------------------------------------------
rem Keep this file as UTF-8 WITHOUT BOM with CRLF line endings.
rem With a BOM, cmd cannot parse the first @echo off line and then
rem echoes every command - including the expanded model key - onto
rem the console. Comments here stay ASCII on purpose: cmd reads
rem batch files by byte offset, and multi-byte text inside rem
rem lines can shift line boundaries. The check below also uses
rem 'if not defined' rather than comparing the value, so the
rem secret is never expanded into a command line at all.
rem -------------------------------------------------------------------

if not defined SPIRITSCOUT_REMOTE_LLM_KEY (
    echo [i] 这次没检测到模型 key（SPIRITSCOUT_REMOTE_LLM_KEY）。
    echo     不影响启动：进控制台后到「模型」页给供应商填 key 就行，
    echo     密钥加密存进本机密钥库，以后不用再设环境变量。
    echo     想用环境变量也可以：setx SPIRITSCOUT_REMOTE_LLM_KEY "你的key"
    echo.
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-local.ps1" -Port 8010

echo.
echo [=] 控制台已退出。
echo     若上面报错，直接看本窗口的输出（控制台为前台运行，不重定向到日志文件）。
echo.
pause
