# Windows 原生控制台。完整工具沙箱请使用 python deploy.py up。
# 用法：.\scripts\windows\start-console.ps1 --port 8000；Ctrl+C 停止。
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$appArguments = $args
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$projectPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) {
    throw "缺少虚拟环境：先运行 uv sync（或 py -3 -m venv .venv && .venv\Scripts\python.exe -m pip install -e .）；完整部署可运行 py -3 deploy.py up"
}
Push-Location -LiteralPath $repoRoot
try {
    & $projectPython -X utf8 -m spiritscout --config configs/system.yaml @appArguments
    $appExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $appExitCode
