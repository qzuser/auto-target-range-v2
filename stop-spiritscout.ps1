# ============================================================
#  停止灵枢控制台：kill 服务进程 + 关掉承载它的 PowerShell 窗口
#  绿色 = 只关本项目脚本窗口，不碰你自己开的终端
# ============================================================
param(
    [int]$Port = 8010,
    [switch]$Quiet
)

$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }

function Say($m) { if (-not $Quiet) { Write-Host "  $m" } }

# 1. 监听该端口的 python（服务本体）
$conn = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
$svcPid = $null
if ($conn) {
    $svcPid = $conn.OwningProcess
    Say "控制台服务: PID $svcPid（端口 $Port）"
} else {
    Say "端口 $Port 没有服务在跑"
}

# 2. 顺着父链找承载它的 PowerShell 窗口（脚本是 powershell -> python）
$shellPid = $null
if ($svcPid) {
    $chain = @()
    $cur = $svcPid
    for ($i = 0; $i -lt 4 -and $cur; $i++) {
        $ci = Get-CimInstance Win32_Process -Filter "ProcessId=$cur" -ErrorAction SilentlyContinue
        if (-not $ci) { break }
        $chain += [pscustomobject]@{ PID = $ci.ProcessId; Name = $ci.Name; Cmd = $ci.CommandLine }
        $cur = $ci.ParentProcessId
    }
    # 只认「命令行里带本项目脚本」的 powershell，避免误杀用户自己的终端
    $shell = $chain | Where-Object {
        $_.Name -eq 'powershell.exe' -and
        $_.Cmd -match 'run-spiritscout|run-offline|run-model'
    } | Select-Object -First 1
    if ($shell) { $shellPid = $shell.PID }
}

# 3. 先杀服务进程（连带子进程）
if ($svcPid) {
    Get-CimInstance Win32_Process -Filter "ParentProcessId=$svcPid" -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Stop-Process -Id $svcPid -Force -ErrorAction SilentlyContinue
    Say "已结束服务进程 $svcPid"
}

# 4. 再关窗口：脚本已退出但 -NoExit 会让窗口留成空壳，这里收掉
if ($shellPid) {
    $p = Get-Process -Id $shellPid -ErrorAction SilentlyContinue
    if ($p) {
        $had = $p.MainWindowHandle -ne 0
        Stop-Process -Id $shellPid -Force -ErrorAction SilentlyContinue
        Say "已关闭控制台窗口（PID $shellPid）" + $(if ($had) { "" } else { "（本来无窗口）" })
    }
} else {
    Say "没有找到本项目的 PowerShell 窗口"
}

# 5. 兜底：清掉残留的、命令行指向本项目**启动脚本**的无窗口 shell 空壳
#    必须排除自身（stop-spiritscout.ps1），否则把执行这条命令的 shell 也一起收了
$stale = Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
    Where-Object {
        $_.CommandLine -match 'run-spiritscout\.ps1|run-offline\.ps1' -and
        $_.CommandLine -notmatch 'stop-spiritscout\.ps1' -and
        $_.ProcessId -ne $PID -and
        -not (Get-CimInstance Win32_Process -Filter "ParentProcessId=$($_.ProcessId)" -ErrorAction SilentlyContinue |
              Where-Object { $_.Name -eq 'python.exe' })
    }
foreach ($s in $stale) {
    Stop-Process -Id $s.ProcessId -Force -ErrorAction SilentlyContinue
    Say "清理残留窗口壳 PID $($s.ProcessId)"
}

if (-not $Quiet) { Write-Host "" ; Write-Host "完成。" -ForegroundColor Green }
