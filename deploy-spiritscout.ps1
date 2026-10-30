# SpiritScout（灵枢）一键部署 —— Windows + Docker Desktop
#
# 为什么必须 Docker：CTF 解题的 shell/python 工具硬依赖 bubblewrap，
# Windows 原生 sandbox_available=False（已实测），工具会直接拒绝执行。
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File .\deploy-spiritscout.ps1
#   powershell -ExecutionPolicy Bypass -File .\deploy-spiritscout.ps1 -SkipBuild   # 已构建过
#
# 首次构建较慢（node+playwright-mcp、pip 装 litellm/langgraph，加 CTF 工具箱更久）。

[CmdletBinding()]
param(
    [switch]$SkipBuild,
    [switch]$NoToolkit,
    [int]$Port = 10010,
    [string]$AdminUser = 'spiritscout',
    [string]$AdminPassword = ''
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$app = Join-Path $root 'SpiritScout'
if (-not (Test-Path (Join-Path $app 'docker-compose.yml'))) {
    throw "找不到 SpiritScout 仓库：$app"
}

# ---------------------------------------------------------------- 1. 管理员凭据
$envFile = Join-Path $app '.env'
if (-not (Test-Path $envFile)) {
    if (-not $AdminPassword) {
        $bytes = New-Object byte[] 12
        [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
        $AdminPassword = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+','x').Replace('/','y')
    }
    @(
        '# 由 deploy-spiritscout.ps1 生成',
        "SPIRITSCOUT_ADMIN_USERNAME=$AdminUser",
        "SPIRITSCOUT_ADMIN_PASSWORD=$AdminPassword",
        "SPIRITSCOUT_PORT=$Port",
        'INSTALL_TOOLKIT=1',
        'PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple'
    ) | Set-Content -Path $envFile -Encoding UTF8
    Write-Host "[1/4] 已生成 .env（用户名 $AdminUser / 密码 $AdminPassword）" -ForegroundColor Green
} else {
    Write-Host "[1/4] 复用既有 .env（端口/密码以文件为准）" -ForegroundColor Yellow
}

# ---------------------------------------------------------------- 2. Docker 引擎
function Test-Docker {
    try { docker info --format '{{.ServerVersion}}' 2>$null | Out-Null; return $true }
    catch { return $false }
}

if (-not (Test-Docker)) {
    $desktop = Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\Docker Desktop.exe'
    if (-not (Test-Path $desktop)) { throw "Docker 守护进程未运行，且找不到 Docker Desktop：$desktop" }
    Write-Host "[2/4] 启动 Docker Desktop，等待引擎就绪（最多 240s）..." -ForegroundColor Yellow
    Start-Process -FilePath $desktop | Out-Null
    $deadline = (Get-Date).AddSeconds(240)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 6
        if (Test-Docker) { break }
    }
    if (-not (Test-Docker)) { throw "Docker 引擎 240s 内未就绪：手动打开 Docker Desktop 并等鲸鱼图标稳定后重跑" }
}
Write-Host ("[2/4] Docker 引擎就绪：{0}" -f (docker info --format '{{.ServerVersion}}')) -ForegroundColor Green

# ---------------------------------------------------------------- 3. 构建镜像
Push-Location $app
try {
    if (-not $NoToolkit) { $env:INSTALL_TOOLKIT = '1' }
    if (-not $SkipBuild) {
        Write-Host "[3/4] 构建镜像（首次 10-30 分钟，含 CTF 工具箱）..." -ForegroundColor Yellow
        docker compose build
        if ($LASTEXITCODE -ne 0) { throw "docker compose build 失败（看上面输出）" }
    } else {
        Write-Host "[3/4] 跳过构建" -ForegroundColor Yellow
    }

    # ------------------------------------------------------------ 4. 起服务
    Write-Host "[4/4] 启动容器..." -ForegroundColor Yellow
    docker compose up -d --wait
    if ($LASTEXITCODE -ne 0) { throw "docker compose up 失败" }
} finally {
    Pop-Location
}

$port = (Get-Content $envFile | Where-Object { $_ -match '^SPIRITSCOUT_PORT=' }) -replace '^SPIRITSCOUT_PORT=',''
if (-not $port) { $port = $Port }
$user = (Get-Content $envFile | Where-Object { $_ -match '^SPIRITSCOUT_ADMIN_USERNAME=' }) -replace '^SPIRITSCOUT_ADMIN_USERNAME=',''
$pass = (Get-Content $envFile | Where-Object { $_ -match '^SPIRITSCOUT_ADMIN_PASSWORD=' }) -replace '^SPIRITSCOUT_ADMIN_PASSWORD=',''

Write-Host ""
Write-Host "==== 灵枢已就位 ====" -ForegroundColor Cyan
Write-Host "控制台 : http://127.0.0.1:$port"
Write-Host "账号   : $user"
Write-Host "密码   : $pass"
Write-Host ""
Write-Host "下一步："
Write-Host "  1) 控制台「模型」页填 Base URL / API Key / 模型 ID，再在「编队」页指派给灵枢与子 Agent"
Write-Host "  2) 首页选 CTF 模式，任务里贴平台适配器档案与你的目标地址"
Write-Host "  报告落在容器卷 /app/.spiritscout/sessions/<会话>/reports/"
