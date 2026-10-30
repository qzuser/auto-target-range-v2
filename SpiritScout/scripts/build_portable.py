"""构建「解压即用」的 Windows 便携包。

把 CPython 运行时、全部第三方依赖和项目本体打成一个目录，用户解压后双击
`1-启动服务.bat` 即可使用，不需要预装 Python 或联网装依赖。

用法：
    .venv/Scripts/python -m scripts.build_portable

产物：packages/SpiritScout-<version>-portable/ 与同名 zip。

可重定位的关键
--------------
1. **不写 python311._pth**：它把 sys.path 钉成绝对路径并禁用 PYTHONPATH，
   反而破坏搬移能力。标准布局（python.exe 在包根、Lib/Lib\\site-packages
   在包内）下 CPython 自己认这个目录为 prefix。
2. **必须带 python3.dll**：Rust/C 扩展（tokenizers、cv2 等）链接的是稳定
   ABI 转发库 `python3.dll`，不是 `python311.dll`。漏了它只有一个笼统的
   `ImportError: DLL load failed`，看不出缺什么——这是本脚本踩过的坑。
3. **VC++ 运行时整套同版本**：Python 安装目录自带 14.34 的 vcruntime140，
   而系统 msvcp140 往往是 14.51，混用照样加载失败。统一从 System32 取。
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT.parent / "packages"
VERSION = (ROOT / "src" / "spiritscout" / "__init__.py").read_text(
    encoding="utf-8").split('__version__ = "')[1].split('"')[0]
NAME = f"SpiritScout-{VERSION}-portable"
STAGE = OUT / NAME

# 解释器本体：python3.dll 是稳定 ABI 转发库，扩展模块真正依赖的是它
CORE_BINARIES = ("python.exe", "pythonw.exe", "python311.dll", "python3.dll")
# VC++ 运行时：必须成套且同版本，宁可全套拿 System32 的
VC_RUNTIME = ("msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll",
              "msvcp140_atomic_wait.dll", "msvcp140_codecvt_ids.dll",
              "concrt140.dll", "vcruntime140.dll", "vcruntime140_1.dll",
              "vcruntime140_threads.dll")
# 不进包：开发机产物、缓存、用户数据
DROP_DIRS = {"build", "dist", ".venv", ".git", ".spiritscout", "__pycache__",
             "tests", "node_modules", ".pytest_cache", ".ruff_cache",
             "scripts", "browser-output", "docs", ".tools"}
DROP_FILES = {".env", ".gitignore", ".gitattributes"}

START_BAT = r"""@echo off
chcp 65001 >nul
title SpiritScout __VERSION__
cd /d "%~dp0"

rem Keep this file ASCII-only, UTF-8 without BOM, CRLF: cmd reads batch files by
rem byte offset, and multi-byte text inside rem lines can shift line boundaries.

set "VIRTUAL_ENV=%~dp0runtime"
set "PYTHONPATH=%~dp0app\src"
set "PYTHONUTF8=1"
set "PYTHONNOUSERSITE=1"
set "PYTHONIOENCODING=utf-8"
rem Do not fetch litellm's remote model-cost table: unreachable hosts cost 3
rem retries of a few seconds each, and the built-in table is used anyway.
set "LITELLM_LOCAL_MODEL_COST_MAP=True"

if not exist "%~dp0data" mkdir "%~dp0data"

echo.
echo   SpiritScout __VERSION__   Web console  ^|  http://127.0.0.1:8010
echo   Close this window to stop it.
echo.

start "" "http://127.0.0.1:8010"
"%~dp0runtime\python.exe" -X utf8 -m spiritscout --config "%~dp0configs\system.yaml" --port 8010
if errorlevel 1 (
  echo.
  echo   [ERROR] console exited. See messages above.
  pause
)
"""

STOP_BAT = r"""@echo off
chcp 65001 >nul
echo Stopping SpiritScout (port 8010) ...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8010" ^| findstr LISTENING') do (
  taskkill /F /PID %%a >nul 2>&1
)
echo Done.
pause
"""

USAGE = """灵枢（SpiritScout）v__VERSION__ 便携版
================================================

解压后双击「1-启动服务.bat」，浏览器会自动打开 http://127.0.0.1:8010

首次使用
--------
1. 双击 1-启动服务.bat（保持黑窗口开着，关掉窗口就等于停服务）
2. 浏览器打开 http://127.0.0.1:8010
3. 到「模型设置」填自己的 API Key
4. 停止：关掉启动窗口，或双击 2-停止服务.bat

包内结构
--------
  runtime\\     自带 Python 3.11 与全部依赖，无需预装、无需联网
  app\\         程序本体
  configs\\     配置文件（system.yaml / models.yaml）
  local-range\\ 内置练习靶场（可选）
  data\\        运行数据，可直接备份或清空

说明
----
- 解压即用，不需要装 Python；目录可放任意路径，含中文也没问题。
- 换台电脑：整个文件夹拷过去即可。
- 端口被占用时，编辑 1-启动服务.bat 把 --port 8010 改成别的。
- Windows 64 位专用。
"""


def _onerror(func, path, _exc):
    """只读文件（.pyc 常带只读位）强删一次；仍失败就如实报错。"""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError as exc:
        print(f"    ! 无法删除 {path}: {exc}")


def _size(p: Path) -> float:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) / 1048576


def _base_python() -> Path:
    """定位构建用的基础 CPython 安装（venv 只提供身份，不提供 Lib）。"""
    cfg = ROOT / ".venv" / "pyvenv.cfg"
    if cfg.exists():
        for line in cfg.read_text(encoding="utf-8").splitlines():
            if line.lower().startswith("home"):
                home = Path(line.split("=", 1)[1].strip())
                if (home / "python.exe").exists():
                    return home
    found = Path(sys.base_prefix)
    if (found / "python.exe").exists():
        return found
    raise SystemExit("找不到基础 Python 安装目录")


def main() -> int:
    if os.name != "nt":
        raise SystemExit("便携包构建只支持 Windows")

    base = _base_python()
    venv_sp = ROOT / ".venv" / "Lib" / "site-packages"
    if not venv_sp.is_dir():
        raise SystemExit(f"缺少依赖目录：{venv_sp}")

    print(f"版本 {VERSION}")
    print(f"基础 Python {base}")

    if STAGE.exists():
        shutil.rmtree(STAGE, onerror=_onerror)
    STAGE.mkdir(parents=True)

    # 1. 运行时
    runtime = STAGE / "runtime"
    runtime.mkdir()
    for name in CORE_BINARIES:
        src = base / name
        if not src.exists():
            raise SystemExit(f"基础 Python 缺少 {name}")
        shutil.copy2(src, runtime / name)
    vc_dir = Path(os.environ["WINDIR"]) / "System32"
    for name in VC_RUNTIME:
        src = vc_dir / name
        if src.exists():
            shutil.copy2(src, runtime / name)
    ign = shutil.ignore_patterns("__pycache__", "test", "tests", "idlelib",
                                 "tkinter", "turtledemo", "site-packages")
    for sub in ("DLLs", "Lib"):
        shutil.copytree(base / sub, runtime / sub, ignore=ign, dirs_exist_ok=True)
    (runtime / "Lib" / "site-packages").mkdir(parents=True, exist_ok=True)
    print(f"  运行时 {_size(runtime):.0f} MB")

    # 2. 依赖
    shutil.copytree(venv_sp, runtime / "Lib" / "site-packages",
                    ignore=shutil.ignore_patterns("__pycache__"),
                    dirs_exist_ok=True)
    sp = runtime / "Lib" / "site-packages"
    for junk in ("tests", "test"):
        for d in list(sp.rglob(junk)):
            if d.is_dir() and d.parent != sp:
                shutil.rmtree(d, onerror=_onerror)
    print(f"  加依赖共 {_size(runtime):.0f} MB")

    # 3. 项目
    app = STAGE / "app"
    app.mkdir()
    for item in ROOT.iterdir():
        if item.name in DROP_DIRS or item.name in DROP_FILES:
            continue
        dst = app / item.name
        if item.is_dir():
            shutil.copytree(item, dst, ignore=shutil.ignore_patterns(
                "__pycache__", "*.egg-info"), dirs_exist_ok=True)
        else:
            shutil.copy2(item, dst)
    for d in list(app.rglob("__pycache__")):
        shutil.rmtree(d, onerror=_onerror)
    print(f"  项目 {_size(app):.1f} MB")

    # 4. 配置与数据目录
    cfg_src = ROOT / "configs"
    if cfg_src.is_dir():
        shutil.copytree(cfg_src, STAGE / "configs",
                        ignore=shutil.ignore_patterns("__pycache__"),
                        dirs_exist_ok=True)
    (STAGE / "data").mkdir()

    # 5. 启动脚本（CRLF，否则 cmd 解析出错）
    for name, text in (("1-启动服务.bat", START_BAT),
                       ("2-停止服务.bat", STOP_BAT),
                       ("使用说明.txt", USAGE)):
        (STAGE / name).write_text(
            text.replace("__VERSION__", VERSION).replace("\n", "\r\n"),
            encoding="utf-8")
    print("  脚本就绪")

    # 6. 自检：真正 import 一遍重依赖，别把坏包发出去
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith(("PYTHON", "VIRTUAL_ENV"))}
    env.update(PYTHONPATH=str(app / "src"), PYTHONNOUSERSITE="1",
               PYTHONUTF8="1", LITELLM_LOCAL_MODEL_COST_MAP="True")
    probe = (
        "import sys;"
        "mods=['tokenizers','cv2','numpy','cryptography','z3','capstone',"
        "'pwnlib','PIL','fastapi','uvicorn','litellm','httpx','yaml'];"
        "bad=[];"
        "[bad.append(m) for m in mods if not __import__('importlib').util.find_spec(m)];"
        "__import__('importlib').import_module('spiritscout');"
        "print('imports-ok' if not bad else 'missing:'+','.join(bad))"
    )
    res = subprocess.run([str(runtime / "python.exe"), "-c", probe],
                         capture_output=True, text=True, env=env,
                         cwd=str(STAGE), timeout=600)
    tail = (res.stdout or res.stderr).strip().splitlines()
    print("  自检:", tail[-1][:120] if tail else "(无输出)")
    if res.returncode != 0 or "imports-ok" not in (res.stdout or ""):
        print(res.stderr[-1200:])
        return 1

    # 7. 打 zip
    zip_path = OUT / f"{NAME}.zip"
    if zip_path.exists():
        zip_path.unlink()
    files = [p for p in STAGE.rglob("*") if p.is_file()]
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED,
                         compresslevel=6) as zf:
        for i, p in enumerate(files, 1):
            zf.write(p, Path(NAME) / p.relative_to(STAGE))
            if i % 10000 == 0:
                print(f"    {i}/{len(files)}")
    print(f"  {zip_path.name} {zip_path.stat().st_size / 1048576:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
