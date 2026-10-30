# 本机启动器（不用 Docker）
#
# 作用：导出执行后端与模型网关 key → 启动灵枢 Web 控制台。
# 依赖：Python 3.11 venv（SpiritScout\.venv）、Git for Windows 的 bash。
#
#   powershell -ExecutionPolicy Bypass -File .\start-local.ps1
#   powershell -ExecutionPolicy Bypass -File .\start-local.ps1 -Port 8010
#
param(
    [int]$Port = 8010,
    [switch]$Debug,
    [switch]$Fix
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$venvPy = Join-Path $root 'SpiritScout\.venv\Scripts\python.exe'

if (-not (Test-Path $venvPy)) {
    Write-Host "[!] 缺虚拟环境：先执行" -ForegroundColor Yellow
    Write-Host "    py -3.11 -m venv SpiritScout\.venv"
    Write-Host "    SpiritScout\.venv\Scripts\python.exe -m pip install -e `"SpiritScout[toolkit]`""
    exit 1
}

# 0.5) 依赖自检。交给 SpiritScout\scripts\probe_deps.py：它按 pyproject 里的
#      分发名查 importlib.metadata，不导入任何模块（光导入 litellm 就要几秒，
#      启动自检不该付这个代价）。缺依赖时立刻停下并给出安装命令，比 cd 进去
#      跑到一半抛 ImportError 好懂得多。
$depsProbe = Join-Path $root 'SpiritScout\scripts\probe_deps.py'
$deps = $null
if (Test-Path $depsProbe) {
    $depsJson = & $venvPy -X utf8 $depsProbe --toolkit --json 2>$null | Out-String
    if ($depsJson -and $depsJson.Trim()) {
        try { $deps = $depsJson | ConvertFrom-Json } catch { }
    }
}

if ($deps) {
    $pyVersion = $deps.python
    $missing = @($deps.runtime_missing)
    $missingToolkit = @($deps.toolkit_missing)
} else {
    # 旧版本仓库还没有探针脚本：只核对 Python 版本，其余交给运行时去报错
    $pyVersion = & $venvPy -X utf8 -c "import sys; print(str(sys.version_info[0]) + '.' + str(sys.version_info[1]))" 2>$null
    $missing = @()
    $missingToolkit = @()
}

if (-not $pyVersion) {
    Write-Host "[x] 虚拟环境里的 python.exe 跑不起来，建议删掉 SpiritScout\.venv 重建" -ForegroundColor Red
    exit 1
}
if ([version]$pyVersion -lt [version]'3.11') {
    Write-Host "[x] 虚拟环境是 Python $pyVersion，灵枢需要 3.11 或更高" -ForegroundColor Red
    Write-Host "    py -3.11 -m venv SpiritScout\.venv"
    Write-Host "    SpiritScout\.venv\Scripts\python.exe -m pip install -e `"SpiritScout`""
    exit 1
}

if ($missing.Count -gt 0) {
    Write-Host "[x] 缺 $($missing.Count) 个运行依赖：$($missing -join ', ')" -ForegroundColor Red
    Write-Host "    安装：SpiritScout\.venv\Scripts\python.exe -m pip install -e `"SpiritScout`""
    if ($Fix) {
        Write-Host "[>] 带了 -Fix，开始安装（首次要几分钟）…" -ForegroundColor Cyan
        Push-Location $root
        try { & $venvPy -m pip install -e 'SpiritScout' } finally { Pop-Location }
        if ($LASTEXITCODE -ne 0) { Write-Host "[x] 安装失败，看上面 pip 的输出" -ForegroundColor Red; exit 1 }
        Write-Host "[+] 依赖已装好，继续启动" -ForegroundColor Green
    } else {
        Write-Host "    或加 -Fix 让启动器自己装：start-local.ps1 -Fix"
        exit 1
    }
}

# 工具包是可选组，缺了不影响启动，但 CTF 的 pwn/crypto 环节会缺工具。
if ($missingToolkit.Count -gt 0) {
    Write-Host "[!] 可选工具包不全（CTF 的 pwn/crypto 会缺工具）：$($missingToolkit -join ', ')" -ForegroundColor Yellow
    Write-Host "    需要时装：SpiritScout\.venv\Scripts\python.exe -m pip install -e `"SpiritScout[toolkit]`""
}

$systemCfg = Join-Path $root 'SpiritScout\configs\system.yaml'
if (-not (Test-Path $systemCfg)) {
    Write-Host "[x] 缺配置文件：SpiritScout\configs\system.yaml" -ForegroundColor Red
    Write-Host "    copy SpiritScout\configs\system.example.yaml SpiritScout\configs\system.yaml"
    exit 1
}

# 端口被占是启动失败最常见的原因（多半是上一次的控制台没退干净），
# 提前查出来，比让 uvicorn 抛 WinError 10048 清楚。
try {
    if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
        Write-Host "[x] 端口 $Port 已被占用（常见于上次没退干净的控制台）" -ForegroundColor Red
        Write-Host "    看是谁：Get-NetTCPConnection -LocalPort $Port | Select-Object OwningProcess"
        Write-Host "    或换端口：start-local.ps1 -Port $($Port + 1)"
        exit 1
    }
} catch { }

Write-Host "[+] 依赖自检通过（Python $pyVersion，运行依赖齐全）" -ForegroundColor Green
if ($missingToolkit.Count -eq 0) { Write-Host "    可选工具包也齐全" }

# 1) 模型渠道：优先自定义 OpenAI 兼容渠道（SPIRITSCOUT_REMOTE_LLM_KEY），
#    没有再退回本机 DSH 网关。key 只进环境变量，不写文件。
$remoteKey = $env:SPIRITSCOUT_REMOTE_LLM_KEY
if ($remoteKey) {
    Write-Host "[+] 使用自定义渠道 key（SPIRITSCOUT_REMOTE_LLM_KEY）"
} else {
    $gateway = 'http://127.0.0.1:18923/v1'
    if (-not $env:SPIRITSCOUT_LOCAL_LLM_KEY) {
        $settings = Join-Path $env:USERPROFILE '.dsh\our-free-model\settings.json'
        if (Test-Path $settings) {
            $raw = Get-Content $settings -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
            if ($raw -and $raw -match '"forwardKey"\s*:\s*"([^"]+)"') { $env:SPIRITSCOUT_LOCAL_LLM_KEY = $Matches[1] }
        }
    }
    if (-not $env:SPIRITSCOUT_LOCAL_LLM_KEY) {
        # 没有 key 不拦启动：控制台的「模型」页可以给供应商填 key，密钥进本机
        # 加密密钥库，比环境变量更好管。这里只提示，不退出。
        Write-Host "[i] 没取到模型 key：控制台照常启动，进去后到「模型」页填即可。" -ForegroundColor Yellow
    }
    try {
        $models = Invoke-RestMethod "$gateway/models" -Headers @{ Authorization = "Bearer $env:SPIRITSCOUT_LOCAL_LLM_KEY" } -TimeoutSec 5
        Write-Host "[+] 本机网关可用，模型 $(@($models.data).Count) 个：$((($models.data | Select-Object -First 3).id) -join ', ')…"
    } catch {
        Write-Host "[!] 本机网关 $gateway 不可达或 key 无效：$($_.Exception.Message)" -ForegroundColor Yellow
    }
}

# 2) 执行后端：本机 host（无 bwrap 时的默认；显式写死便于审计对照）
$env:SPIRITSCOUT_SANDBOX_BACKEND = 'host'
$env:SPIRITSCOUT_EXECUTOR__SANDBOX_BACKEND = 'host'
$env:PYTHONUNBUFFERED = '1'
if ($Debug) { $env:SPIRITSCOUT_LOG_LEVEL = 'DEBUG' }

Write-Host "[+] 执行后端 host（工作目录锁定 + 运行期 ACL 收口 + 环境白名单 + 超时杀进程树；仍无读隔离）"
Write-Host "[>] 控制台：http://127.0.0.1:$Port"
Write-Host "    首次进入按提示设管理员密码；模型页应已看到 configs/models.yaml 里配置的模型。"
Push-Location (Join-Path $root 'SpiritScout')
Write-Host "[>] 前台运行中：关闭本窗口（或按 Ctrl+C）即停止控制台" -ForegroundColor Cyan
try {
    & $venvPy -X utf8 -m spiritscout --config configs\system.yaml --port $Port
} finally {
    Pop-Location
}
