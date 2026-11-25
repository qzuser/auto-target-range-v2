#Requires -Version 5.1
<#
.SYNOPSIS
    Build a self-contained Python runtime for the native SpiritScout desktop app.

.DESCRIPTION
    The script prepares:

        <OutDir>\
            py\       Python embeddable runtime plus installed dependencies
            configs\  editable configuration copied from the repository templates

    It intentionally does not create a desktop executable. The Compose desktop
    application is packaged by build-desktop.ps1; this script is the Python layer
    shared by local builds and release builds.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging\windows\build-backend-runtime.ps1

.EXAMPLE
    ... -Wheel D:\artifacts\spiritscout-1.3.0-py3-none-any.whl -OutDir D:\runtime
#>
[CmdletBinding()]
param(
    [string]$Wheel = '',
    [string]$PythonVersion = '3.11.9',
    [string]$OutDir = '',
    [string]$PythonZip = '',
    [string]$GetPip = '',
    [string]$IndexUrl = '',
    [switch]$SkipInstall
)

$ErrorActionPreference = 'Stop'

function Write-Step([string]$Text) { Write-Host "[>] $Text" -ForegroundColor Cyan }
function Write-Ok([string]$Text) { Write-Host "[+] $Text" -ForegroundColor Green }
function Write-Warn2([string]$Text) { Write-Host "[!] $Text" -ForegroundColor Yellow }

function Test-ZipArchive([string]$Path) {
    try {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $archive = [System.IO.Compression.ZipFile]::OpenRead($Path)
        try { $archive.Dispose() } finally { $null = $archive }
        return $true
    }
    catch {
        return $false
    }
}

function Invoke-Download([string]$Url, [string]$Destination) {
    if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
        & curl.exe -L --fail --retry 3 --retry-delay 2 --connect-timeout 20 --max-time 600 `
            --output $Destination $Url
        return $LASTEXITCODE -eq 0
    }
    try {
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest -Uri $Url -OutFile $Destination -UseBasicParsing -TimeoutSec 600
        return $true
    }
    catch {
        return $false
    }
}

$packagingDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent (Split-Path -Parent $packagingDir)
$versionFile = Join-Path $repoRoot 'src\spiritscout\__init__.py'

if (-not (Test-Path -LiteralPath (Join-Path $repoRoot 'pyproject.toml'))) {
    throw "Cannot find pyproject.toml. Run this script from the repository root."
}

$version = (Select-String -Path $versionFile -Pattern '__version__\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
if (-not $version) {
    throw "Cannot read __version__ from $versionFile"
}

if (-not $OutDir) {
    $OutDir = Join-Path $repoRoot 'build\backend-runtime'
}
$OutDir = [System.IO.Path]::GetFullPath($OutDir)

if (-not $Wheel) {
    $candidates = @()
    foreach ($dir in @((Join-Path $repoRoot 'dist\python'), (Join-Path $repoRoot 'dist'))) {
        if (Test-Path -LiteralPath $dir) {
            $candidates += @(Get-ChildItem -LiteralPath $dir -File -Filter 'spiritscout-*.whl' -ErrorAction SilentlyContinue)
        }
    }
    $candidates = @($candidates | Sort-Object LastWriteTime -Descending)
    if ($candidates.Count -eq 0) {
        throw "No spiritscout-*.whl found. Build one first: uv build --wheel --outdir dist\python ."
    }
    $Wheel = $candidates[0].FullName
}
$Wheel = (Resolve-Path -LiteralPath $Wheel).Path

$pyCache = Join-Path $repoRoot 'build\download-cache\python'
New-Item -ItemType Directory -Force -Path $pyCache | Out-Null
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

if (-not $PythonZip) {
    $PythonZip = Join-Path $pyCache "python-$PythonVersion-embed-amd64.zip"
    if ((-not (Test-Path -LiteralPath $PythonZip)) -or -not (Test-ZipArchive $PythonZip)) {
        if (Test-Path -LiteralPath $PythonZip) {
            Remove-Item -LiteralPath $PythonZip -Force
        }
        Write-Step "Download Python embeddable $PythonVersion"
        $download = "$PythonZip.download"
        $fileName = "python-$PythonVersion-embed-amd64.zip"
        $urls = @()
        if ($env:SPIRITSCOUT_PYTHON_URL) {
            $urls += $env:SPIRITSCOUT_PYTHON_URL
        }
        $urls += @(
            "https://mirrors.huaweicloud.com/python/$PythonVersion/$fileName",
            "https://registry.npmmirror.com/-/binary/python/$PythonVersion/$fileName",
            "https://mirrors.tuna.tsinghua.edu.cn/python/$PythonVersion/$fileName",
            "https://www.python.org/ftp/python/$PythonVersion/$fileName"
        )
        $downloaded = $false
        foreach ($url in $urls | Select-Object -Unique) {
            if (Test-Path -LiteralPath $download) {
                Remove-Item -LiteralPath $download -Force
            }
            Write-Host "    $url"
            if (Invoke-Download $url $download) {
                Move-Item -LiteralPath $download -Destination $PythonZip -Force
                $downloaded = $true
                break
            }
        }
        if (-not $downloaded) {
            throw "Python download failed. Pass -PythonZip with a local copy."
        }
    }
}
if (-not (Test-Path -LiteralPath $PythonZip)) {
    throw "Python archive not found: $PythonZip"
}

$pyDir = Join-Path $OutDir 'py'
if (Test-Path -LiteralPath $pyDir) {
    Write-Step "Remove previous Python runtime: $pyDir"
    Remove-Item -LiteralPath $pyDir -Recurse -Force
}
Write-Step "Extract Python to $pyDir"
Expand-Archive -LiteralPath $PythonZip -DestinationPath $pyDir -Force

$pyExe = Join-Path $pyDir 'python.exe'
if (-not (Test-Path -LiteralPath $pyExe)) {
    throw "The archive does not contain python.exe: $pyExe"
}

# Embeddable Python disables site-packages in pythonXY._pth by default.
$pthFile = Get-ChildItem -LiteralPath $pyDir -Filter 'python*._pth' | Select-Object -First 1
if (-not $pthFile) {
    throw "Cannot find pythonXY._pth in $pyDir"
}
$pthLines = @(Get-Content -LiteralPath $pthFile.FullName)
$pthLines = @($pthLines | ForEach-Object {
    if ($_ -match '^#\s*import site') { 'import site' } else { $_ }
})
if ($pthLines -notcontains 'Lib\site-packages') { $pthLines += 'Lib\site-packages' }
if ($pthLines -notcontains 'Lib\site-packages\win32') { $pthLines += 'Lib\site-packages\win32' }
[System.IO.File]::WriteAllLines(
    $pthFile.FullName,
    $pthLines,
    (New-Object System.Text.UTF8Encoding($false))
)

& $pyExe -c "import sys; print(sys.version)"
if ($LASTEXITCODE -ne 0) {
    throw "The extracted Python interpreter cannot start."
}
Write-Ok "Python $version runtime ready"

if (-not $SkipInstall) {
    if (-not $GetPip) {
        $GetPip = Join-Path $pyCache 'get-pip.py'
        if (-not (Test-Path -LiteralPath $GetPip)) {
            Write-Step 'Download get-pip.py'
            $download = "$GetPip.download"
            if (Test-Path -LiteralPath $download) {
                Remove-Item -LiteralPath $download -Force
            }
            $getPipUrls = @()
            if ($env:SPIRITSCOUT_GET_PIP_URL) {
                $getPipUrls += $env:SPIRITSCOUT_GET_PIP_URL
            }
            $getPipUrls += @(
                'https://mirrors.aliyun.com/pypi/get-pip.py',
                'https://bootstrap.pypa.io/get-pip.py'
            )
            $downloaded = $false
            foreach ($getPipUrl in $getPipUrls) {
                if (Invoke-Download $getPipUrl $download) {
                    Move-Item -LiteralPath $download -Destination $GetPip -Force
                    $downloaded = $true
                    break
                }
                if (Test-Path -LiteralPath $download) {
                    Remove-Item -LiteralPath $download -Force
                }
            }
            if (-not $downloaded) {
                throw "get-pip.py download failed: $($getPipUrls -join ', ')"
            }
        }
    }
    if (-not (Test-Path -LiteralPath $GetPip)) {
        throw "get-pip.py not found: $GetPip"
    }

    $mirror = if ($IndexUrl) {
        $IndexUrl
    } elseif ($env:SPIRITSCOUT_PIP_INDEX) {
        $env:SPIRITSCOUT_PIP_INDEX
    } else {
        'https://pypi.tuna.tsinghua.edu.cn/simple'
    }
    $officialIndex = 'https://pypi.org/simple'
    $getPipArgs = @($GetPip, '--no-warn-script-location', '--disable-pip-version-check')
    if ($mirror) { $getPipArgs += @('--index-url', $mirror) }

    Write-Step 'Install pip into the embedded interpreter'
    & $pyExe @getPipArgs
    if ($LASTEXITCODE -ne 0 -and $mirror -ne $officialIndex) {
        Write-Warn2 "pip bootstrap mirror failed; retrying with official PyPI: $officialIndex"
        & $pyExe $GetPip --index-url $officialIndex --no-warn-script-location --disable-pip-version-check
    }
    if ($LASTEXITCODE -ne 0) {
        throw "get-pip.py failed (exit code $LASTEXITCODE)"
    }

    $sitePackages = Join-Path $pyDir 'Lib\site-packages'
    New-Item -ItemType Directory -Force -Path $sitePackages | Out-Null
    $env:PYTHONNOUSERSITE = '1'
    $pipArgs = @(
        '-m', 'pip', 'install',
        '--no-warn-script-location',
        '--disable-pip-version-check',
        '--no-user',
        '--target', $sitePackages,
        '--upgrade',
        '--no-compile'
    )
    if ($mirror) { $pipArgs += @('--index-url', $mirror) }
    $pipArgs += $Wheel

    Write-Step "Install $([System.IO.Path]::GetFileName($Wheel)) and dependencies"
    & $pyExe @pipArgs
    if ($LASTEXITCODE -ne 0) {
        if ($mirror -ne $officialIndex) {
            Write-Warn2 "Dependency mirror failed; retrying with official PyPI: $officialIndex"
            $fallbackArgs = @(
                '-m', 'pip', 'install',
                '--no-warn-script-location',
                '--disable-pip-version-check',
                '--no-user',
                '--target', $sitePackages,
                '--upgrade',
                '--no-compile',
                '--index-url', $officialIndex,
                $Wheel
            )
            & $pyExe @fallbackArgs
        }
        if ($LASTEXITCODE -ne 0) {
            throw "pip install failed (exit code $LASTEXITCODE)"
        }
    }
}
else {
    Write-Warn2 'SkipInstall: dependencies were not installed.'
}

$configSrc = Join-Path $repoRoot 'configs'
$configDst = Join-Path $OutDir 'configs'
if (Test-Path -LiteralPath $configDst) {
    Remove-Item -LiteralPath $configDst -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $configDst | Out-Null

function Copy-Template([string]$Name, [string]$DestinationName = $Name) {
    $source = Join-Path $configSrc $Name
    if (-not (Test-Path -LiteralPath $source)) {
        Write-Warn2 "Missing config template: $Name"
        return
    }
    Copy-Item -LiteralPath $source -Destination (Join-Path $configDst $DestinationName) -Force
    Write-Ok "configs\$DestinationName"
}

Copy-Template 'system.example.yaml' 'system.yaml'
Copy-Template 'models.example.yaml' 'models.yaml'
Copy-Template 'models.mock.yaml'
Copy-Template 'skills.yaml'

if (-not $SkipInstall) {
    Write-Step 'Smoke test: import SpiritScout from the embedded runtime'
    Push-Location $OutDir
    try {
        $env:PYTHONNOUSERSITE = '1'
        & $pyExe -c "import spiritscout, sys; print('SpiritScout ' + spiritscout.__version__ + ' / Python ' + sys.version.split()[0])"
        if ($LASTEXITCODE -ne 0) {
            throw 'The embedded runtime could not import spiritscout.'
        }
    }
    finally {
        Pop-Location
    }
}

$totalMb = [Math]::Round(((Get-ChildItem -LiteralPath $OutDir -Recurse -File | Measure-Object Length -Sum).Sum / 1MB), 1)
Write-Ok "Python runtime ready: $OutDir ($totalMb MB)"
