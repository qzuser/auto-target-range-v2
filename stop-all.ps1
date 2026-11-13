# ============================================================
#  灵枢一键停止：控制台 + 推理服务 + 承载它们的窗口
#  用法：powershell -ExecutionPolicy Bypass -File .\stop-all.ps1
#        .\stop-all.ps1 -KeepLlm     # 只停控制台，留着模型
# ============================================================
param(
    [int]$Port = 8010,
    [int]$LlmPort = 1234,
    [switch]$KeepLlm,
    [switch]$Quiet
)

$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }

function Say($msg, $color = 'Gray') { if (-not $Quiet) { Write-Host "  $msg" -ForegroundColor $color } }
function Head($msg) { if (-not $Quiet) { Write-Host ''; Write-Host $msg -ForegroundColor Cyan } }

Write-Host ''
Write-Host '=============================================' -ForegroundColor Cyan
Write-Host '   灵枢 SpiritScout · 停止' -ForegroundColor Cyan
Write-Host '=============================================' -ForegroundColor Cyan

# ── 1. 控制台 ────────────────────────────────────────────────
Head "[1/3] 控制台（端口 $Port）"
$conn = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
if ($conn) {
    $svcPid = $conn.OwningProcess
    # 顺着父链找承载它的 PowerShell（只认命令行里带本项目脚本的）
    $shellPid = $null
    $cur = $svcPid
    for ($i = 0; $i -lt 4 -and $cur; $i++) {
        $ci = Get-CimInstance Win32_Process -Filter "ProcessId=$cur" -ErrorAction SilentlyContinue
        if (-not $ci) { break }
        if ($ci.Name -eq 'powershell.exe' -and $ci.CommandLine -match 'run-spiritscout|start-all') {
            $shellPid = $ci.ProcessId
            break
        }
        $cur = $ci.ParentProcessId
    }
    Get-CimInstance Win32_Process -Filter "ParentProcessId=$svcPid" -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Stop-Process -Id $svcPid -Force -ErrorAction SilentlyContinue
    Say "已结束服务进程 $svcPid"
    if ($shellPid) {
        Stop-Process -Id $shellPid -Force -ErrorAction SilentlyContinue
        Say "已关闭控制台窗口 $shellPid"
    }
} else {
    Say '端口没有服务在跑'
}

# 兜底：清掉没有 python 子进程的项目窗口空壳
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
    Where-Object {
        $_.CommandLine -match 'run-spiritscout\.ps1' -and
        $_.CommandLine -notmatch 'stop-all' -and
        $_.ProcessId -ne $PID -and
        -not (Get-CimInstance Win32_Process -Filter "ParentProcessId=$($_.ProcessId)" -ErrorAction SilentlyContinue |
              Where-Object { $_.Name -eq 'python.exe' })
    } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        Say "清理残留窗口 $($_.ProcessId)"
    }

# ── 2. 推理服务 ──────────────────────────────────────────────
Head "[2/3] 推理服务（端口 $LlmPort）"
if ($KeepLlm) {
    Say '按 -KeepLlm 保留推理服务' Yellow
} elseif (Get-NetTCPConnection -State Listen -LocalPort $LlmPort -ErrorAction SilentlyContinue) {
    $lm = Get-CimInstance Win32_Process -Filter "Name='llama-server.exe'" -ErrorAction SilentlyContinue
    if ($lm) {
        $lm | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Say "已停 llama-server（$($lm.Count) 个进程）"
    } else {
        $lms = Join-Path $env:USERPROFILE '.lmstudio\bin\lms.exe'
        if (Test-Path $lms) {
            & $lms unload --all *> $null
            Say '已卸载 LM Studio 里的模型（服务本身保持）'
        }
    }
} else {
    Say '推理服务没在跑'
}

# ── 3. 显存 ──────────────────────────────────────────────────
Head '[3/3] 显存'
try {
    $vram = & nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader 2>$null
    if ($vram) { Say "当前占用: $vram" }
} catch { }

Write-Host ''
Write-Host '=============================================' -ForegroundColor Green
Write-Host '  已停止。重新开始请跑 start-all.ps1' -ForegroundColor Green
Write-Host '=============================================' -ForegroundColor Green
Write-Host ''
