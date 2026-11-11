# 编译「灵枢桌面版.exe」——自带窗口的 Windows 客户端。
#
# 产物是一个独立 exe：内嵌浏览器要的三个 DLL 以资源形式塞进 PE，
# 首次运行时自己解到 %LOCALAPPDATA%\SpiritScout\lib。双击即用，
# 不需要装 .NET SDK（用的是 Windows 自带的 csc.exe），也不需要随包带 DLL。
#
#   powershell -ExecutionPolicy Bypass -File SpiritScout\launcher\build-desktop.ps1
#   powershell ... -File ... -OutputDir D:\dist      # 换个落点
#   powershell ... -File ... -SkipDownload           # 用缓存里的 SDK（离线）
#
# WebView2 运行时（Edge WebView2 Runtime）是 Windows 10/11 自带的；
# 真没有时程序会退到「用浏览器打开」（Edge 独立窗口），不会白屏。
param(
    [string]$OutputDir = '',
    [string]$SdkVersion = '',
    [switch]$SkipDownload
)

$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$repoRoot = Split-Path $here -Parent          # SpiritScout/
$workRoot = Split-Path $repoRoot -Parent      # 仓库根（exe 默认放这里）

if (-not $OutputDir) { $OutputDir = $workRoot }
$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)
$cache = Join-Path $here '.cache\webview2'
$source = Join-Path $here 'SpiritScoutDesktop.cs'
$outputName = '灵枢桌面版.exe'
$outputPath = Join-Path $OutputDir $outputName

# 版本写死的理由：WebView2 的托管 DLL 与原生 loader 必须同版本，
# 随手取最新会导致「DLL 版本不匹配」这种极难查的白屏。升级改这一处。
if (-not $SdkVersion) { $SdkVersion = '1.0.2903.40' }
$sdkDir = Join-Path $cache $SdkVersion

function Find-Csc {
    $candidates = @(
        (Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'),
        (Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe')
    )
    foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
    throw '找不到 csc.exe（.NET Framework 4.x 自带的编译器）。Windows 10/11 默认有：确认没被裁剪过系统组件。'
}

function Ensure-Sdk {
    $need = @(
        (Join-Path $sdkDir 'Microsoft.Web.WebView2.Core.dll'),
        (Join-Path $sdkDir 'Microsoft.Web.WebView2.WinForms.dll'),
        (Join-Path $sdkDir 'WebView2Loader.dll')
    )
    $missing = $need | Where-Object { -not (Test-Path $_) }
    if (-not $missing) { return }

    if ($SkipDownload) {
        throw "缓存里缺 WebView2 SDK：$($missing -join ', ')。去掉 -SkipDownload 再跑一次。"
    }

    Write-Host "[1/4] 取 WebView2 SDK $SdkVersion（NuGet，约 8 MB）…"
    New-Item -ItemType Directory -Force -Path $sdkDir | Out-Null
    $pkg = Join-Path $sdkDir 'pkg.zip'
    $urls = @(
        "https://www.nuget.org/api/v2/package/Microsoft.Web.WebView2/$SdkVersion",
        "https://nuget.cdn.azure.cn/v3-flatcontainer/microsoft.web.webview2/$($SdkVersion.ToLower())/microsoft.web.webview2.$($SdkVersion.ToLower()).nupkg"
    )
    $ok = $false
    foreach ($url in $urls) {
        try {
            Invoke-WebRequest -Uri $url -OutFile $pkg -TimeoutSec 300
            $ok = $true
            break
        } catch {
            Write-Host "    这个源不行（$($_.Exception.Message)），换下一个"
        }
    }
    if (-not $ok) { throw "WebView2 SDK 下载失败：$($urls -join ' / ')" }

    $extract = Join-Path $sdkDir 'pkg'
    Remove-Item $extract -Recurse -Force -ErrorAction SilentlyContinue
    Expand-Archive -Path $pkg -DestinationPath $extract -Force
    Copy-Item (Join-Path $extract 'lib\net462\Microsoft.Web.WebView2.Core.dll') $sdkDir -Force
    Copy-Item (Join-Path $extract 'lib\net462\Microsoft.Web.WebView2.WinForms.dll') $sdkDir -Force
    Copy-Item (Join-Path $extract 'runtimes\win-x64\native\WebView2Loader.dll') $sdkDir -Force
    Remove-Item $pkg -Force
    Remove-Item $extract -Recurse -Force
    Write-Host "    已解到 $sdkDir"
}

Ensure-Sdk
$csc = Find-Csc

Write-Host "[2/4] 编译（csc /target:winexe /platform:x64）…"
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$coreDll = Join-Path $sdkDir 'Microsoft.Web.WebView2.Core.dll'
$winFormsDll = Join-Path $sdkDir 'Microsoft.Web.WebView2.WinForms.dll'
$loaderDll = Join-Path $sdkDir 'WebView2Loader.dll'

# 图标跟网页标签页同一个（static/favicon.svg 渲出来的 launcher/icon.ico），
# 任务栏、桌面、资源管理器里看到的就是浏览器里那个标志。
$iconPath = Join-Path $PSScriptRoot 'icon.ico'
$iconArgs = @()
if (Test-Path $iconPath) {
    # 既做 exe 的图标，也作为资源嵌进去让窗口自己用（WinForms 不会自动继承 exe 图标）
    $iconArgs = @(("/win32icon:" + $iconPath), ("/resource:" + $iconPath + ",app.icon"))
} else {
    Write-Host '    [!] 没找到 launcher/icon.ico，先按没有图标的编（跑一次 make-icon.py 就有了）'
}

# 启动页与错误页也是窗口的一部分：浅色 HTML 直接嵌进 exe，运行时 NavigateToString 用，
# 不落到磁盘上（写不进去的目录也能用），也不会出现联网请求。
foreach ($page in @('splash.html', 'error.html', 'dialog.html')) {
    $pagePath = Join-Path (Join-Path $PSScriptRoot 'ui') $page
    if (-not (Test-Path $pagePath)) { throw "缺 launcher/ui/$page —— 启动页/错误页是窗口的一部分，必须有" }
    $iconArgs += ("/resource:" + $pagePath + "," + $page)
}

$cscArgs = @(
    '/nologo', '/target:winexe', '/platform:x64', '/optimize+',
    '/utf8output',
    ("/out:" + $outputPath),
    '/reference:System.dll',
    '/reference:System.Drawing.dll',
    '/reference:System.Windows.Forms.dll',
    '/reference:System.Core.dll',
    ("/reference:" + $coreDll),
    ("/reference:" + $winFormsDll),
    ("/resource:" + $coreDll + ",wv2.core"),
    ("/resource:" + $winFormsDll + ",wv2.winforms"),
    ("/resource:" + $loaderDll + ",wv2.loader"),
    $source
) + $iconArgs
# 上一版还在跑的时候 csc 写不进输出文件，报错信息又只有一句「退出码 1」，
# 所以先收掉同名进程再编；真失败了把 csc 的原话打出来。
$running = Get-Process -Name ([System.IO.Path]::GetFileNameWithoutExtension($outputName)) -ErrorAction SilentlyContinue
if ($running) {
    Write-Host "    发现旧实例在跑（PID $($running.Id -join ', ')），先关掉再编译"
    $running | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 600
}
$compileLog = & $csc @cscArgs 2>&1
if ($LASTEXITCODE -ne 0) {
    $compileLog | ForEach-Object { Write-Host "    $_" }
    throw "csc 编译失败（退出码 $LASTEXITCODE）"
}
$compileLog | Where-Object { $_ -match 'warning' } | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }

Write-Host "[3/4] 校验产物…"
if (-not (Test-Path $outputPath)) { throw "没生成 $outputPath" }
$size = [math]::Round((Get-Item $outputPath).Length / 1KB)
Write-Host "    $outputPath（$size KB）"

Write-Host "[4/4] 冒烟：确认 exe 能起来并自建窗口…"
# 带 --smoke：只验窗口，不起控制台（不然每次构建都会留一个占端口的服务进程）。
# 浏览器数据目录也换成临时的：不然冒烟实例和用户正开着的窗口抢同一份 profile，
# WebView2 会报「资源在使用中」，看起来像启动失败。
$smokeProfile = Join-Path ([System.IO.Path]::GetTempPath()) ("spiritscout-smoke-" + $PID)
$env:SPIRITSCOUT_WEBVIEW_DIR = $smokeProfile    # 子进程继承环境变量（5.1 的 Start-Process 没有 -Environment）
$proc = Start-Process -FilePath $outputPath -ArgumentList '--smoke' -PassThru
$title = ''
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 400
    if ($proc.HasExited) { break }
    if ($proc.MainWindowTitle) { $title = $proc.MainWindowTitle; break }
}
# 冒烟窗口两三秒就自己关了，所以除了看标题，也认日志里那句「构建冒烟：窗口正常」。
$smokeOk = $title -like '*灵枢*'
if (-not $smokeOk) {
    $log = Get-ChildItem (Join-Path (Split-Path $outputPath) 'logs') -Filter 'desktop-*.log' -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($log) {
        $smokeOk = (Get-Content $log.FullName -Encoding utf8 -Tail 20) -match '构建冒烟：窗口正常' | Where-Object { $_ }
        if ($smokeOk) { $title = $proc.MainWindowTitle }
    }
}
if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
Remove-Item Env:\SPIRITSCOUT_WEBVIEW_DIR -ErrorAction SilentlyContinue
Remove-Item $smokeProfile -Recurse -Force -ErrorAction SilentlyContinue
if ($smokeOk) {
    Write-Host "    窗口标题：$title"
    Write-Host "    冒烟通过（已关闭）" -ForegroundColor Green
} else {
    Write-Host "    [!] 冒烟没通过：窗口没出来，日志里也没有「构建冒烟：窗口正常」" -ForegroundColor Yellow
    exit 1
}
Write-Host "完成。双击 $outputName 即可打开灵枢桌面版；" -ForegroundColor Green
Write-Host "它会在 %LOCALAPPDATA%\SpiritScout\lib 放 WebView2 的三个 DLL（首次启动自动解压）。"
