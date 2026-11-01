"""组装「解压即用」发布包（自带 Python + 全套依赖）。

    SpiritScout-<ver>-portable\
    ├── 1-启动服务.bat         起 Web 控制台（http://127.0.0.1:8010）
    ├── 2-停止服务.bat         按端口收口残留进程
    ├── 使用说明.txt
    ├── runtime\               精简 CPython 3.11 + Lib\site-packages（同时充当 venv 形状）
    ├── app\                   程序本体（src / docs / scripts / 许可证）
    ├── configs\               system.yaml / models.yaml / agent_models.yaml
    └── data\                  运行数据（会话、审计、报告、密钥库）

为什么 configs 放包根：`python -m spiritscout` 的 --config、models_config_path、
以及宿主后端的 .venv 探测都按「当前工作目录 / 项目根」解析。仓库里跑的就是
「cwd = 项目根、configs 在根下」，包内保持一致最不容易踩坑；data\ 只用配置项
显式指过去，不改代码。
"""
from __future__ import annotations

import os
import re
import shutil
import stat
import sys
import zipfile
from pathlib import Path

ROOT = Path(r"C:\Users\admin\Desktop\全自动打靶")
PROJ = ROOT / "SpiritScout"
OUT = ROOT / "packages"
SRC_PY = Path(r"C:\Users\admin\AppData\Local\Programs\Python\Python311")
VENV_SP = PROJ / ".venv" / "Lib" / "site-packages"

VERSION = (PROJ / "src" / "spiritscout" / "__init__.py").read_text(
    encoding="utf-8").split('__version__ = "')[1].split('"')[0]
NAME = f"SpiritScout-{VERSION}-portable"
STAGE = OUT / NAME

# 进 app\ 的内容（其余是构建/开发产物，发布包里没有意义）
APP_INCLUDE = ["src", "docs", "scripts", "README.md", "CHANGELOG.md",
               "SECURITY.md", "LICENSE", "pyproject.toml", ".env.example"]
APP_IGNORE = shutil.ignore_patterns("__pycache__", "*.egg-info", "*.pyc")

# 标准库只留运行时真正会用到的东西
STDLIB_DROP = {"test", "tests", "idlelib", "tkinter", "turtledemo", "ensurepip",
               "lib2to3", "Doc", "Tools", "site-packages", "__pycache__"}

VCRT = ("msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll",
        "msvcp140_atomic_wait.dll", "msvcp140_codecvt_ids.dll",
        "concrt140.dll", "vcruntime140.dll", "vcruntime140_1.dll",
        "vcruntime140_threads.dll")


def onerror(func, path, exc):  # noqa: ANN001
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        print(f"    ! 删不掉 {path}")


def rm(p: Path) -> None:
    if p.exists():
        shutil.rmtree(p, onerror=onerror)


def mb(p: Path) -> float:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) / 1048576


def nfiles(p: Path) -> int:
    return sum(1 for f in p.rglob("*") if f.is_file())


def cp(src: Path, dst: Path) -> None:
    shutil.copy2(src, dst)


# ------------------------------------------------------------------ 1) runtime
def build_runtime():
    runtime = STAGE / "runtime"
    runtime.mkdir(parents=True)

    for name in ("python.exe", "pythonw.exe", "python311.dll", "python3.dll",
                 "python311.zip", "python311._pth"):
        src = SRC_PY / name
        if src.exists() and name != "python311._pth":
            cp(src, runtime / name)

    # VC++ 运行时整套同版本：Python 目录自带的 vcruntime140 是 14.34，系统
    # msvcp140 是 14.5x，混用会「ImportError: DLL load failed」且没有细节。
    sys32 = Path(os.environ["WINDIR"]) / "System32"
    for name in VCRT:
        src = sys32 / name
        if src.exists():
            cp(src, runtime / name)
        else:
            print(f"    ! 系统缺少 {name}")

    shutil.copytree(SRC_PY / "DLLs", runtime / "DLLs", dirs_exist_ok=True)
    shutil.copytree(SRC_PY / "Lib", runtime / "Lib", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(*STDLIB_DROP))
    (runtime / "Lib" / "site-packages").mkdir(parents=True, exist_ok=True)

    # venv 形状：sandbox.py 的 _project_venv() 只认 <venv>\Scripts\python.exe。
    # Scripts\python.exe 没有 pyvenv.cfg 时会靠 landmark（Lib\os.py）上溯一层，
    # 于是 prefix 自然落回 runtime\，标准库与 site-packages 都对得上；
    # python311.dll 必须同目录一份，否则 exe 起不来。
    scripts = runtime / "Scripts"
    scripts.mkdir()
    for name in ("python.exe", "pythonw.exe", "python311.dll", "python3.dll"):
        src = runtime / name
        if src.exists():
            cp(src, scripts / name)
    print(f"  runtime 基础层 {mb(runtime):.0f} MB")


def build_site_packages():
    sp = STAGE / "runtime" / "Lib" / "site-packages"
    shutil.copytree(VENV_SP, sp, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
    # 编辑安装留下的 .pth 指向构建机绝对路径，留着会让 import spiritscout
    # 解析到不存在的目录（甚至回连构建机），必须清掉
    for p in list(sp.glob("__editable__*")) + list(sp.glob("*editable*finder*")):
        p.unlink(missing_ok=True)
        print(f"    清掉编辑安装残留 {p.name}")
    for d in list(sp.glob("spiritscout-*.dist-info")):
        rm(d)
        print(f"    清掉旧版本元数据 {d.name}")
    for p in sp.glob("*.chm"):
        p.unlink(missing_ok=True)
    removed = 0
    for name in ("tests", "test"):
        for d in list(sp.rglob(name)):
            if d.is_dir() and d.parent != sp:
                rm(d)
                removed += 1
    print(f"  site-packages {mb(sp):.0f} MB（清理 {removed} 个包内 tests/）")


# ---------------------------------------------------------------------- 2) app
def build_app():
    app = STAGE / "app"
    app.mkdir()
    for name in APP_INCLUDE:
        src = PROJ / name
        if not src.exists():
            print(f"    ! 缺 {src}")
            continue
        if src.is_dir():
            shutil.copytree(src, app / name, ignore=APP_IGNORE)
        else:
            cp(src, app / name)
    print(f"  app {mb(app):.1f} MB / {nfiles(app)} 文件")


# ------------------------------------------------------------------ 3) configs
def build_configs():
    """配置文件放包根，数据落 data\\。

    只改「数据落点」和「包内没有的 MCP 服务器」，其余与仓库一致——发布的
    配置就是作者实测跑过的那份，不是另写一份。
    """
    cfg = STAGE / "configs"
    cfg.mkdir()
    text = (PROJ / "configs" / "system.yaml").read_text(encoding="utf-8")

    data_paths = {
        r"(?m)^(\s*)root:\s*\.spiritscout\b.*$": r"\g<1>root: data/workspace",
        r"(?m)^(\s*)sqlite_path:\s*\.spiritscout/blackboard\.db\b.*$":
            r"\g<1>sqlite_path: data/workspace/blackboard.db",
        r"(?m)^(\s*)sqlite_path:\s*\.spiritscout/knowledge\.db\b.*$":
            r"\g<1>sqlite_path: data/workspace/knowledge.db",
        r"(?m)^(\s*)chroma_path:\s*\.spiritscout/chroma\b.*$":
            r"\g<1>chroma_path: data/workspace/chroma",
        r"(?m)^(\s*)output_dir:\s*\.spiritscout/reports\b.*$":
            r"\g<1>output_dir: data/workspace/reports",
        r"(?m)^(\s*)audit_log_path:\s*\.spiritscout/audit\.jsonl\b.*$":
            r"\g<1>audit_log_path: data/workspace/audit.jsonl",
    }
    for pat, rep in data_paths.items():
        text, n = re.subn(pat, rep, text)
        if n != 1:
            raise SystemExit(f"数据落点改写失败（{n} 处）：{pat}")

    # ida / yakit 需要 .venv 里的 idalib、项目 .tools 里的 yak 引擎，包内没有，
    # 留着每次开会话都会留一次「不可达」痕迹，直接摘掉（注释里保留说明）。
    for name in ("ida", "yakit"):
        text, n = re.subn(rf"(?ms)^  - name: {name}\b.*?(?=^  - name: )", "", text)
        if n != 1:
            raise SystemExit(f"摘除 MCP {name} 失败（{n} 处）")

    text = text.replace(
        "# 灵枢（SpiritScout）系统配置示例",
        "# 灵枢（SpiritScout）系统配置 —— 便携版\n"
        "# 数据落点已指向 data\\workspace（相对包根目录，整体搬迁不受影响）。\n"
        "# 原配置里的 ida / yakit 两个 MCP 服务器需要项目 .venv、.tools，本包未附带，已摘除；\n"
        "# 需要时照 docs/部署与配置.md 自行加回。", 1)
    (cfg / "system.yaml").write_text(text, encoding="utf-8")

    # 模型注册表：发布版不预置任何真实 key，只留一个 OpenAI 兼容供应商骨架
    (cfg / "models.yaml").write_text("""\
# 模型注册表 —— 灵枢（SpiritScout）便携版
#
# 这里不存任何密钥。填 key 走 Web 控制台「模型」页：选中供应商 → 填 API Key
# → 保存（加密进本机密钥库 data\\workspace\\vault.db，重启仍有效）。
#
# 首次使用的两条路：
#   A. 有 OpenAI 兼容端点（方舟 / DeepSeek / 通义 / OpenRouter / 中转站都算）：
#      「模型」页 →「添加供应商」→ 选预设或手填 base_url → 填 key →
#      「获取模型列表」勾选模型 → 「编队」页把模型指派给 Agent。
#   B. 本机起推理服务（LM Studio / Ollama / llama.cpp）：
#      保持下面 local 供应商的 base_url，填模型 ID 即可。
#
# 也可以直接改本文件（格式参考 configs/models.example.yaml），改完重启控制台。

providers:
  - name: openai
    provider: openai_compatible
    base_url: https://api.openai.com/v1
    api_key: ''
    api_format: chat_completions

  - name: local
    provider: openai_compatible
    base_url: http://127.0.0.1:1234/v1
    api_key: ''
    api_format: auto

models: []
""", encoding="utf-8")

    (cfg / "agent_models.yaml").write_text(
        "# Agent 模型分配表 —— 由 Web「编队」页维护，可手工编辑。\n"
        "# 模型要先在 configs/models.yaml 注册并启用，这里才指派得上。\n"
        "assignments: {}\nnaming: []\n", encoding="utf-8")

    for name in ("system.example.yaml", "models.example.yaml", "models.mock.yaml"):
        src = PROJ / "configs" / name
        if src.exists():
            cp(src, cfg / name)
    print(f"  configs {nfiles(cfg)} 文件")


# ----------------------------------------------------------------- 5) 启动脚本
START = """@echo off
chcp 65001 >nul
title SpiritScout __VER__
cd /d "%~dp0"

rem Keep this file ASCII-only, UTF-8 without BOM, CRLF: cmd reads batch files by
rem byte offset, and multi-byte text inside rem lines can shift line boundaries.

set "VIRTUAL_ENV=%~dp0runtime"
set "PYTHONPATH=%~dp0app\\src"
set "PYTHONUTF8=1"
set "PYTHONNOUSERSITE=1"
set "PYTHONIOENCODING=utf-8"
rem Do not fetch litellm's remote model-cost table: unreachable hosts cost 3
rem retries of a few seconds each, and the built-in table is used anyway.
set "LITELLM_LOCAL_MODEL_COST_MAP=True"

if not exist "%~dp0data" mkdir "%~dp0data"

echo.
echo   SpiritScout __VER__   Web console  ^|  http://127.0.0.1:8010
echo   Close this window to stop it.
echo.

rem First run: let the owner pick the console admin password. Only a scrypt hash
rem is written, to data/workspace/admin.db - nothing is shipped and no plaintext
rem ever touches disk. Press Enter twice to skip; the console then stays
rem loopback-only. Existing accounts are kept as-is (--if-missing).
if not exist "%~dp0data\\workspace\\admin.db" (
  echo   [first run] Set the console admin password ^(input is hidden^).
  echo   [first run] Press Enter twice to skip - console stays local-only.
  "%~dp0runtime\\python.exe" -X utf8 -m spiritscout --set-admin-password --if-missing --config "%~dp0configs\\system.yaml"
  echo.
)

start "" "http://127.0.0.1:8010"
"%~dp0runtime\\python.exe" -X utf8 -m spiritscout --config "%~dp0configs\\system.yaml" --port 8010
if errorlevel 1 (
  echo.
  echo   [ERROR] console exited. See messages above.
  pause
)
"""

STOP = """@echo off
chcp 65001 >nul
echo Stopping SpiritScout (port 8010) ...
for %%P in (8010) do (
  for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%%P" ^| findstr LISTENING') do (
    echo   port %%P -^> kill PID %%a
    taskkill /F /T /PID %%a >nul 2>&1
  )
)
echo Done.
pause
"""

README = """灵枢（SpiritScout）v__VER__ 便携版 —— 解压即用的自动打靶系统
================================================================

不用装 Python、不用装依赖、不用联网装环境：解压后双击「1-启动服务.bat」即可。

一、三步开始
------------
1. 双击「1-启动服务.bat」
   - 会弹出一个黑窗口（服务本体，别关；关掉=停服务）
   - **第一次启动会让你设控制台管理员密码**：密码输入不回显，只把 scrypt 加盐
     哈希写进 data\\workspace\\admin.db，明文不落盘、也不进包。直接回车两次
     表示跳过——那样控制台只绑本机 127.0.0.1，别的机器进不来。
   - 浏览器自动打开 http://127.0.0.1:8010
2. 用刚才设的用户名/密码登录（默认用户名 spiritscout，可在设密码时改）
3. 进控制台 → 侧栏「模型」→ 选供应商填 API Key → 「获取模型列表」勾选模型
   → 「编队」页把模型指派给 Agent。密钥加密存进 data\\workspace\\vault.db，
   重启后仍有效。没 key 时也可以先把 configs\\models.mock.yaml 复制成
   configs\\models.yaml 重启，用模拟模型把界面点一遍（模拟模型是确定性应答，
   不会真解题）。

二、跑一轮自动打靶（验证环境是否真的通了）
------------------------------------------
控制台里新建任务，模式选 CTF/比赛，正文贴这两段：
  1) 平台适配器档案（PlatformAdapter 需要的端点定义，见 app\\docs 的架构与执行流程篇）
  2) 你有授权的目标地址
本包不含靶场，请对接自己的比赛平台或已授权环境。
产物：data\\workspace\\sessions\\<会话>\\flags.json、reports\\ctf_writeup_*.md、
audit.jsonl（每次模型调用与工具调用都可回溯）。

三、包内结构
------------
  runtime\\      自带 Python 3.11 + 全部依赖（litellm / fastapi / pwntools / scapy
                / capstone / z3 / sqlmap / opencv 等），不依赖系统解释器
  app\\          程序本体（src / docs / scripts）
  configs\\      system.yaml（系统配置）、models.yaml（模型注册表）、agent_models.yaml
  data\\         运行数据：会话、审计、报告、密钥库。备份搬机就拷这个目录
                （出厂只有做题经验库；管理员密码库 admin.db 等是你本地
                 第一次启动后才生成的，不会随包发出去）

四、包里自带的做题经验
----------------------
两个层次，都在包里，装上就能用，不需要额外下载：

1) 知识库（静态参考事实，随 app 一起分发）
   app\\src\\spiritscout\\knowledge\\data\\security_skills.json（约 645 KB）
     —— 各方向的手法索引：Web / Pwn / Reverse / Crypto / Misc / 取证等，
        按「怎么做」组织，由模型按实际情况取用。
   app\\src\\spiritscout\\knowledge\\seed.py
     —— 结构化的种子知识：平台特性、载荷形态、常见坑位。

2) 经验库（跨会话积累的实战判断，预置 + 自增长）
   data\\workspace\\experience.db
     —— 出厂已预置一批实战洞察（表 insights），记的是「怎么判读」而不是
        「打什么」。例如：云靶场实例回收后坐标不再指向同一环境、连接超时
        在按需实例上该先当成实例生命周期信号而不是目标防护、零轮次战报
        不能当作难度或防护强度的证据、赛事入口令牌过期与靶场下线难以
        区分、赛事接入层与题目实例层的可达性互不蕴含。
     —— 每条带：insight（一句话洞察）、context（适用场景）、tags（标签）、
        source_session（来源会话）、source_model、ts。

经验怎么接着长
--------------
每次任务收尾，模型从这次实战里提炼洞察写进 experience.db；下个任务开工
时自动召回最多 6 条（configs\\system.yaml 的 experience.recall_limit）注入
上下文。用得越久，判读越贴合你实际打过的环境。

想归零：删掉 data\\workspace\\experience.db，下次启动重建空库。
        （知识库那两个文件在 app\\ 里，删了会丢内置参考，别动。）
想带走：连 data\\ 一起拷，经验跟着走。

停止服务
--------
关掉那个黑窗口，或双击「2-停止服务.bat」（按端口收口，含残留进程）。

管理员密码（第一次启动就设好，包里不含任何凭据）
----------------------------------------------
- 首次双击「1-启动服务.bat」时在黑窗口里设置：先问用户名（直接回车=spiritscout），
  再输两遍密码（不回显）。密码至少 8 个字符。
- 存哪：data\\workspace\\admin.db（表 admins，password_hash 形如
  scrypt$16384$8$1$盐$哈希）。登录后的会话 Cookie 用 data\\workspace\\auth.key
  里的随机密钥签名。**这两个文件都是本地生成的，打包时会被清掉，包里没有。**
- 明文不落盘：输入不回显，不进命令行参数，不写日志；包内 py 代码只有校验逻辑。
- 忘了密码 / 想换一个：
      删掉 data\\workspace\\admin.db，重新双击启动（会再问一次）
  或手动覆盖同名账号：
      runtime\\python.exe -m spiritscout --set-admin-password --config configs\\system.yaml
- 不想设也能用：直接回车两次跳过，控制台只绑 127.0.0.1，别的机器进不来。

五、常见问题
------------
- shell 工具报「没有可用 shell」：Windows 上建议装 Git for Windows（自带
  bash，系统自动找得到）；没装会退到 cmd.exe，多数命令仍能跑。
- python 工具报不可用：确认没有动过 runtime\\ 目录；包内 python 在
  runtime\\python.exe，沙箱按 VIRTUAL_ENV=runtime 找到它。
- 浏览器自动化（playwright / chrome 两个 MCP）要 Node.js + npx；没装只是这两个
  工具不可用，不影响解题与打靶。
- 端口被占：改「1-启动服务.bat」里的 --port 8010。
- 想给局域网别的机器访问：先在首次启动时设好管理员密码，再把
  configs\\system.yaml 里的 web.host 改成 0.0.0.0 重启（没设密码时非回环绑定
  会被拒绝启动，这是有意的）。首次会被防火墙拦，选允许。
- 想用环境变量喂密码（写在 .env 或 set）：SPIRITSCOUT_ADMIN_USERNAME /
  SPIRITSCOUT_ADMIN_PASSWORD 仍被支持，启动时会同步进 admin.db；旧变量名
  SPIRITSCOUT_SERVER_PASSWORD 也认。日常不建议——明文留在环境里，不如第一次
  启动时设的那份哈希。
- 目录别放 C:\\Program Files（控制台要写 configs\\models.yaml，Program Files
  默认不可写）；桌面、D 盘、U 盘都行，路径带中文没问题。
- 杀软对打包了 python + pwntools 的目录偶尔会拦：加信任/排除即可，包内没有
  联网二进制，全部依赖都是纯本地代码。
- 只支持 Windows 10/11 64 位。

六、安全边界（务必知道）
------------------------
- 执行后端是 host：进程锁在会话目录内、环境变量白名单、超时杀进程树，但
  **没有文件系统读隔离**（宿主其它可读路径仍可读）。别拿它跑不明来源的脚本，
  或多租户共用。
- 测试边界由模型按你的任务描述维护；只在自己有授权的目标上使用。
- 系统内置的模型调用与工具调用全部写审计（data\\workspace\\audit.jsonl）。
"""
README = README.replace("__VER__", VERSION)


def write_crlf(path: Path, text: str, encoding: str = "utf-8") -> None:
    """写成品脚本/说明：统一 CRLF，并拦住悄悄混进来的控制字符。

    模板是普通字符串，`\\a` `\\b` `\\t` 这类转义一旦漏掉一个反斜杠就会变成真正的
    控制字符（曾经把 `data\\workspace\\admin.db` 写成 BEL + `dmin.db`，cmd 里看不出
    毛病但文件已经坏了）。宁可构建失败，也不发一个带隐藏字节的包。
    """
    body = text.replace("\r\n", "\n").replace("\n", "\r\n")
    bad = sorted({ch for ch in body if ord(ch) < 32 and ch not in "\r\n\t"})
    if bad:
        raise SystemExit(
            f"{path.name} 里出现控制字符 {[hex(ord(c)) for c in bad]}——"
            "检查模板里的反斜杠转义")
    path.write_bytes(body.encode(encoding))


def build_scripts():
    write_crlf(STAGE / "1-启动服务.bat", START.replace("__VER__", VERSION))
    write_crlf(STAGE / "2-停止服务.bat", STOP)
    # 说明文件带 BOM：老版本记事本也认得出 UTF-8
    write_crlf(STAGE / "使用说明.txt", README, encoding="utf-8-sig")
    data_root = STAGE / "data"
    data_root.mkdir(exist_ok=True)
    workspace = data_root / "workspace"
    workspace.mkdir(exist_ok=True)

    # 预置做题经验：仓库里积累的 insights 随包发出去，收包的人开箱就带着
    # 这些判读经验，不用从零攒。experience.root 留空即跟随工作区，所以
    # 直接放到 workspace 下就会被认到。
    seed_exp = PROJ / ".spiritscout" / "experience.db"
    if seed_exp.exists():
        shutil.copy2(seed_exp, workspace / "experience.db")
        try:
            import sqlite3
            con = sqlite3.connect(workspace / "experience.db")
            count = con.execute("SELECT COUNT(*) FROM insights").fetchone()[0]
            con.close()
            print(f"  预置做题经验 {count} 条（experience.db）")
        except Exception:
            print("  预置做题经验 experience.db")

    # 出厂包不带任何本机凭据：管理员哈希库、会话签名密钥、密钥库都可能已经被
    # 开发机自己用过（admin.db 里有设过的密码哈希、vault.key 能解本地 key）。
    # 收包的人必须自己设密，所以这里一律清掉——不是可以商量的打包选项。
    for name in CREDENTIAL_FILES:
        for candidate in (workspace / name, data_root / name):
            if candidate.exists():
                candidate.unlink()
                print(f"  清掉本机凭据 {candidate.relative_to(STAGE)}")

    write_crlf(data_root / "说明.txt", """这个目录放运行数据，删掉等于把灵枢恢复成刚装好的状态。

  workspace\\              工作区根（配置里 workspace.root）
    sessions\\             会话：每次任务的材料、flags.json、报告、审计
    reports\\              报告输出
    audit.jsonl            逐条审计（模型调用与工具调用）
    blackboard.db          共享黑板
    knowledge.db/chroma/   知识库
    experience.db          做题经验库（预置了一批实战判读经验，见下）
    admin.db              控制台管理员（第一次启动时设的密码，只存 scrypt 哈希；
                          打包时被清掉，出厂包没有这个文件）
    auth.key              登录会话 Cookie 的签名密钥（同样是本地生成，不进包）
    vault.db + vault.key   本机密钥库（模型 API Key 加密存这里）
    resources\\            共享资源目录

关于 experience.db
------------------
跨会话自我进化用的经验库，表 insights 每条是一句实战洞察 + 适用场景 +
标签 + 来源会话。两个来源：
  1. 出厂预置——已随包附带，直接可用；
  2. 自己攒的——每次任务收尾时由模型提炼，下个任务开工时自动召回最多
     6 条（experience.recall_limit）。

想归零就删掉这个文件，下次启动会重建空库。想带着换机器就连目录一起拷。

备份或整体搬到别的电脑：连这个目录一起拷，历史会话和已填的 key 都跟着走。
""", encoding="utf-8-sig")
    print("  启动脚本 + 使用说明就绪")


# ------------------------------------------------------------------ 6) 打 zip
#: 出厂包里绝不允许存在的本机凭据（首次启动才由用户自己生成）。
CREDENTIAL_FILES = ("admin.db", "auth.key", "vault.db", "vault.key")


def assert_no_credentials() -> None:
    """打包前最后一道闸：凭据文件一个都不许在包里，发现就拒绝出包。

    只看 ``data\\``：那是运行数据的落点，凭据只可能出现在这里；``runtime\\``
    是第三方依赖，同名文件（如果有）跟凭据无关。
    """
    data_root = STAGE / "data"
    hits = [p for p in data_root.rglob("*")
            if p.is_file() and p.name in CREDENTIAL_FILES] if data_root.exists() else []
    if hits:
        for p in hits:
            print(f"  清掉漏网凭据 {p.relative_to(STAGE)}")
            p.unlink(missing_ok=True)
        raise SystemExit("出厂包含本机凭据，已清理并中止出包；请重新组装后再打 zip")
    print("  凭据闸：data\\ 内无 admin.db / auth.key / vault.*")


def prune_app_bytecode() -> int:
    """出包前剪掉 ``app\\`` 下的 __pycache__。

    ``APP_IGNORE`` 只在复制时排除，验包会把控制台真起一遍，Python 又在自己
    代码旁边写回 ``.pyc``；不剪的话发布包里会带着一份可能比源码旧的字节码。
    ``runtime\\`` 下的第三方字节码保留：那是依赖预编译，属于正常内容。
    """
    app = STAGE / "app"
    if not app.exists():
        return 0
    count = 0
    for cache in sorted(app.rglob("__pycache__"), reverse=True):
        if cache.is_dir():
            count += sum(1 for p in cache.rglob("*") if p.is_file())
            shutil.rmtree(cache, ignore_errors=True)
    return count


def make_zip() -> Path:
    assert_no_credentials()
    pruned = prune_app_bytecode()
    if pruned:
        print(f"  剪掉 app\\ 下的 __pycache__ {pruned} 个文件")
    zip_path = OUT / f"{NAME}.zip"
    zip_path.unlink(missing_ok=True)
    files = [p for p in STAGE.rglob("*") if p.is_file()]
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for i, p in enumerate(files, 1):
            z.write(p, Path(NAME) / p.relative_to(STAGE))
            if i % 5000 == 0:
                print(f"    {i}/{len(files)}")
    print(f"  {zip_path.name}  {zip_path.stat().st_size / 1048576:.1f} MB")
    return zip_path


def main() -> int:
    if "--zip-only" in sys.argv:
        print(f"=== 只打 zip（{mb(STAGE):.0f} MB / {nfiles(STAGE)} 文件）===")
        make_zip()
        return 0
    if "--scripts-only" in sys.argv:
        print("=== 只重写启动脚本与说明 ===")
        build_scripts()
        return 0
    print(f"源版本 {VERSION} -> {STAGE}")
    print("=== 1/6 runtime ===")
    rm(STAGE)
    STAGE.mkdir(parents=True)
    build_runtime()
    print("=== 2/6 依赖 ===")
    build_site_packages()
    print("=== 3/6 程序 ===")
    build_app()
    print("=== 4/6 配置 ===")
    build_configs()
    print("=== 5/6 启动脚本 ===")
    build_scripts()
    print(f"[=] 暂存目录 {mb(STAGE):.0f} MB / {nfiles(STAGE)} 文件")
    if "--zip" in sys.argv:
        print("=== 6/6 打 zip ===")
        make_zip()
    return 0


if __name__ == "__main__":
    sys.exit(main())
