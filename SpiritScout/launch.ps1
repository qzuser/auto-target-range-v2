# Windows 原生控制台。完整工具沙箱请使用 python deploy.py up。
# 用法：.\launch.ps1 --port 8000；Ctrl+C 停止。
$ErrorActionPreference = 'Stop'
$appArguments = $args
$projectPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) {
    throw "缺少虚拟环境：先运行 py -3 -m venv .venv，再运行 .venv\Scripts\python.exe -m pip install -e .；完整部署可运行 py -3 deploy.py up"
}
Push-Location -LiteralPath $PSScriptRoot
try {
    # 首次启动：还没有管理员就当场设密码。只把 scrypt 哈希写进 .spiritscout\admin.db，
    # 明文不进命令行也不落盘；已有账号、或不是交互终端（管道里调用）时自动跳过。
    & $projectPython -X utf8 -m spiritscout --set-admin-password --if-missing --config configs/system.yaml
    & $projectPython -X utf8 -m spiritscout --config configs/system.yaml @appArguments
    $appExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $appExitCode
