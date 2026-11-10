# 本机启动器（不用 Docker）
#
# 作用：自检环境与依赖 → 导出执行后端与模型网关 key → 启动灵枢 Web 控制台。
# 缺运行依赖（含本体没装进 venv）由本脚本自己 pip 装；缺虚拟环境、缺 pip 或
# 解释器版本不够只报命令不动手——重建 venv 的影响面比装几个包大得多。
# 依赖：Python 3.11+（SpiritScout\.venv）、Git for Windows 的 bash。
#
#   powershell -ExecutionPolicy Bypass -File .\start-local.ps1
#   powershell -ExecutionPolicy Bypass -File .\start-local.ps1 -Port 8010
#   powershell -ExecutionPolicy Bypass -File .\start-local.ps1 -NoInstall   # 只报告，不自动装
#   powershell -ExecutionPolicy Bypass -File .\start-local.ps1 -PipIndex official   # 走 PyPI 官方源
#
# 装依赖默认走国内镜像（清华 TUNA），镜像不可用时自动退回 PyPI 官方源重试一次。
# 换源：-PipIndex <url>，或环境变量 SPIRITSCOUT_PIP_INDEX；`-PipIndex official` 强制官方源。
# 只看当前解析出的源不动手：-ShowPipIndex。
#
# -Port 以 `--port` 传给 CLI，**覆盖** SpiritScout\configs\system.yaml 里的 web.port
# （配置里写的是 8000）；双击入口「启动服务.cmd」固定 8010，两个数字不一样是正常的。
# 跑的是 SpiritScout\src 下的当前代码（editable 安装），下面的版本号与
# `python -m spiritscout --version`、控制台横幅同源。
param(
    [int]$Port = 8010,
    [switch]$Debug,
    [switch]$NoInstall,
    [string]$PipIndex = '',
    [switch]$ShowPipIndex
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$venvPy = Join-Path $root 'SpiritScout\.venv\Scripts\python.exe'
$depsProbe = Join-Path $root 'SpiritScout\scripts\probe_deps.py'
$minPython = [version]'3.11'

# 依赖源：国内镜像优先。默认清华 TUNA——PyPI 官方站在国内经常几十 KB/s 甚至超时，
# 首次装 litellm/langgraph 那几百兆能把人耗死在窗口前。
$script:MirrorIndex = 'https://pypi.tuna.tsinghua.edu.cn/simple'
$script:OfficialIndex = 'https://pypi.org/simple'
$script:MirrorLabel = '清华镜像（TUNA）'

function Resolve-PipIndex([string]$value) {
    # 优先级：-PipIndex > 环境变量 SPIRITSCOUT_PIP_INDEX > 默认镜像。
    # 关键字 official / pypi / default 表示「用官方源」，便于临时排障。
    $raw = $value
    if (-not $raw) { $raw = $env:SPIRITSCOUT_PIP_INDEX }
    if (-not $raw) { return $script:MirrorIndex }
    $raw = $raw.Trim()
    if (-not $raw) { return $script:MirrorIndex }
    $lower = $raw.ToLowerInvariant()
    if (@('official', 'pypi', 'default') -contains $lower) { return $script:OfficialIndex }
    if ($raw -notmatch '^https?://') {
        throw "-PipIndex 要给完整地址（例如 https://pypi.tuna.tsinghua.edu.cn/simple），收到：$raw"
    }
    return $raw
}

$script:pipIndex = Resolve-PipIndex $PipIndex

function Get-IndexLabel([string]$index) {
    # 标签跟着实际源走：自定义镜像不能还挂着「清华」的名
    if ($index -eq $script:OfficialIndex) { return 'PyPI 官方源' }
    if ($index -eq $script:MirrorIndex) { return $script:MirrorLabel }
    return '自定义源'
}

if ($ShowPipIndex) {
    Write-Host "PIP_INDEX=$script:pipIndex"
    Write-Host "PIP_INDEX_LABEL=$(Get-IndexLabel $script:pipIndex)"
    exit 0
}


# 提示与自装共用同一份命令文本，免得两处写歪
$cmdCore = "SpiritScout\.venv\Scripts\python.exe -m pip install --index-url $script:pipIndex -e `"SpiritScout`""
$cmdToolkit = "SpiritScout\.venv\Scripts\python.exe -m pip install --index-url $script:pipIndex -e `"SpiritScout[toolkit]`""

function Find-HostPython {
    # 本机 py 启动器里可用的 3.11+。取版本号最低的那个：工具包里的 gmpy2 / z3-solver
    # 在新 Python 上常常还没有预编译轮子，跟着最新版走容易把自装卡在源码编译上。
    $lines = @()
    try { $lines = @(& py -0p 2>$null) } catch { }
    $found = foreach ($line in $lines) {
        if ($line -match '-V:(\d+\.\d+)') {
            $v = [version]$Matches[1]
            if ($v -ge $minPython) { [pscustomobject]@{ Version = $v; Tag = $Matches[1] } }
        }
    }
    $sorted = @($found | Sort-Object Version)
    if ($sorted.Count -eq 0) { return $null }
    return $sorted[0].Tag
}

function Get-Deps {
    # 探针只读 importlib.metadata，几十毫秒；返回 $null 表示「读不出结论」
    if (-not (Test-Path $depsProbe)) { return $null }
    $json = & $venvPy -X utf8 $depsProbe --toolkit --json 2>$null | Out-String
    if (-not $json -or -not $json.Trim()) { return $null }
    try { return $json | ConvertFrom-Json } catch { return $null }
}

function Invoke-PipInstall {
    # 在仓库根执行 pip install -e <Target>，把退出码交给调用方决定拦不拦启动。
    #
    # 输出必须逐行 Write-Host，不能用 Out-Host：双击入口之外还有
    # `powershell -File … > 日志` 这种重定向场景，Out-Host 在没有交互宿主时
    # 无处可写，pip 的下载进度和报错全都看不见，只剩一个静默挂死的窗口。
    # --retries/--timeout 让断网时的最坏耗时收敛到几十秒，而不是无限等。
    # 源：先走解析出的镜像；镜像挂了（同步延迟、被墙、限流）自动退官方源重试一次，
    # 并把后续步骤也切到官方源——免得每次都先撞一面墙再回来。
    param([string]$Target)

    function Invoke-Pip([string]$index) {
        $pipArgs = @('-m', 'pip', 'install', '--disable-pip-version-check',
                     '--retries', '2', '--timeout', '30')
        if ($index) { $pipArgs += @('--index-url', $index) }
        $pipArgs += @('--editable', $Target)
        & $venvPy @pipArgs | ForEach-Object { Write-Host $_ }
        return $LASTEXITCODE
    }

    Push-Location $root
    try {
        $code = Invoke-Pip $script:pipIndex
        if ($code -ne 0 -and $script:pipIndex -ne $script:OfficialIndex) {
            Write-Host "[!] 镜像 $script:pipIndex 装不下（退出码 $code），改用官方源重试一次…" -ForegroundColor Yellow
            $code = Invoke-Pip $script:OfficialIndex
            if ($code -eq 0) {
                $script:pipIndex = $script:OfficialIndex
                Write-Host "[i] 官方源通了；本次启动后续都走 $script:OfficialIndex" -ForegroundColor DarkGray
            }
        }
        return $code
    } finally { Pop-Location }
}

# 1) 环境自检。venv 在不在、解释器跑不跑得起来、版本够不够——这几样缺任何
#    一样都没法「自动补」，只能给精确命令。
if (-not (Test-Path $venvPy)) {
    Write-Host "[x] 缺虚拟环境：SpiritScout\.venv" -ForegroundColor Red
    $hostPy = Find-HostPython
    if ($hostPy) {
        Write-Host "[i] 本机有 Python $hostPy，建一个（装在哪由你定，启动器不代劳）：" -ForegroundColor Yellow
        Write-Host "        py -$hostPy -m venv SpiritScout\.venv"
        Write-Host "    建完再跑一次本脚本，缺的运行依赖它会自己 pip 装齐。"
    } else {
        Write-Host "[x] 而且本机 py 启动器里没有 3.11 或更高的解释器，先装 Python：" -ForegroundColor Red
        Write-Host "        winget install -e --id Python.Python.3.11"
        Write-Host "    或到 https://www.python.org/downloads/ 装 3.11，安装时勾 Add python.exe to PATH。"
    }
    exit 1
}

$pyVersion = $null
try {
    $pyVersion = & $venvPy -X utf8 -c "import sys; print(str(sys.version_info[0]) + '.' + str(sys.version_info[1]))" 2>$null
} catch { }
if (-not $pyVersion) {
    Write-Host "[x] SpiritScout\.venv 里的 python.exe 跑不起来" -ForegroundColor Red
    Write-Host "    通常是整个目录被移动过，或底下的解释器被卸载/升级了。删掉重建："
    Write-Host "        Remove-Item -Recurse -Force SpiritScout\.venv"
    Write-Host "        py -3.11 -m venv SpiritScout\.venv"
    exit 1
}
if ([version]$pyVersion -lt $minPython) {
    Write-Host "[x] 虚拟环境是 Python $pyVersion，灵枢需要 3.11 或更高" -ForegroundColor Red
    Write-Host "    旧 venv 换不了底层解释器，删掉重建："
    Write-Host "        Remove-Item -Recurse -Force SpiritScout\.venv"
    Write-Host "        py -3.11 -m venv SpiritScout\.venv"
    exit 1
}

# 2) 依赖自检与自动补装。缺依赖、或本体没装进 venv（这时 -m spiritscout 会
#    直接找不到模块），默认就地 pip 装并复验；只有 -NoInstall 才退回纯提示。
$deps = Get-Deps
if (-not $deps) {
    # 旧版本仓库没有探针脚本，或它跑挂了：只核对过 Python 版本，其余交给运行时去报错
    Write-Host "[!] 依赖探针没给出结论（SpiritScout\scripts\probe_deps.py 缺失或执行失败），跳过依赖自检" -ForegroundColor Yellow
    $missing = @()
    $missingToolkit = @()
} else {
    $missing = @($deps.runtime_missing)
    $missingToolkit = @($deps.toolkit_missing)

    # 先报源码版本：跑的是 src/ 下的当前代码，与 --version 同源。editable 装的
    # .dist-info 是当初 pip 打的快照，源码升版本后它还写着旧号，所以两者不一致时
    # 再单独提一句（只提示，不拦启动；重装一次即可对齐）。
    if ($deps.source_version) {
        Write-Host "[i] 源码版本：灵枢 v$($deps.source_version)（SpiritScout\src 当前代码）" -ForegroundColor DarkGray
    }
    $srcLabel = Get-IndexLabel $script:pipIndex
    Write-Host "[i] 依赖源：$srcLabel（$script:pipIndex；换源用 -PipIndex <url> 或环境变量 SPIRITSCOUT_PIP_INDEX）" -ForegroundColor DarkGray
    if ($deps.self_version -and $deps.source_version -and
        ($deps.self_version -ne $deps.source_version)) {
        Write-Host "[i] 安装元数据 $($deps.self_version) 落后于源码 $($deps.source_version)" -ForegroundColor DarkGray
        Write-Host "    （editable 指向 src/，起的服务是源码版本；想对齐就重装一次：$cmdCore）"
    }

    if (-not $deps.pip) {
        Write-Host "[x] 这个 venv 里没有 pip，自动补装无从谈起。先修它：" -ForegroundColor Red
        Write-Host "        SpiritScout\.venv\Scripts\python.exe -m ensurepip --upgrade"
        Write-Host "    修不好就删了重建：Remove-Item -Recurse -Force SpiritScout\.venv"
        exit 1
    }

    if ($missing.Count -gt 0 -or -not $deps.self_version) {
        if ($missing.Count -gt 0) {
            Write-Host "[x] 缺 $($missing.Count) 个运行依赖：$($missing -join ', ')" -ForegroundColor Red
        }
        if (-not $deps.self_version) {
            Write-Host "[x] 灵枢本体没装进这个 venv，-m spiritscout 起不来" -ForegroundColor Red
        }
        if ($NoInstall) {
            Write-Host "[x] 带了 -NoInstall，不自动装。手工执行：" -ForegroundColor Red
            Write-Host "        $cmdCore"
            exit 1
        }
        Write-Host "[>] 自动补装运行依赖（首次要几分钟，别关窗口）…" -ForegroundColor Cyan
        $code = Invoke-PipInstall 'SpiritScout'
        if ($code -ne 0) {
            Write-Host "[x] pip 安装失败（退出码 $code），常见原因是网络、代理或镜像没同步" -ForegroundColor Red
            Write-Host "    换官方源试：start-local.ps1 -PipIndex official" -ForegroundColor Red
            Write-Host "    换别的镜像：start-local.ps1 -PipIndex https://mirrors.aliyun.com/pypi/simple/" -ForegroundColor Red
            Write-Host "    手工执行：$cmdCore"
            exit 1
        }
        # 装完必须复验：pip 报成功但装到了别的环境、或依赖冲突回滚，都会留在这里
        $deps = Get-Deps
        $missing = @($deps.runtime_missing)
        $missingToolkit = @($deps.toolkit_missing)
        if (-not $deps -or $missing.Count -gt 0 -or -not $deps.self_version) {
            $still = '未知（探针读不出结果）'
            if ($deps) { $still = ($missing -join ', ') }
            Write-Host "[x] 装完仍不可用，还缺：$still" -ForegroundColor Red
            Write-Host "    确认装进了这个 venv：SpiritScout\.venv\Scripts\python.exe -m pip list | Select-String spiritscout"
            exit 1
        }
        Write-Host "[+] 运行依赖已装好（灵枢 $($deps.self_version)）" -ForegroundColor Green
    }

    # 工具包是可选组，缺了不影响启动，但 CTF 的 pwn/crypto 环节会缺工具。
    # 装不上只降级工具链，不拦启动——本体与运行依赖这一步已经齐了。
    if ($missingToolkit.Count -gt 0) {
        Write-Host "[!] 可选工具包不全（CTF 的 pwn/crypto 会缺工具）：$($missingToolkit -join ', ')" -ForegroundColor Yellow
        if ($NoInstall) {
            Write-Host "    需要时装：$cmdToolkit"
        } else {
            Write-Host "[>] 自动补装工具包（pwntools / z3 / gmpy2 等，体积不小）…" -ForegroundColor Cyan
            $code = Invoke-PipInstall 'SpiritScout[toolkit]'
            $after = Get-Deps
            if ($after) { $missingToolkit = @($after.toolkit_missing) }
            if ($missingToolkit.Count -gt 0) {
                Write-Host "[!] 工具包仍缺 $($missingToolkit.Count) 个：$($missingToolkit -join ', ')（不影响启动）" -ForegroundColor Yellow
                if ($code -ne 0) { Write-Host "    pip 退出码 $code；手工试：$cmdToolkit" }
            } else {
                Write-Host "[+] 工具包已补齐" -ForegroundColor Green
            }
        }
    }
}

$systemCfg = Join-Path $root 'SpiritScout\configs\system.yaml'
if (-not (Test-Path $systemCfg)) {
    Write-Host "[x] 缺配置文件：SpiritScout\configs\system.yaml" -ForegroundColor Red
    Write-Host "    copy SpiritScout\configs\system.example.yaml SpiritScout\configs\system.yaml"
    exit 1
}

# 端口被占是启动失败最常见的原因（多半是上一次的控制台没退干净），
# 提前查出来，比让 uvicorn 抛 WinError 10048 清楚。
try {
    if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
        Write-Host "[x] 端口 $Port 已被占用（常见于上次没退干净的控制台）" -ForegroundColor Red
        Write-Host "    看是谁：Get-NetTCPConnection -LocalPort $Port | Select-Object OwningProcess"
        Write-Host "    或换端口：start-local.ps1 -Port $($Port + 1)"
        exit 1
    }
} catch { }

Write-Host "[+] 依赖自检通过（Python $pyVersion，运行依赖齐全）" -ForegroundColor Green
if ($missingToolkit.Count -eq 0) { Write-Host "    可选工具包也齐全" }

# 1) 模型渠道：优先自定义 OpenAI 兼容渠道（SPIRITSCOUT_REMOTE_LLM_KEY），
#    没有再退回本机 DSH 网关。key 只进环境变量，不写文件。
$remoteKey = $env:SPIRITSCOUT_REMOTE_LLM_KEY
if ($remoteKey) {
    Write-Host "[+] 使用自定义渠道 key（SPIRITSCOUT_REMOTE_LLM_KEY）"
} else {
    $gateway = 'http://127.0.0.1:18923/v1'
    if (-not $env:SPIRITSCOUT_LOCAL_LLM_KEY) {
        $settings = Join-Path $env:USERPROFILE '.dsh\our-free-model\settings.json'
        if (Test-Path $settings) {
            $raw = Get-Content $settings -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
            if ($raw -and $raw -match '"forwardKey"\s*:\s*"([^"]+)"') { $env:SPIRITSCOUT_LOCAL_LLM_KEY = $Matches[1] }
        }
    }
    if (-not $env:SPIRITSCOUT_LOCAL_LLM_KEY) {
        # 没有 key 不拦启动：控制台的「模型」页可以给供应商填 key，密钥进本机
        # 加密密钥库，比环境变量更好管。这里只提示，不退出。
        Write-Host "[i] 没取到模型 key：控制台照常启动，进去后到「模型」页填即可。" -ForegroundColor Yellow
    }
    try {
        $models = Invoke-RestMethod "$gateway/models" -Headers @{ Authorization = "Bearer $env:SPIRITSCOUT_LOCAL_LLM_KEY" } -TimeoutSec 5
        Write-Host "[+] 本机网关可用，模型 $(@($models.data).Count) 个：$((($models.data | Select-Object -First 3).id) -join ', ')…"
    } catch {
        Write-Host "[!] 本机网关 $gateway 不可达或 key 无效：$($_.Exception.Message)" -ForegroundColor Yellow
    }
}

# 2) 执行后端：本机 host（无 bwrap 时的默认；显式写死便于审计对照）
$env:SPIRITSCOUT_SANDBOX_BACKEND = 'host'
$env:SPIRITSCOUT_EXECUTOR__SANDBOX_BACKEND = 'host'
$env:PYTHONUNBUFFERED = '1'
if ($Debug) { $env:SPIRITSCOUT_LOG_LEVEL = 'DEBUG' }

Write-Host "[+] 执行后端 host（工作目录锁定 + 运行期 ACL 收口 + 环境白名单 + 超时杀进程树；仍无读隔离）"
Push-Location (Join-Path $root 'SpiritScout')
# 3) 管理员账号：首次启动让本人当场设密码，只把 scrypt 哈希写进工作区 admin.db。
#    已有账号就跳过；不是交互终端（脚本/CI 调用）时同样跳过，绝不卡住启动。
Write-Host "[>] 管理员账号：首次启动在这里设置密码（明文只在设完后显示一次，不落盘，只存哈希）"
Write-Host "    长度不限；不想设就回车两次跳过（auth_mode=none 下不设也能直接进，随时可补）" -ForegroundColor DarkGray
& $venvPy -X utf8 -m spiritscout --set-admin-password --if-missing --config configs\system.yaml
if ($LASTEXITCODE -ne 0) {
    Write-Host "    [!] 没设置管理员密码：控制台仍只在回环地址可用；" -ForegroundColor Yellow
    Write-Host "        之后可手动补：SpiritScout\.venv\Scripts\python.exe -m spiritscout --set-admin-password" -ForegroundColor Yellow
}

Write-Host "[>] 控制台：http://127.0.0.1:$Port"
Write-Host "    模型页应已看到 configs/models.yaml 里配置的模型。"
Write-Host "[>] 前台运行中：关闭本窗口（或按 Ctrl+C）即停止控制台" -ForegroundColor Cyan
try {
    & $venvPy -X utf8 -m spiritscout --config configs\system.yaml --port $Port
} finally {
    Pop-Location
}
