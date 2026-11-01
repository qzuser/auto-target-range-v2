@echo off
rem Windows native console launcher (cmd). Full tool sandbox: py -3 deploy.py up
rem Usage: launch.cmd --port 8000   (Ctrl+C to stop)
setlocal
cd /d "%~dp0"

set "PROJECT_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PROJECT_PYTHON%" (
    echo [launch] missing .venv - run: py -3 -m venv .venv
    echo [launch] then: .venv\Scripts\python.exe -m pip install -e .
    echo [launch] full deployment: py -3 deploy.py up
    exit /b 1
)

rem First start: set the admin password when none exists. Only the scrypt hash is
rem written to .spiritscout\admin.db; plaintext never hits the command line or disk.
rem Skipped automatically when an account exists or stdin is not interactive.
"%PROJECT_PYTHON%" -X utf8 -m spiritscout --set-admin-password --if-missing --config configs/system.yaml
"%PROJECT_PYTHON%" -X utf8 -m spiritscout --config configs/system.yaml %*
set "APP_EXIT=%ERRORLEVEL%"
endlocal & exit /b %APP_EXIT%
