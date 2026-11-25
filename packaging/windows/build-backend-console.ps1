#Requires -Version 5.1
<#
.SYNOPSIS
    Build the optional Windows backend console executable.

.DESCRIPTION
    The output is a PyInstaller single-file backend console, not the native
    desktop application. End users should normally use build-desktop.ps1.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging\windows\build-backend-console.ps1
#>
[CmdletBinding()]
param(
    [string]$PythonVersion = $(if ($env:BUILD_PYTHON) { $env:BUILD_PYTHON } else { '3.11' }),
    [string]$OutputDir = '',
    [string]$IndexUrl = $(if ($env:SPIRITSCOUT_PIP_INDEX) { $env:SPIRITSCOUT_PIP_INDEX } else { 'https://pypi.tuna.tsinghua.edu.cn/simple' })
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$versionFile = Join-Path $root 'src\spiritscout\__init__.py'
$version = (Select-String -Path $versionFile -Pattern '__version__\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
if (-not $OutputDir) {
    $OutputDir = Join-Path $root 'dist\windows\backend-console'
}
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
$venv = Join-Path $root '.venv-build'
$python = Join-Path $venv 'Scripts\python.exe'
$uv = Get-Command uv -ErrorAction SilentlyContinue

function Test-CompatiblePython {
    param([string]$Executable)
    & $Executable -c "import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 15) else 1)" 2>$null
    return $LASTEXITCODE -eq 0
}

Push-Location $root
try {
    $compatible = (Test-Path -LiteralPath $python) -and (Test-CompatiblePython $python)
    if (-not $compatible) {
        if ($uv) {
            & $uv venv --python $PythonVersion --allow-existing $venv
            if ($LASTEXITCODE -ne 0) { throw "uv venv failed (exit code $LASTEXITCODE)" }
        }
        else {
            $py = Get-Command py -ErrorAction SilentlyContinue
            if ($py) {
                & $py "-$PythonVersion" -m venv --clear $venv
            }
            if (-not (Test-Path -LiteralPath $python)) {
                $fallback = Get-Command python -ErrorAction SilentlyContinue
                if (-not $fallback) {
                    throw "Missing uv or Python 3.11-3.14."
                }
                & $fallback -c "import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 15) else 1)"
                if ($LASTEXITCODE -ne 0) {
                    throw "The fallback Python must be 3.11-3.14: $(& $fallback --version)"
                }
                & $fallback -m venv --clear $venv
            }
        }
        if (-not (Test-CompatiblePython $python)) {
            throw "The build Python must be 3.11-3.14: $(& $python --version)"
        }
    }

    if ($uv) {
        & $uv pip install --python $python --default-index $IndexUrl -e '.[build]'
        $installExitCode = $LASTEXITCODE
    }
    else {
        & $python -m pip install --index-url $IndexUrl --upgrade pip
        $installExitCode = $LASTEXITCODE
        if ($installExitCode -eq 0) {
            & $python -m pip install --index-url $IndexUrl -e '.[build]'
            $installExitCode = $LASTEXITCODE
        }
    }
    if ($installExitCode -ne 0 -and $IndexUrl -notlike 'https://pypi.org*') {
        Write-Warning "Dependency mirror failed; retrying with official PyPI."
        if ($uv) {
            & $uv pip install --python $python --default-index 'https://pypi.org/simple' -e '.[build]'
        }
        else {
            & $python -m pip install --index-url 'https://pypi.org/simple' -e '.[build]'
        }
    }
    if ($LASTEXITCODE -ne 0) { throw "Build dependency install failed (exit code $LASTEXITCODE)" }

    New-Item -ItemType Directory -Force -Path $OutputDir, (Join-Path $root 'build\pyinstaller') | Out-Null
    & $python -m PyInstaller --clean --noconfirm `
        --distpath $OutputDir `
        --workpath (Join-Path $root 'build\pyinstaller') `
        packaging\windows\backend-console.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit code $LASTEXITCODE)" }

    $built = Join-Path $OutputDir 'SpiritScout.exe'
    if (-not (Test-Path -LiteralPath $built)) { throw "PyInstaller did not create $built" }
    $output = Join-Path $OutputDir "SpiritScout-$version-windows-x64-backend.exe"
    Move-Item -LiteralPath $built -Destination $output -Force
    & $output --version
    if ($LASTEXITCODE -ne 0) { throw "Built executable failed its version check." }
    Write-Host "Backend console: $output"
}
finally {
    Pop-Location
}
