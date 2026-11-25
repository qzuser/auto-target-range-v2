#Requires -Version 7.0
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$AppDir,
    [int]$TimeoutSeconds = 90
)

$ErrorActionPreference = 'Stop'

function Get-DescendantProcessIds {
    param([int]$RootId)

    $known = [System.Collections.Generic.HashSet[int]]::new()
    $queue = [System.Collections.Generic.Queue[int]]::new()
    [void]$queue.Enqueue($RootId)
    while ($queue.Count -gt 0) {
        $parent = $queue.Dequeue()
        $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$parent" -ErrorAction SilentlyContinue
        foreach ($child in $children) {
            $childId = [int]$child.ProcessId
            if ($known.Add($childId)) {
                [void]$queue.Enqueue($childId)
            }
        }
    }
    return @($known)
}

function Read-NewLogText {
    param(
        [string]$Path,
        [long]$Offset
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return ''
    }
    $stream = [System.IO.File]::Open(
        $Path,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::ReadWrite
    )
    try {
        if ($Offset -gt $stream.Length) {
            $Offset = 0
        }
        [void]$stream.Seek($Offset, [System.IO.SeekOrigin]::Begin)
        $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8, $false, 4096, $true)
        try {
            return $reader.ReadToEnd()
        }
        finally {
            $reader.Dispose()
        }
    }
    finally {
        $stream.Dispose()
    }
}

$appDirPath = (Resolve-Path -LiteralPath $AppDir).Path
$exePath = Join-Path $appDirPath 'SpiritScout.exe'
if (-not (Test-Path -LiteralPath $exePath)) {
    throw "SpiritScout.exe not found: $exePath"
}

$logRoot = Join-Path ($env:LOCALAPPDATA ?? $env:TEMP) 'SpiritScout\desktop-logs'
$logPath = Join-Path $logRoot ('desktop-' + (Get-Date -Format 'yyyy-MM-dd') + '.log')
$logOffset = if (Test-Path -LiteralPath $logPath) {
    (Get-Item -LiteralPath $logPath).Length
} else {
    0L
}

$launchedAt = Get-Date
Write-Host "[smoke] launching $exePath"
$startInfo = [System.Diagnostics.ProcessStartInfo]::new()
$startInfo.FileName = $exePath
$startInfo.WorkingDirectory = $appDirPath
$startInfo.UseShellExecute = $false
$startInfo.CreateNoWindow = $true
$startInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
$process = [System.Diagnostics.Process]::Start($startInfo)
if ($null -eq $process) {
    throw "Failed to start SpiritScout.exe"
}
Write-Host "[smoke] desktop pid=$($process.Id); waiting for backend log"
$port = $null
$backendIds = @()
$response = $null
$failure = $null

try {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $logText = ''
    $lastProgress = Get-Date
    while ((Get-Date) -lt $deadline) {
        if ($process.HasExited) {
            throw "Desktop process exited before backend readiness (exit=$($process.ExitCode))."
        }
        $logText = Read-NewLogText -Path $logPath -Offset $logOffset
        $matches = [regex]::Matches($logText, 'http://127\.0\.0\.1:(\d+)')
        if ($matches.Count -gt 0) {
            $candidatePort = [int]$matches[$matches.Count - 1].Groups[1].Value
            try {
                $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 `
                    -Uri "http://127.0.0.1:$candidatePort/login"
                if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) {
                    $port = $candidatePort
                    break
                }
            }
            catch {
                $response = $null
            }
        }
        if (((Get-Date) - $lastProgress).TotalSeconds -ge 10) {
            Write-Host "[smoke] still waiting; desktop_exited=$($process.HasExited)"
            $lastProgress = Get-Date
        }
        Start-Sleep -Milliseconds 750
    }

    if (-not $port) {
        throw "Backend did not become HTTP-ready within $TimeoutSeconds seconds."
    }

    $backendIds = @(Get-DescendantProcessIds -RootId $process.Id)
    if ($backendIds.Count -eq 0) {
        throw "Desktop did not expose a backend process."
    }
    if ($logText -match 'No supported WebSocket library detected') {
        throw "Backend started without a supported WebSocket library."
    }
    if ($logText -match 'Unsupported upgrade request') {
        throw "Backend reported an unsupported WebSocket upgrade request."
    }
    Write-Host "[smoke] backend ready on port $port; backend_pids=$($backendIds -join ',')"
}
catch {
    $failure = $_.Exception.Message
}
finally {
    Write-Host "[smoke] closing desktop"
    if (-not $process.HasExited) {
        $graceful = $process.CloseMainWindow()
        if (-not $graceful) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
    }
    $exitDeadline = (Get-Date).AddSeconds(25)
    while ((Get-Date) -lt $exitDeadline) {
        $live = @($backendIds | Where-Object {
            Get-Process -Id $_ -ErrorAction SilentlyContinue
        })
        if ($process.HasExited -and $live.Count -eq 0) {
            break
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $process.HasExited) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }
    $remaining = @($backendIds | Where-Object {
        Get-Process -Id $_ -ErrorAction SilentlyContinue
    })
    if ($remaining.Count -gt 0) {
        $failure = (($failure, "Backend descendants still alive after desktop exit: $($remaining -join ', ')") |
            Where-Object { $_ }) -join '; '
        Stop-Process -Id $remaining -Force -ErrorAction SilentlyContinue
    }
    Write-Host "[smoke] cleanup complete; remaining_backend_pids=$($remaining -join ',')"
}

$result = [pscustomobject]@{
    DesktopPid = $process.Id
    BackendPids = $backendIds -join ','
    Port = $port
    HttpStatus = $response.StatusCode
    DesktopExited = $process.HasExited
    BackendReleased = $remaining.Count -eq 0
    DurationSeconds = [Math]::Round(((Get-Date) - $launchedAt).TotalSeconds, 2)
}
$result | Format-List

if ($failure) {
    throw $failure
}
