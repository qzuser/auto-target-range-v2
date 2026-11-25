#Requires -Version 5.1
<#
.SYNOPSIS
    Build the Windows traffic recording proxy used by the desktop release.

.DESCRIPTION
    The desktop distribution bundles this executable so end users do not need
    Go installed. Source builds use an existing go.exe when available; otherwise
    the script downloads a pinned portable Go toolchain into the local build
    cache. Aliyun is tried first, with the official Go download as fallback.
#>
[CmdletBinding()]
param(
    [string]$OutputDir = '',
    [string]$GoExe = '',
    [string]$GoVersion = '1.26.3'
)

$ErrorActionPreference = 'Stop'

function Write-Step([string]$Text) { Write-Host "[>] $Text" -ForegroundColor Cyan }
function Write-Ok([string]$Text) { Write-Host "[+] $Text" -ForegroundColor Green }

function Invoke-Download([string]$Url, [string]$Destination) {
    $partial = "$Destination.download"
    if (Test-Path -LiteralPath $partial) {
        Remove-Item -LiteralPath $partial -Force
    }
    try {
        if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
            & curl.exe -L --fail --retry 3 --retry-delay 2 --connect-timeout 20 --max-time 900 `
                --output $partial $Url
            if ($LASTEXITCODE -ne 0) {
                return $false
            }
        } else {
            $ProgressPreference = 'SilentlyContinue'
            Invoke-WebRequest -Uri $Url -OutFile $partial -UseBasicParsing -TimeoutSec 900
        }
        Move-Item -LiteralPath $partial -Destination $Destination -Force
        return $true
    } catch {
        if (Test-Path -LiteralPath $partial) {
            Remove-Item -LiteralPath $partial -Force
        }
        return $false
    }
}

$packagingDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent (Split-Path -Parent $packagingDir)
$proxySource = Join-Path $repoRoot 'traffic-proxy'
if (-not (Test-Path -LiteralPath (Join-Path $proxySource 'go.mod'))) {
    throw "找不到流量代理源码：$proxySource"
}

if (-not $OutputDir) {
    $OutputDir = Join-Path $repoRoot 'build\tools'
}
$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$output = Join-Path $OutputDir 'spiritscout-traffic-proxy.exe'

if (-not $GoExe) {
    $installedGo = Get-Command go.exe -ErrorAction SilentlyContinue
    if ($installedGo) {
        $GoExe = $installedGo.Source
    }
}

$downloadCache = Join-Path $repoRoot 'build\download-cache\go'
$portableRoot = Join-Path $downloadCache "go$GoVersion"
$portableGo = Join-Path $portableRoot 'go\bin\go.exe'
if (-not $GoExe -and (Test-Path -LiteralPath $portableGo)) {
    $GoExe = $portableGo
}

if (-not $GoExe) {
    New-Item -ItemType Directory -Force -Path $downloadCache | Out-Null
    $archive = Join-Path $downloadCache "go$GoVersion.windows-amd64.zip"
    if (-not (Test-Path -LiteralPath $archive)) {
        Write-Step "下载便携 Go $GoVersion（阿里云优先）"
        $urls = @(
            "https://mirrors.aliyun.com/golang/go$GoVersion.windows-amd64.zip",
            "https://go.dev/dl/go$GoVersion.windows-amd64.zip"
        )
        $downloaded = $false
        foreach ($url in $urls) {
            if (Invoke-Download $url $archive) {
                $downloaded = $true
                break
            }
            Write-Host "[!] 下载失败，尝试下一个源：$url" -ForegroundColor Yellow
        }
        if (-not $downloaded) {
            throw "无法下载 Go $GoVersion。"
        }
    }

    if (-not (Test-Path -LiteralPath $portableGo)) {
        Write-Step "展开便携 Go $GoVersion"
        New-Item -ItemType Directory -Force -Path $portableRoot | Out-Null
        Expand-Archive -LiteralPath $archive -DestinationPath $portableRoot -Force
    }
    if (-not (Test-Path -LiteralPath $portableGo)) {
        throw "便携 Go 不完整：$portableGo"
    }
    $GoExe = $portableGo
}

$GoExe = (Resolve-Path -LiteralPath $GoExe).Path
$env:GOTOOLCHAIN = 'local'
$env:GOOS = 'windows'
$env:GOARCH = 'amd64'
$env:CGO_ENABLED = '0'
$env:GOPROXY = 'https://goproxy.cn,https://proxy.golang.com.cn,direct'
$env:GOSUMDB = 'sum.golang.google.cn'

Write-Step "编译 Windows 流量录制代理：$GoExe"
Push-Location $proxySource
try {
    & $GoExe build -trimpath -buildvcs=false -ldflags '-s -w' -o $output .
    if ($LASTEXITCODE -ne 0) {
        throw "Go 构建失败（退出码 $LASTEXITCODE）"
    }
} finally {
    Pop-Location
}

if (-not (Test-Path -LiteralPath $output)) {
    throw "流量代理没有生成：$output"
}

$sizeMb = [Math]::Round(((Get-Item -LiteralPath $output).Length / 1MB), 2)
Write-Ok "流量代理：$output（$sizeMb MB）"
