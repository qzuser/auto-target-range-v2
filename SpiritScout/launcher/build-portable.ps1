#Requires -Version 5.1
<#
.SYNOPSIS
    打一个「什么都不用装」的 Windows 便携版：内嵌 Python 运行时 + 已装好的依赖 + 桌面版 exe。

.DESCRIPTION
    桌面版 exe 本身只是壳子，真正干活的是 Python 服务。要让别人机器上双击就能用，
    就得把解释器和依赖一起带过去。这个脚本就把它们塞进同一个目录：

        灵枢便携版\
            灵枢桌面版.exe        ← 双击这个
            desktop.json          ← 告诉 exe：程序目录在哪、用哪个解释器
            py\                   ← Python 3.11 embeddable + Lib\site-packages（灵枢与依赖）
            configs\              ← system.yaml / models.yaml（模板）/ skills.yaml
            data\ workspaces\ logs\

    用的解释器是 python.org 的 embeddable 包（约 10 MB，免安装），
    它默认不吃 site-packages，脚本会把 python311._pth 补好再装依赖。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File SpiritScout\launcher\build-portable.ps1

.EXAMPLE
    # 离线：提前下好解释器包与 get-pip.py
    ... -PythonZip D:\offline\python-3.11.9-embed-amd64.zip -GetPip D:\offline\get-pip.py
#>
[CmdletBinding()]
param(
    [string]$Wheel = '',
    [string]$PythonVersion = '3.11.9',
    [string]$OutDir = '',
    [string]$PythonZip = '',
    [string]$GetPip = '',
    [string]$DesktopExe = '',
    [string]$IndexUrl = '',
    [switch]$SkipInstall,
    [switch]$NoZip
)

$ErrorActionPreference = 'Stop'

function Write-Step([string]$Text) { Write-Host "[>] $Text" -ForegroundColor Cyan }
function Write-Ok([string]$Text) { Write-Host "[+] $Text" -ForegroundColor Green }
function Write-Warn2([string]$Text) { Write-Host "[!] $Text" -ForegroundColor Yellow }

$launcherDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent (Split-Path -Parent $launcherDir)
if (-not (Test-Path (Join-Path $repoRoot 'SpiritScout\pyproject.toml'))) {
    throw "找不到仓库根（期望 $repoRoot\SpiritScout\pyproject.toml）；脚本要放在 SpiritScout\launcher\ 下跑。"
}

# 版本号只认一个地方
$versionFile = Join-Path $repoRoot 'SpiritScout\src\spiritscout\__init__.py'
$version = (Select-String -Path $versionFile -Pattern '__version__\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
Write-Step "版本 $version，仓库根 $repoRoot"

if (-not $OutDir) { $OutDir = Join-Path $repoRoot ('dist-portable\灵枢便携版-' + $version) }
if (-not $Wheel) {
    $candidates = Get-ChildItem (Join-Path $repoRoot 'dist') -Filter 'spiritscout-*.whl' -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending
    if (-not $candidates) { throw "dist\ 里没有 spiritscout-*.whl —— 先 python -m build --outdir dist SpiritScout" }
    $Wheel = $candidates[0].FullName
}
if (-not (Test-Path $Wheel)) { throw "wheel 不存在：$Wheel" }
Write-Step "wheel：$Wheel"

if (-not $DesktopExe) {
    $DesktopExe = Join-Path $repoRoot '灵枢桌面版.exe'
}
if (-not (Test-Path $DesktopExe)) {
    throw "没有桌面版 exe（$DesktopExe）—— 先跑 build-desktop.ps1"
}
Write-Step "桌面版：$DesktopExe"

# ---------- 1. 内嵌解释器 ----------

$cacheDir = Join-Path $launcherDir '.cache\python'
New-Item -ItemType Directory -Force -Path $cacheDir | Out-Null
if (-not $PythonZip) {
    $PythonZip = Join-Path $cacheDir "python-$PythonVersion-embed-amd64.zip"
    if (-not (Test-Path $PythonZip)) {
        $url = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
        Write-Step "下载内嵌解释器：$url"
        try {
            $ProgressPreference = 'SilentlyContinue'
            Invoke-WebRequest -Uri $url -OutFile $PythonZip -UseBasicParsing
        }
        catch {
            throw "下载解释器失败（$($_.Exception.Message)）。可手动下好，然后用 -PythonZip 指过去。"
        }
    }
}
if (-not (Test-Path $PythonZip)) { throw "解释器包不存在：$PythonZip" }

if (Test-Path $OutDir) {
    Write-Step "清掉旧的输出目录：$OutDir"
    Remove-Item $OutDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$pyDir = Join-Path $OutDir 'py'
Write-Step "解开解释器到 py\"
Expand-Archive -Path $PythonZip -DestinationPath $pyDir -Force

$pyExe = Join-Path $pyDir 'python.exe'
if (-not (Test-Path $pyExe)) { throw "解压后没有 python.exe（包不对？）：$pyExe" }

# embeddable 默认不加载 site-packages，也不认 .pth；改 pythonXY._pth 才行
$pthFile = Get-ChildItem $pyDir -Filter 'python*._pth' | Select-Object -First 1
if (-not $pthFile) { throw '找不到 python*._pth，这个 embeddable 包结构不对' }
$pthLines = Get-Content $pthFile.FullName
$pthLines = $pthLines | ForEach-Object { if ($_ -match '^#\s*import site') { 'import site' } else { $_ } }
if ($pthLines -notcontains 'Lib\site-packages') { $pthLines += 'Lib\site-packages' }
if ($pthLines -notcontains 'Lib\site-packages\win32') { $pthLines += 'Lib\site-packages\win32' }
Set-Content -Path $pthFile.FullName -Value $pthLines -Encoding ASCII
Write-Step ("修好 " + $pthFile.Name + '：' + ($pthLines -join ' | '))

& $pyExe -c "import sys; print(sys.version)" | ForEach-Object { Write-Ok "解释器可用：$_" }

# ---------- 2. pip ----------

if (-not $SkipInstall) {
    if (-not $GetPip) {
        $GetPip = Join-Path $cacheDir 'get-pip.py'
        if (-not (Test-Path $GetPip)) {
            Write-Step '下载 get-pip.py'
            try {
                $ProgressPreference = 'SilentlyContinue'
                Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile $GetPip -UseBasicParsing
            }
            catch { throw "下载 get-pip.py 失败（$($_.Exception.Message)）" }
        }
    }
    if (-not (Test-Path $GetPip)) { throw "get-pip.py 不存在：$GetPip" }

    Write-Step '给内嵌解释器装 pip'
    # get-pip 也要走镜像：直连 PyPI 时它会在这一步反复重试，卡十几分钟不动
    $getPipArgs = @($GetPip, '--no-warn-script-location', '--disable-pip-version-check')
    $mirror = if ($IndexUrl) { $IndexUrl } elseif ($env:SPIRITSCOUT_PIP_INDEX) { $env:SPIRITSCOUT_PIP_INDEX } else { '' }
    if ($mirror) { $getPipArgs += @('--index-url', $mirror) }
    & $pyExe @getPipArgs
    if ($LASTEXITCODE -ne 0) { throw "get-pip.py 失败（退出码 $LASTEXITCODE）" }

    # ---------- 3. 装灵枢与依赖 ----------
    # 必须显式 --target：内嵌解释器一旦能被判成「用户 site 可写」，
    # pip 就会往 %APPDATA%\Python 里装（本机实测直接权限失败，还会污染宿主环境）。
    $sitePackages = Join-Path $pyDir 'Lib\site-packages'
    New-Item -ItemType Directory -Force -Path $sitePackages | Out-Null
    $env:PYTHONNOUSERSITE = '1'          # 别让宿主机的用户级包混进便携版
    $pipArgs = @('-m', 'pip', 'install', '--no-warn-script-location', '--disable-pip-version-check',
                 '--no-user', '--target', $sitePackages, '--upgrade')
    if ($IndexUrl) { $pipArgs += @('--index-url', $IndexUrl) }
    elseif ($env:SPIRITSCOUT_PIP_INDEX) { $pipArgs += @('--index-url', $env:SPIRITSCOUT_PIP_INDEX) }
    $pipArgs += $Wheel

    Write-Step '装依赖（litellm / langgraph / fastapi 这一坨，几分钟起步，别关窗口）'
    Write-Host ('    ' + $pyExe + ' ' + ($pipArgs -join ' ')) -ForegroundColor DarkGray
    & $pyExe @pipArgs
    if ($LASTEXITCODE -ne 0) { throw "pip install 失败（退出码 $LASTEXITCODE）" }
}
else {
    Write-Warn2 '跳过安装（-SkipInstall）：目录里只有解释器，没有依赖'
}

# ---------- 4. 配置与目录 ----------

$cfgSrc = Join-Path $repoRoot 'SpiritScout\configs'
$cfgDst = Join-Path $OutDir 'configs'
New-Item -ItemType Directory -Force -Path $cfgDst | Out-Null

function Copy-Config([string]$from, [string]$to) {
    $src = Join-Path $cfgSrc $from
    if (-not (Test-Path $src)) { Write-Warn2 "缺配置模板：$from"; return }
    Copy-Item $src (Join-Path $cfgDst $to) -Force
    Write-Ok "configs\$to"
}

# 真实 models.yaml / system.yaml 不进包：一律从 *.example.yaml 起一份
Copy-Config 'system.example.yaml' 'system.yaml'
Copy-Config 'models.example.yaml' 'models.yaml'
Copy-Config 'skills.yaml' 'skills.yaml'

foreach ($d in @('data', 'workspaces', 'logs')) {
    New-Item -ItemType Directory -Force -Path (Join-Path $OutDir $d) | Out-Null
}

# ---------- 5. exe 与 desktop.json ----------

Copy-Item $DesktopExe (Join-Path $OutDir '灵枢桌面版.exe') -Force
$json = @"
{
  "root": ".",
  "python": "py\\python.exe",
  "port": 8010
}
"@
[System.IO.File]::WriteAllText((Join-Path $OutDir 'desktop.json'), $json, (New-Object System.Text.UTF8Encoding($false)))
Write-Ok 'desktop.json（root=程序目录，python=py\python.exe）'

$cmd = @"
@echo off
rem Start the SpiritScout desktop build from the portable folder.
cd /d "%~dp0"
start "" "%~dp0灵枢桌面版.exe"
"@
# .cmd 里要写中文文件名（灵枢桌面版.exe），所以按系统 ANSI 代码页（中文 Windows 是 936）落盘；
# 用 ASCII 会把中文变成 ?，双击后一句「找不到文件」。行尾必须 CRLF——只给 LF 时旧版 cmd
# 会把 start 那行读歪，双击毫无反应。
$cmd = $cmd -replace "`r?`n", "`r`n"
$ansi = [System.Text.Encoding]::GetEncoding(936)
[System.IO.File]::WriteAllText((Join-Path $OutDir '启动灵枢.cmd'), $cmd, $ansi)
Write-Ok '启动灵枢.cmd'

$readme = @"
灵枢便携版 $version —— 双击「灵枢桌面版.exe」即可，不需要装 Python，也不需要联网。

    py\        内嵌的 Python 3.11 与灵枢的依赖（别删）
    configs\   system.yaml / models.yaml / skills.yaml
               第一次用先编辑 models.yaml，把模型渠道与密钥填上
    desktop.json  告诉 exe 用哪个解释器、程序目录在哪

整份目录可以拷到 U 盘或别的机器，路径随你放，但别只拷 exe。
日志在 logs\，会话数据在 data\ 与 workspaces\。
"@
[System.IO.File]::WriteAllText((Join-Path $OutDir '使用说明.txt'), $readme, (New-Object System.Text.UTF8Encoding($true)))
Write-Ok '使用说明.txt'

# ---------- 6. 冒烟 ----------

if (-not $SkipInstall) {
    Write-Step '冒烟：内嵌解释器里能不能 import 灵枢'
    Push-Location $OutDir
    try {
        $out = & (Join-Path $OutDir 'py\python.exe') -c "import spiritscout, sys; print('灵枢 ' + spiritscout.__version__ + ' / Python ' + sys.version.split()[0])"
        if ($LASTEXITCODE -ne 0) { throw 'import spiritscout 失败' }
        Write-Ok $out
        $env:PYTHONNOUSERSITE = '1'
        $count = (& (Join-Path $OutDir 'py\python.exe') -m pip list --format=freeze 2>$null | Measure-Object).Count
        Write-Ok "已装包 $count 个"
    }
    finally { Pop-Location }
}

# ---------- 7. 打包 ----------

$totalMb = [math]::Round(((Get-ChildItem $OutDir -Recurse -File | Measure-Object Length -Sum).Sum / 1MB), 1)
Write-Ok "目录完成：$OutDir（$totalMb MB）"

if (-not $NoZip) {
    $zipPath = Join-Path $repoRoot ("dist-portable\spiritscout-$version-portable-win64.zip")
    if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
    Write-Step "压缩成 $zipPath（这一步也慢）"
    Compress-Archive -Path (Join-Path $OutDir '*') -DestinationPath $zipPath -CompressionLevel Optimal
    $zipMb = [math]::Round(((Get-Item $zipPath).Length / 1MB), 1)
    Write-Ok "打完：$zipPath（$zipMb MB）"
    Write-Host ''
    Write-Host '拷到别的机器：解压后双击 灵枢桌面版.exe。' -ForegroundColor Green
    Write-Host '发布：把它作为 release 附件（和 wheel/sdist/zip 并列）。' -ForegroundColor Green
}
