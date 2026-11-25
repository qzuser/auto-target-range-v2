@echo off
rem Windows native console launcher (cmd). Full tool sandbox: py -3 deploy.py up
rem Usage: scripts\windows\start-console.cmd --port 8000
rem
rem Console login is OFF by default (web.auth_mode: none): the workbench opens
rem straight into the UI on 127.0.0.1, no password prompt at startup.
rem To turn it back on:  .venv\Scripts\python.exe -m spiritscout --set-admin-password
rem                      then start with:  scripts\windows\start-console.cmd --auth password
rem To wipe stored credentials: --clear-admin-password
setlocal
cd /d "%~dp0..\.."
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

set "PROJECT_PYTHON=%CD%\.venv\Scripts\python.exe"
if not exist "%PROJECT_PYTHON%" (
    echo [launch] missing .venv - run: py -3 -m venv .venv
    echo [launch] then: .venv\Scripts\python.exe -m pip install -e . -i https://pypi.tuna.tsinghua.edu.cn/simple
    echo [launch] (-i points pip at the Tsinghua PyPI mirror; drop it to use pypi.org)
    echo [launch] full deployment: py -3 deploy.py up
    exit /b 1
)

"%PROJECT_PYTHON%" -X utf8 -m spiritscout --config configs/system.yaml %*
set "APP_EXIT=%ERRORLEVEL%"
endlocal & exit /b %APP_EXIT%
