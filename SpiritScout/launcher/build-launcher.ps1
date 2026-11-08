<#
.SYNOPSIS
    编译并签名灵枢的 Windows 启动器（启动服务.exe）。

.DESCRIPTION
    .cmd / .bat 没有 Authenticode 容器，Windows 的信任提供程序会直接拒绝，
    双击入口永远显示"未知发布者"。想让入口带上发布者，入口必须是 PE 文件。
    这个脚本把 launcher/SpiritScoutLauncher.cs 编成 exe，再用本机自签名证书
    签一遍，产物可以直接双击运行，行为与 启动服务.cmd 一致。

    签名材料默认放在 %USERPROFILE%\.spiritscout\signing\，不入库：
      SpiritScoutLocal.pfx  带私钥的证书（密码见 -PfxPassword）
      SpiritScoutLocal.cer  公钥证书
      osslsigncode.exe      签名工具（首次会自动下载）

.PARAMETER OutFile
    输出路径，默认仓库根的 启动服务.exe。

.PARAMETER PfxPassword
    pfx 密码。不传就读环境变量 SPIRITSCOUT_SIGN_PASSWORD；
    首次生成证书时也会用它，之后需要保持一致。

.PARAMETER SkipSign
    只编译不签名（调试用；未签名的 exe 仍然会被当成未知发布者）。

.EXAMPLE
    pwsh -File SpiritScout\launcher\build-launcher.ps1
#>
[CmdletBinding()]
param(
    [string]$OutFile = '',
    [string]$PfxPassword = $env:SPIRITSCOUT_SIGN_PASSWORD,
    [string]$SigningDir = (Join-Path $env:USERPROFILE '.spiritscout\signing'),
    [string]$OsslSignCode = '',
    [switch]$SkipSign
)

$ErrorActionPreference = 'Stop'
$launcherDir = $PSScriptRoot
$repoRoot = Split-Path -Parent (Split-Path -Parent $launcherDir)
if (-not $OutFile) { $OutFile = Join-Path $repoRoot '启动服务.exe' }

function Write-Step([string]$text) { Write-Host "[*] $text" }

# ---- 1. 编译 ---------------------------------------------------------------
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path $csc)) {
    $csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe'
}
if (-not (Test-Path $csc)) {
    throw '找不到 csc.exe（.NET Framework 4.x 自带）；请确认系统装了 .NET Framework 4.x'
}

$source = Join-Path $launcherDir 'SpiritScoutLauncher.cs'
if (-not (Test-Path $source)) { throw "找不到源码：$source" }

$work = Join-Path ([System.IO.Path]::GetTempPath()) ("spiritscout-launcher-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $work | Out-Null
$compiled = Join-Path $work 'SpiritScoutLauncher.exe'

Write-Step "编译 $(Split-Path -Leaf $source)"
& $csc /nologo /target:exe "/out:$compiled" /codepage:65001 /utf8output /optimize+ $source | Out-Null
if (-not (Test-Path $compiled)) { throw '编译失败：没有生成 exe' }
Write-Step ("编译完成 {0:N1} KB" -f ((Get-Item $compiled).Length / 1KB))

if ($SkipSign) {
    Copy-Item $compiled $OutFile -Force
    Write-Warning '已跳过签名：这个 exe 双击仍会显示"未知发布者"'
    Write-Step "输出 $OutFile"
    Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue
    return
}

# ---- 2. 证书 ---------------------------------------------------------------
if (-not $PfxPassword) {
    throw '缺少 pfx 密码：传 -PfxPassword，或设环境变量 SPIRITSCOUT_SIGN_PASSWORD'
}
New-Item -ItemType Directory -Force -Path $SigningDir | Out-Null
$pfxPath = Join-Path $SigningDir 'SpiritScoutLocal.pfx'
$cerPath = Join-Path $SigningDir 'SpiritScoutLocal.cer'

if (-not (Test-Path $pfxPath)) {
    Write-Step '没有现成证书，生成一张自签名代码签名证书（有效期 10 年）'
    $cert = New-SelfSignedCertificate -Type CodeSigningCert `
        -Subject 'CN=SpiritScout Local, O=SpiritScout, C=CN' `
        -FriendlyName 'SpiritScout 本机启动器签名' `
        -KeyUsage DigitalSignature -KeyExportPolicy Exportable -KeyLength 3072 `
        -HashAlgorithm SHA256 -NotAfter (Get-Date).AddYears(10) `
        -CertStoreLocation Cert:\CurrentUser\My `
        -TextExtension @('2.5.29.37={text}1.3.6.1.5.5.7.3.3', '2.5.29.19={text}')

    $secure = ConvertTo-SecureString -String $PfxPassword -AsPlainText -Force
    Export-PfxCertificate -Cert $cert -FilePath $pfxPath -Password $secure | Out-Null
    Export-Certificate -Cert $cert -FilePath $cerPath -Type CERT | Out-Null
    Write-Step "证书指纹 $($cert.Thumbprint)"

    # 自签名证书必须进"受信任的根"和"受信任的发布者"，否则验证不过
    $public = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2 $cerPath
    foreach ($name in 'Root', 'TrustedPublisher') {
        $store = New-Object System.Security.Cryptography.X509Certificates.X509Store($name, 'CurrentUser')
        $store.Open([System.Security.Cryptography.X509Certificates.OpenFlags]::ReadWrite)
        $store.Add($public)
        $store.Close()
    }
    Write-Step '已把证书装进当前用户的 受信任根 / 受信任发布者'
}
if (-not (Test-Path $cerPath)) { throw "缺少公钥证书：$cerPath" }

# ---- 3. 签名 ---------------------------------------------------------------
if (-not $OsslSignCode) {
    $candidates = @(
        (Join-Path $SigningDir 'osslsigncode.exe'),
        (Join-Path $launcherDir 'tools/osslsigncode.exe')
    )
    $OsslSignCode = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $OsslSignCode) {
    Write-Step '没有签名工具，下载 osslsigncode（约 2.6 MB，便携版，不入库）'
    $zip = Join-Path $SigningDir 'osslsigncode.zip'
    Invoke-WebRequest 'https://github.com/mtrojnar/osslsigncode/releases/download/2.15/osslsigncode-2.15-windows-amd64.zip' `
        -OutFile $zip -UseBasicParsing
    Expand-Archive -Path $zip -DestinationPath (Join-Path $SigningDir 'osslsigncode-unpack') -Force
    $found = Get-ChildItem (Join-Path $SigningDir 'osslsigncode-unpack') -Recurse -Filter 'osslsigncode.exe' |
        Select-Object -First 1
    if (-not $found) { throw 'osslsigncode 解压后没找到 exe' }
    Copy-Item $found.FullName (Join-Path $SigningDir 'osslsigncode.exe') -Force
    $OsslSignCode = Join-Path $SigningDir 'osslsigncode.exe'
}

$signed = Join-Path $work 'SpiritScoutLauncher.signed.exe'
Write-Step "签名（$([System.IO.Path]::GetFileName($OsslSignCode))）"
& $OsslSignCode sign -pkcs12 $pfxPath -pass $PfxPassword -h sha256 `
    -n 'SpiritScout 灵枢 启动器' -i 'https://github.com/qzuser/auto-target-range-v2' `
    -in $compiled -out $signed | Out-Null
if (-not (Test-Path $signed)) { throw '签名失败：没有生成签名后的 exe' }

Copy-Item $signed $OutFile -Force
$check = Get-AuthenticodeSignature $OutFile
Write-Step "输出 $OutFile"
Write-Host "    签名状态：$($check.Status)　签名者：$($check.SignerCertificate.Subject)"
if ($check.Status -ne 'Valid') {
    Write-Warning '签名验证没过：确认证书已装进"受信任的根证书颁发机构"和"受信任的发布者"'
}

Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue
