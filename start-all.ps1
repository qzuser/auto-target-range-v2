# ============================================================
#  灵枢一键启动：推理服务 + 控制台 + 浏览器
#  双击 start-all.cmd 或直接跑本脚本。每一步失败都会说清卡在哪。
#
#  用法：
#    powershell -ExecutionPolicy Bypass -File .\start-all.ps1
#    .\start-all.ps1 -SkipBrowser -Port 8010
#    .\start-all.ps1 -Reload          # 强制重载模型
# ============================================================
param(
    [int]$Port = 8010,
    [int]$LlmPort = 1234,
    [string]$Model = 'qwen3.5-9b',
    [int]$ContextLength = 16384,
    [switch]$SkipBrowser,
    [switch]$Reload,
    [switch]$Quiet
)

$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }
$OutputEncoding = [Text.Encoding]::UTF8

$Root     = Split-Path -Parent $MyInvocation.MyCommand.Path
$App      = Join-Path $Root 'SpiritScout'
$Py       = Join-Path $App '.venv\Scripts\python.exe'
$WorkDir  = Join-Path $Root '_work'
$Lms      = Join-Path $env:USERPROFILE '.lmstudio\bin\lms.exe'
$LockFile = Join-Path $env:USERPROFILE '.lmstudio\.internal\llmster-pid.lock'
$LMHome   = Join-Path $env:USERPROFILE '.lmstudio\extensions\backends'
$BK       = Join-Path $LMHome 'llama.cpp-win-x86_64-nvidia-cuda12-avx2-2.64.0'
$Vendor   = Join-Path $LMHome 'vendor\win-llama-cuda12-vendor-v2'
$GGUF     = Join-Path $env:USERPROFILE '.lmstudio\models\lmstudio-community\Qwen3.5-9B-GGUF\Qwen3.5-9B-Q4_K_M.gguf'
$LlmLog   = Join-Path $WorkDir 'llama-server.log'

function Say($msg, $color = 'Gray') { if (-not $Quiet) { Write-Host "  $msg" -ForegroundColor $color } }
function Head($msg) { if (-not $Quiet) { Write-Host ''; Write-Host $msg -ForegroundColor Cyan } }
function LlmApi { try { Invoke-RestMethod "http://127.0.0.1:$LlmPort/v1/models" -TimeoutSec 4 *> $null; return $true } catch { return $false } }
function AppApi { try { Invoke-RestMethod "http://127.0.0.1:$Port/api/sessions" -TimeoutSec 4 *> $null; return $true } catch { return $false } }
function WaitFor([scriptblock]$check, [int]$tries) {
    for ($i = 0; $i -lt $tries; $i++) {
        Start-Sleep -Seconds 2
        if (& $check) { return $true }
    }
    return $false
}

Write-Host ''
Write-Host '=============================================' -ForegroundColor Cyan
Write-Host '   灵枢 SpiritScout · 一键启动' -ForegroundColor Cyan
Write-Host '=============================================' -ForegroundColor Cyan

# ── 0. 环境自检 ──────────────────────────────────────────────
Head '[0/4] 环境自检'
if (-not (Test-Path $Py)) {
    Write-Host "  [x] 找不到虚拟环境: $Py" -ForegroundColor Red
    Write-Host '      建环境: py -3.11 -m venv SpiritScout\.venv' -ForegroundColor Yellow
    Write-Host '      装依赖: powershell -ExecutionPolicy Bypass -File .\start-local.ps1' -ForegroundColor Yellow
    Read-Host '按回车退出'
    exit 1
}
if (-not (Test-Path $WorkDir)) { New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null }
Say 'Python 虚拟环境 OK'

# ── 1. 推理服务 ──────────────────────────────────────────────
Head "[1/4] 推理服务（端口 $LlmPort）"
$llmMode = 'none'

if ((LlmApi) -and (-not $Reload)) {
    Say '已在运行，复用' Green
    $llmMode = 'running'
}

if ($llmMode -eq 'none') {
    # 1a. 清 LM Studio 死锁（PID 早已不存在的锁文件会让 daemon 永远等下去）
    if (Test-Path $LockFile) {
        $stalePid = (Get-Content $LockFile -Raw -ErrorAction SilentlyContinue).Trim()
        $alive = $false
        if ($stalePid) { $alive = [bool](Get-Process -Id $stalePid -ErrorAction SilentlyContinue) }
        if (-not $alive) {
            Remove-Item $LockFile -Force -ErrorAction SilentlyContinue
            Say "清掉死锁文件 llmster-pid.lock（PID $stalePid 已不存在）" Yellow
        }
    }

    # 1b. 试 LM Studio
    if (Test-Path $Lms) {
        Say '尝试 LM Studio ...'
        & $Lms server start *> $null
        $ok = WaitFor { LlmApi } 8
        if ($ok) {
            & $Lms load $Model --context-length $ContextLength --parallel 1 --gpu max *> $null
            $ok = WaitFor { LlmApi } 12
            if ($ok) { $llmMode = 'lmstudio'; Say 'LM Studio 就绪' Green }
        }
        if ($llmMode -eq 'none') { Say 'LM Studio 起不来，改用 llama-server 兜底' Yellow }
    }

    # 1c. 兜底 llama-server：必须在后端目录跑，否则缺 DLL
    if ($llmMode -eq 'none') {
        $srv = Join-Path $BK 'llama-server.exe'
        if (-not (Test-Path $srv)) {
            Write-Host "  [x] 找不到 llama-server: $srv" -ForegroundColor Red
            Write-Host '      装 LM Studio 会自带；或改脚本顶部 $BK 指向你的 llama.cpp' -ForegroundColor Yellow
            Read-Host '按回车退出'
            exit 1
        }
        if (-not (Test-Path $GGUF)) {
            Write-Host "  [x] 找不到模型文件: $GGUF" -ForegroundColor Red
            Read-Host '按回车退出'
            exit 1
        }
        Get-CimInstance Win32_Process -Filter "Name='llama-server.exe'" -ErrorAction SilentlyContinue |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Start-Sleep -Seconds 2
        $env:PATH = $BK + ';' + $Vendor + ';' + $env:PATH
        $argList = @('-m', $GGUF, '-a', $Model, '-c', "$ContextLength", '-ngl', '99',
                     '--host', '127.0.0.1', '--port', "$LlmPort", '-np', '1',
                     '--reasoning-budget', '0')
        Start-Process -FilePath $srv -ArgumentList $argList -WorkingDirectory $BK -WindowStyle Minimized
        $ok = WaitFor { LlmApi } 20
        if ($ok) {
            $llmMode = 'llama-server'
            Say "llama-server 就绪（日志 $LlmLog）" Green
        } else {
            Write-Host '  [x] 兜底也没起来' -ForegroundColor Red
            Write-Host "      看 %USERPROFILE%\.lmstudio\server-logs 下的最新日志" -ForegroundColor Yellow
            Read-Host '按回车退出'
            exit 1
        }
    }
}

# 模型自检：先看列表，再真跑一次——端口通但请求不返回（假死）时列表照样读得到
try {
    $ids = (Invoke-RestMethod "http://127.0.0.1:$LlmPort/v1/models" -TimeoutSec 6).data | ForEach-Object { $_.id }
    if ($ids -contains $Model) { Say "模型 $Model 在列" Green }
    else { Say "服务里是 [$($ids -join ', ')]，没有 $Model —— 改 configs\models.yaml" Yellow }

    $probe = @{ model = $Model; messages = @(@{ role = 'user'; content = 'ping' }); max_tokens = 4; stream = $false } | ConvertTo-Json -Depth 5
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $null = Invoke-RestMethod "http://127.0.0.1:$LlmPort/v1/chat/completions" -Method Post `
        -ContentType 'application/json' -Body $probe -TimeoutSec 45
    $sw.Stop()
    Say "推理自检通过（$([math]::Round($sw.Elapsed.TotalSeconds,1))s）" Green
} catch {
    Write-Host "  [x] 推理自检失败：模型列表读得到但请求不返回，端点多半假死了" -ForegroundColor Red
    Write-Host "      处理：先跑 stop-all.ps1，再跑本脚本重载模型" -ForegroundColor Yellow
    if (-not $Quiet) { Write-Host "      详情：$($_.Exception.Message)" -ForegroundColor DarkGray }
}

# ── 2. 控制台 ────────────────────────────────────────────────
Head "[2/4] 控制台（端口 $Port）"
if (AppApi) {
    Say '已在运行，复用' Green
} else {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match '-m spiritscout' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
    $launcher = Join-Path $Root 'run-spiritscout.ps1'
    Start-Process powershell -ArgumentList '-ExecutionPolicy', 'Bypass', '-File', $launcher -WindowStyle Minimized
    $ok = WaitFor { AppApi } 20
    if ($ok) { Say '控制台就绪' Green }
    else {
        Write-Host "  [x] 控制台没起来，看 $(Join-Path $WorkDir 'agent-server.log')" -ForegroundColor Red
        Read-Host '按回车退出'
        exit 1
    }
}

# ── 3. MCP 自检 ──────────────────────────────────────────────
Head '[3/4] MCP 服务'
$cfgPath = Join-Path $App 'configs\system.yaml'
$mcpPy = @(
    'import yaml, pathlib, shutil, sys',
    'cfg = pathlib.Path(sys.argv[1])',
    "d = yaml.safe_load(cfg.read_text(encoding='utf-8')) or {}",
    "for s in (d.get('mcp_servers') or []):",
    "    name = s.get('name')",
    "    if not s.get('enabled', True):",
    "        print('  ' + str(name) + '  已关闭'); continue",
    "    cmd = str(s.get('command') or '').split()",
    "    exe = cmd[0] if cmd else ''",
    "    ok = bool(shutil.which(exe)) or pathlib.Path(exe).exists()",
    "    print('  ' + str(name) + ('  可用' if ok else '  不可用（缺 ' + exe + '）'))"
)
$mcpFile = Join-Path $WorkDir '_mcp_check.py'
[IO.File]::WriteAllLines($mcpFile, $mcpPy, [Text.UTF8Encoding]::new($false))
& $Py -X utf8 $mcpFile $cfgPath 2>$null | ForEach-Object { if (-not $Quiet) { Write-Host $_ -ForegroundColor Gray } }
Remove-Item $mcpFile -Force -ErrorAction SilentlyContinue
Say '（MCP 由灵枢按配置自己拉起；不可用的会跳过，不影响解题）'

# ── 4. 浏览器 ────────────────────────────────────────────────
Head '[4/4] 打开控制台'
$url = 'http://127.0.0.1:' + $Port
if (-not $SkipBrowser) { Start-Process $url }

Write-Host ''
Write-Host '=============================================' -ForegroundColor Green
Write-Host "  就绪: $url" -ForegroundColor Green
Write-Host "  推理: $llmMode @ 127.0.0.1:$LlmPort ($Model, $ContextLength 上下文)" -ForegroundColor Green
Write-Host '  停止: powershell -ExecutionPolicy Bypass -File .\stop-all.ps1' -ForegroundColor Green
Write-Host '=============================================' -ForegroundColor Green
Write-Host ''
Say '浏览器里: 选模式 → 填题目 → 贴附件 → 下发'
Say '关掉本窗口不会停服务；要停请用 stop-all.ps1'
