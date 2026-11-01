@echo off
rem Windows native console launcher (cmd). Full tool sandbox: py -3 deploy.py up
rem Usage: launch.cmd --port 8000   (Ctrl+C to stop)
rem
rem Console login is OFF by default (web.auth_mode: none): the workbench opens
rem straight into the UI on 127.0.0.1, no password prompt at startup.
rem To turn it back on:  .venv\Scripts\python.exe -m spiritscout --set-admin-password
rem                      then start with:  launch.cmd --auth password
rem To wipe stored credentials: --clear-admin-password
setlocal
cd /d "%~dp0"

set "PROJECT_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PROJECT_PYTHON%" (
    echo [launch] missing .venv - run: py -3 -m venv .venv
    echo [launch] then: .venv\Scripts\python.exe -m pip install -e .
    echo [launch] full deployment: py -3 deploy.py up
    exit /b 1
)

"%PROJECT_PYTHON%" -X utf8 -m spiritscout --config configs/system.yaml %*
set "APP_EXIT=%ERRORLEVEL%"
endlocal & exit /b %APP_EXIT%
