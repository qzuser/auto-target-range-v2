#Requires -Version 5.1
<#
.SYNOPSIS
    打一个「单个 exe 就能跑」的单文件版：把便携版里的 Python 运行时打进 exe 尾部。

.DESCRIPTION
    便携版是「一个目录」，解压后双击里面的 exe。单文件版是「一个文件」：
    同一个桌面版 exe，尾部挂着运行时 zip（py\ + configs\，约 130 MB），
    双击后先自己把载荷倒出来解到可写目录，再照常用那份内嵌 Python 起服务。

    尾巴上的 40 字节是 [载荷长度][SHA-256 前 24 字节][SSRTPAY1]：长度定位置、哈希认完整性，

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File SpiritScout\launcher\build-single.ps1
#>
[CmdletBinding()]
param(
    [string]$PortableDir = '',
    [string]$StubExe = '',
    [string]$OutFile = '',
    [switch]$RebuildStub,
    [switch]$NoSmoke
)

$ErrorActionPreference = 'Stop'

function Write-Step([string]$Text) { Write-Host "[>] $Text" -ForegroundColor Cyan }
function Write-Ok([string]$Text) { Write-Host "[+] $Text" -ForegroundColor Green }
function Write-Warn2([string]$Text) { Write-Host "[!] $Text" -ForegroundColor Yellow }

$launcherDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent (Split-Path -Parent $launcherDir)
$versionFile = Join-Path $repoRoot 'SpiritScout\src\spiritscout\__init__.py'
$version = (Select-String -Path $versionFile -Pattern '__version__\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
Write-Step "版本 $version"

if (-not $PortableDir) {
    $candidates = Get-ChildItem (Join-Path $repoRoot 'dist-portable') -Directory -Filter '灵枢便携版-*' -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending
    if (-not $candidates) {
        throw "没有便携版目录。先跑：powershell -ExecutionPolicy Bypass -File SpiritScout\launcher\build-portable.ps1"
    }
    $PortableDir = $candidates[0].FullName
}
if (-not (Test-Path (Join-Path $PortableDir 'py\python.exe'))) {
    throw "这不是便携版目录（没有 py\python.exe）：$PortableDir"
}
$pyMb = [math]::Round(((Get-ChildItem (Join-Path $PortableDir 'py') -Recurse -File | Measure-Object Length -Sum).Sum / 1MB), 1)
Write-Step "运行时来源：$PortableDir（py\ 约 $pyMb MB）"

# ---------- 1. 桩 exe ----------

if (-not $StubExe) { $StubExe = Join-Path $repoRoot '灵枢桌面版.exe' }
if ($RebuildStub -or -not (Test-Path $StubExe)) {
    Write-Step '编桌面版桩程序'
    & (Join-Path $launcherDir 'build-desktop.ps1') -SkipDownload | Out-Host
}
if (-not (Test-Path $StubExe)) { throw "没有桩 exe：$StubExe" }
$stubBytes = [System.IO.File]::ReadAllBytes($StubExe)
Write-Ok ("桩 exe：" + (Split-Path $StubExe -Leaf) + "（" + [math]::Round($stubBytes.Length / 1KB) + " KB）")

# ---------- 2. 运行时 zip ----------

$work = Join-Path $repoRoot 'dist-single'
New-Item -ItemType Directory -Force -Path $work | Out-Null
$zip = Join-Path $work 'runtime.zip'
if (Test-Path $zip) { Remove-Item $zip -Force }

Write-Step '压运行时（py\ + configs\），这一步几分钟'
$tar = Join-Path $env:SystemRoot 'System32\tar.exe'
$zipped = $false
if (Test-Path $tar) {
    Push-Location $PortableDir
    try {
        & $tar '-a' '-cf' $zip 'py' 'configs'
        $zipped = ($LASTEXITCODE -eq 0) -and (Test-Path $zip)
    }
    finally { Pop-Location }
}
if (-not $zipped) {
    Write-Warn2 'tar.exe 打不了，退到 Compress-Archive（慢一些）'
    Compress-Archive -Path (Join-Path $PortableDir 'py'), (Join-Path $PortableDir 'configs') -DestinationPath $zip -CompressionLevel Optimal
}
$zipLen = (Get-Item $zip).Length
Write-Ok ("runtime.zip：" + [math]::Round($zipLen / 1MB, 1) + ' MB')

# ---------- 3. 拼成一个 exe ----------

if (-not $OutFile) {
    $OutFile = Join-Path $repoRoot ("dist\spiritscout-$version-single-win64.exe")
}
$outDir = Split-Path $OutFile -Parent
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

Write-Step '拼载荷：桩 exe + runtime.zip + 40 字节尾标（长度 + SHA-256 前 24 字节 + 标记）'
$payload = [System.IO.File]::ReadAllBytes($zip)
$sha = [System.Security.Cryptography.SHA256]::Create()
try { $digest = $sha.ComputeHash($payload) } finally { $sha.Dispose() }
$trailer = New-Object byte[] 40
[Array]::Copy([BitConverter]::GetBytes([int64]$zipLen), 0, $trailer, 0, 8)
[Array]::Copy($digest, 0, $trailer, 8, 24)
[System.Text.Encoding]::ASCII.GetBytes('SSRTPAY1').CopyTo($trailer, 32)

$target = [System.IO.File]::Create($OutFile)
try {
    $target.Write($stubBytes, 0, $stubBytes.Length)
    $target.Write($payload, 0, $payload.Length)
    $target.Write($trailer, 0, $trailer.Length)
}
finally { $target.Close() }

# ---------- 4. 校验 ----------

$expect = $stubBytes.Length + $zipLen + 40
$actual = (Get-Item $OutFile).Length
if ($actual -ne $expect) { throw "大小不对：期望 $expect，实际 $actual" }

$fs = [System.IO.File]::OpenRead($OutFile)
try {
    $fs.Seek(-40, [System.IO.SeekOrigin]::End) | Out-Null
    $tail = New-Object byte[] 40
    [void]$fs.Read($tail, 0, 40)
}
finally { $fs.Close() }
$tailLen = [BitConverter]::ToInt64($tail, 0)
$tailMagic = [System.Text.Encoding]::ASCII.GetString($tail, 32, 8)
if ($tailLen -ne $zipLen) { throw "尾标长度不对：$tailLen ≠ $zipLen" }
if ($tailMagic -ne 'SSRTPAY1') { throw "尾标标记不对：$tailMagic" }
$tailHash = ($tail[8..31] | ForEach-Object { $_.ToString('x2') }) -join ''
$payloadHash = (($digest[0..23]) | ForEach-Object { $_.ToString('x2') }) -join ''
if ($tailHash -ne $payloadHash) { throw "尾标哈希不对：$tailHash ≠ $payloadHash" }
Write-Ok ("单文件版：" + $OutFile)
Write-Ok ("  总大小 " + [math]::Round($actual / 1MB, 1) + " MB = 桩 " + [math]::Round($stubBytes.Length / 1KB) + " KB + 运行时 " + [math]::Round($zipLen / 1MB, 1) + " MB + 40 字节尾标")
Write-Ok ("  自校验：尾标长度、哈希、标记都对得上")

# ---------- 5. 冒烟：从别处启动，确认它会自己解 ----------

if (-not $NoSmoke) {
    Write-Step '冒烟：拷到一个空目录启动，看它自己解运行时'
    $sandbox = Join-Path $env:TEMP ('灵枢单文件冒烟-' + [guid]::NewGuid().ToString('N').Substring(0, 6))
    New-Item -ItemType Directory -Force -Path $sandbox | Out-Null
    $copy = Join-Path $sandbox '灵枢.exe'
    Copy-Item $OutFile $copy
    Get-Process -Name '灵枢' -ErrorAction SilentlyContinue | Stop-Process -Force

    $proc = Start-Process -FilePath $copy -WorkingDirectory $sandbox -PassThru
    # 日志会从「exe 所在目录」搬到「解出来的运行时目录」，两处都得看，否则会一直等不到
    $ready = $false
    for ($i = 0; $i -lt 180; $i++) {
        Start-Sleep -Seconds 1
        $logs = @()
        $logs += Get-ChildItem $sandbox -Recurse -Filter 'desktop-*.log' -ErrorAction SilentlyContinue
        $logs += Get-ChildItem (Join-Path $env:LOCALAPPDATA 'SpiritScout\runtime') -Recurse -Filter 'desktop-*.log' -ErrorAction SilentlyContinue
        foreach ($l in $logs) {
            $text = Get-Content $l.FullName -Raw -Encoding utf8
            if ($text -match '内嵌运行时可用') { $ready = $true; break }
        }
        if ($ready) { break }
        if ($proc.HasExited) { break }
    }
    Get-Process -Id $proc.Id -ErrorAction SilentlyContinue | ForEach-Object { taskkill /pid $_.Id /t /f 2>&1 | Out-Null }
    foreach ($l in (Get-ChildItem (Join-Path $env:LOCALAPPDATA 'SpiritScout\runtime') -Recurse -Filter 'desktop-*.log' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1)) {
        Get-Content $l.FullName -Encoding utf8 | Select-Object -Last 8 | Out-Host
    }
    if (-not $ready) { throw "冒烟没过：单文件版没能自己解出运行时并跑起来" }
    Write-Ok '冒烟通过：单文件版首次启动自己解出了运行时'
    Remove-Item $sandbox -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host ''
Write-Host '把这一个 exe 拷到任何 Windows 机器上双击即可，不需要 Python、不需要源码。' -ForegroundColor Green
Write-Host '首次启动会先解出约 320 MB 运行时（放在 %LOCALAPPDATA%\SpiritScout\runtime），之后启动就直接开。' -ForegroundColor Green
