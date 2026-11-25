#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$RuntimeDir = '',
    [string]$OutputDir = '',
    [string]$Wheel = '',
    [string]$TrafficProxy = ''
)

$ErrorActionPreference = 'Stop'

function Write-Step([string]$Text) { Write-Host "[>] $Text" -ForegroundColor Cyan }
function Write-Ok([string]$Text) { Write-Host "[+] $Text" -ForegroundColor Green }

$packagingDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent (Split-Path -Parent $packagingDir)
$projectDir = Join-Path $repoRoot 'desktop'
$versionFile = Join-Path $repoRoot 'src\spiritscout\__init__.py'
$version = (Select-String -Path $versionFile -Pattern '__version__\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value

if (-not $OutputDir) {
    $OutputDir = Join-Path $repoRoot 'dist\windows\desktop'
}
$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)

if (-not $RuntimeDir) {
    $RuntimeDir = Join-Path $repoRoot 'build\backend-runtime'
    Write-Step '准备 Python 运行时'
    $runtimeScript = Join-Path $packagingDir 'build-backend-runtime.ps1'
    if ($Wheel) {
        & $runtimeScript -OutDir $RuntimeDir -Wheel $Wheel
    }
    else {
        & $runtimeScript -OutDir $RuntimeDir
    }
}
$RuntimeDir = (Resolve-Path -LiteralPath $RuntimeDir).Path
if (-not (Test-Path -LiteralPath (Join-Path $RuntimeDir 'py\python.exe'))) {
    throw "RuntimeDir 不是完整 Python 运行时：$RuntimeDir"
}
if (-not (Test-Path -LiteralPath (Join-Path $RuntimeDir 'configs\system.yaml'))) {
    throw "RuntimeDir 缺少 configs\system.yaml：$RuntimeDir"
}

$jdkHome = $env:JAVA_HOME
if (-not $jdkHome -or -not (Test-Path -LiteralPath (Join-Path $jdkHome 'bin\jpackage.exe'))) {
    $jdkHome = Get-ChildItem 'C:\Program Files\Microsoft' -Directory -Filter 'jdk-21*' -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending |
        Select-Object -First 1 -ExpandProperty FullName
}
if (-not $jdkHome -or -not (Test-Path -LiteralPath (Join-Path $jdkHome 'bin\jpackage.exe'))) {
    throw '需要 JDK 21，并确保包含 jpackage.exe。'
}
$env:JAVA_HOME = $jdkHome
$env:Path = (Join-Path $jdkHome 'bin') + ';' + $env:Path

Write-Step "版本 $version"
Write-Step '同步桌面依赖'
Push-Location $projectDir
try {
    & .\gradlew.bat stageDesktop createRuntimeImage --no-configuration-cache
    if ($LASTEXITCODE -ne 0) { throw "Gradle 失败（退出码 $LASTEXITCODE）" }
} finally {
    Pop-Location
}

if (-not $TrafficProxy) {
    $trafficScript = Join-Path $packagingDir 'build-traffic-proxy.ps1'
    & $trafficScript -OutputDir (Join-Path $repoRoot 'build\tools')
    if ($LASTEXITCODE -ne 0) { throw "流量代理构建失败（退出码 $LASTEXITCODE）" }
    $TrafficProxy = Join-Path $repoRoot 'build\tools\spiritscout-traffic-proxy.exe'
}
$TrafficProxy = (Resolve-Path -LiteralPath $TrafficProxy).Path

$mainJar = Get-ChildItem (Join-Path $projectDir "build\desktop-input") -File -Filter "SpiritScoutDesktop-$version.jar" |
    Select-Object -First 1
if (-not $mainJar) {
    throw "没有找到桌面主 JAR：SpiritScoutDesktop-$version.jar"
}

$packageRoot = Join-Path $repoRoot 'build\windows-desktop\package'
$buildRoot = Join-Path $repoRoot 'build'
New-Item -ItemType Directory -Force -Path $buildRoot | Out-Null
$allowedRoot = (Resolve-Path $buildRoot).Path
$resolvedPackageRoot = [System.IO.Path]::GetFullPath($packageRoot)
if (-not $resolvedPackageRoot.StartsWith($allowedRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "拒绝清理构建目录之外的路径：$resolvedPackageRoot"
}
if (Test-Path -LiteralPath $resolvedPackageRoot) {
    Remove-Item -LiteralPath $resolvedPackageRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $resolvedPackageRoot | Out-Null

Write-Step '生成 Windows app-image'
$jpackage = Join-Path $jdkHome 'bin\jpackage.exe'
& $jpackage `
    --type app-image `
    --name SpiritScout `
    --dest $resolvedPackageRoot `
    --input (Join-Path $projectDir 'build\desktop-input') `
    --main-jar $mainJar.Name `
    --main-class com.spiritscout.desktop.MainKt `
    --runtime-image (Join-Path $projectDir 'build\compose\tmp\main\runtime') `
    --icon (Join-Path $packagingDir 'icon.ico') `
    --app-version $version `
    --java-options '-Dfile.encoding=UTF-8' `
    --java-options '-Dsun.java2d.uiScale.enabled=true'
if ($LASTEXITCODE -ne 0) { throw "jpackage 失败（退出码 $LASTEXITCODE）" }

$appDir = Join-Path $resolvedPackageRoot 'SpiritScout'
if (-not (Test-Path -LiteralPath (Join-Path $appDir 'SpiritScout.exe'))) {
    throw "jpackage 没有生成 SpiritScout.exe：$appDir"
}

Write-Step '加入 Python 运行时与说明'
Copy-Item -LiteralPath (Join-Path $RuntimeDir 'py') -Destination (Join-Path $appDir 'py') -Recurse -Force
Copy-Item -LiteralPath (Join-Path $RuntimeDir 'configs') -Destination (Join-Path $appDir 'configs') -Recurse -Force
Copy-Item -LiteralPath (Join-Path $repoRoot 'docs\原生桌面端.md') -Destination (Join-Path $appDir 'README-Windows.md') -Force
New-Item -ItemType Directory -Force -Path (Join-Path $appDir 'tools') | Out-Null
Copy-Item -LiteralPath (Join-Path $repoRoot 'tools\experience-export') -Destination (Join-Path $appDir 'tools\experience-export') -Recurse -Force
Copy-Item -LiteralPath $TrafficProxy -Destination (Join-Path $appDir 'tools\spiritscout-traffic-proxy.exe') -Force
Get-ChildItem -LiteralPath $appDir -Recurse -Force -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force
Get-ChildItem -LiteralPath $appDir -Recurse -Force -File -Filter '*.pyc' -ErrorAction SilentlyContinue |
    Remove-Item -Force
Copy-Item -LiteralPath (Join-Path $repoRoot 'desktop\THIRD_PARTY_NOTICES.md') -Destination (Join-Path $appDir 'THIRD_PARTY_NOTICES.md') -Force
Copy-Item -LiteralPath (Join-Path $repoRoot 'desktop\THIRD_PARTY\SaltUI-LICENSE.txt') -Destination (Join-Path $appDir 'SaltUI-LICENSE.txt') -Force

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$zipPath = Join-Path $OutputDir "SpiritScout-$version-windows-x64.zip"
$tar = Join-Path $env:SystemRoot 'System32\tar.exe'
if (Test-Path -LiteralPath $tar) {
    & $tar -a -cf $zipPath -C $resolvedPackageRoot 'SpiritScout'
    if ($LASTEXITCODE -ne 0) { throw "tar 压缩失败（退出码 $LASTEXITCODE）" }
} else {
    Compress-Archive -Path $appDir -DestinationPath $zipPath -CompressionLevel Optimal -Force
}

$sizeMb = [Math]::Round(((Get-ChildItem -LiteralPath $appDir -Recurse -File | Measure-Object Length -Sum).Sum / 1MB), 1)
$zipMb = [Math]::Round(((Get-Item -LiteralPath $zipPath).Length / 1MB), 1)
Write-Ok "桌面目录：$appDir（$sizeMb MB）"
Write-Ok "发布 ZIP：$zipPath（$zipMb MB）"
