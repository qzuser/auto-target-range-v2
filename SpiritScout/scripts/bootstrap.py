#!/usr/bin/env python
"""环境自检与一键修复：找解释器 → 建 venv → 装依赖（国内镜像，失败换源重试）。

为什么单独抽一个脚本：`start-local.ps1` 里那套逻辑只有 PowerShell 能跑，
新加的桌面 GUI 要用、CI 要用、换到别的机器排障时手动也要用。环境问题在
别的机器上偶发的根因基本就四类，这里逐条兜住：

1. **解释器找错**：系统里可能同时有 3.14 / 3.11 / uv 管理的 3.12，跟着
   `python` 走容易拿到太新的那个（gmpy2 / z3 在新 Python 上常常没有预编译
   轮子，自装卡在源码编译）。这里按「显式指定 → venv 里已有的 → py 启动器
   取最低 3.11+ → PATH 上的 python」顺序挑，并要求 3.11 ≤ 版本。
2. **网络抖动**：清华 → 阿里 → 官方，逐个试，每个都带 `--retries/--timeout`，
   国内装 litellm 那几百兆不该因为一次 502 就整个失败。
3. **半残 venv**：venv 在、pip 没了、或解释器跑不起来。默认只报告，带
   `--recreate` 才重建——删环境的破坏面比装包大，得让调用方明说。
4. **写不动 / 路径怪**：临时目录不可写会让 pip 报一堆看不懂的错，这里提前
   探出来并给 pip 指一个能写的 TMP；路径含非 ASCII 字符也只警告不拦。

用法::

    python scripts/bootstrap.py                # 只体检，退出码 0 / 1
    python scripts/bootstrap.py --json         # 体检结果给 GUI / CI 消费
    python scripts/bootstrap.py --fix          # 建 venv 并装缺的运行依赖
    python scripts/bootstrap.py --fix --toolkit --recreate   # 连工具包一起，坏了就重建

退出码：0 健康；1 缺依赖（可 `--fix`）；2 找不到可用的 Python；3 环境坏了
（venv 起不来 / 没 pip，需要 `--recreate`）。
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

# 装依赖的源，按顺序试。国内机器上官方站常常见底速甚至超时，
# 所以镜像在前、官方兜底；要锁定某一个源就传 --mirror。
MIRRORS = [
    "https://pypi.tuna.tsinghua.edu.cn/simple",
    "https://mirrors.aliyun.com/pypi/simple/",
    "https://pypi.org/simple",
]

OFFICIAL = "https://pypi.org/simple"
MIN_PYTHON = (3, 11)
VENV_DIRNAME = Path(".venv")
PACKAGE_DIRNAME = "SpiritScout"

# 打印机：GUI 和 CLI 都靠这行前缀判断「哪一步在跑」，别随便改格式
STEP_PREFIX = "[step] "


def package_root() -> Path:
    """包目录（`pyproject.toml` 与 `.venv` 都在这一级）。

    从 GitHub 拉下来的工作区是 `仓库根/SpiritScout/`，而 release 里的
    sdist / zip 直接把 `SpiritScout` 当根——两种布局都用「脚本上一级」定位，
    顺便要求那一级真的有 `pyproject.toml`，免得在仓库根误建一个 .venv。
    """
    candidate = Path(__file__).resolve().parents[1]
    if (candidate / "pyproject.toml").is_file():
        return candidate
    return Path(__file__).resolve().parents[2]


def venv_python(root: Path) -> Path:
    """venv 里的解释器路径（不管存不存在）。"""
    if os.name == "nt":
        return root / VENV_DIRNAME / "Scripts" / "python.exe"
    return root / VENV_DIRNAME / "bin" / "python"


def say(line: str = "") -> None:
    """进度行一律走 stdout 并立刻 flush，GUI 的日志框靠它实时滚动。"""
    print(line, flush=True)


def _run(cmd: Sequence[str], *, timeout: float = 60.0, env: dict[str, str] | None = None,
         cwd: Path | None = None) -> subprocess.CompletedProcess:
    """跑一个命令；不抛异常，失败信息留在返回值里交给调用方判断。"""
    merged = dict(os.environ)
    merged.setdefault("PYTHONUTF8", "1")
    merged.setdefault("PYTHONIOENCODING", "utf-8")
    if env:
        merged.update(env)
    try:
        return subprocess.run(list(cmd), capture_output=True, text=True, errors="replace",
                              timeout=timeout, env=merged, cwd=str(cwd) if cwd else None)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(list(cmd), 124, "", f"超时（{timeout:.0f}s）")
    except OSError as exc:
        return subprocess.CompletedProcess(list(cmd), 127, "", str(exc))


def parse_version(text: str) -> tuple[int, int, int] | None:
    """从 `Python 3.11.6` 或 `3.11.6` 里取版本三元组。"""
    for token in str(text).replace("\n", " ").split():
        parts = token.split(".")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            patch = parts[2] if len(parts) > 2 and parts[2].isdigit() else "0"
            return (int(parts[0]), int(parts[1]), int(patch))
    return None


def python_version(exe: Path | str) -> tuple[int, int, int] | None:
    """问解释器自己是哪个版本；跑不起来就返回 None。"""
    result = _run([str(exe), "-c", "import sys; print('%d.%d.%d' % sys.version_info[:3])"],
                  timeout=20)
    if result.returncode != 0:
        return None
    return parse_version(result.stdout)


def _is_usable(version: tuple[int, int, int] | None) -> bool:
    return version is not None and version[:2] >= MIN_PYTHON


def find_python(root: Path, override: str | None = None) -> dict[str, Any] | None:
    """按顺序挑一个能用的解释器；返回 `{path, version, source}`。"""
    candidates: list[tuple[str, str]] = []
    if override:
        candidates.append((override, "参数指定"))
    env_python = os.environ.get("SPIRITSCOUT_PYTHON", "").strip()
    if env_python:
        candidates.append((env_python, "环境变量 SPIRITSCOUT_PYTHON"))
    candidates.append((str(venv_python(root)), "已有 venv"))
    for exe in ("python3", "python"):
        found = shutil.which(exe)
        if found:
            candidates.append((found, "PATH"))

    # py 启动器：取版本号最低的 3.11+。太新的 Python 上 gmpy2 / z3 常常
    # 只有源码包，自装会卡在编译，这才是「别的机器上偶发失败」的常见原因。
    launcher = shutil.which("py")
    if launcher:
        listing = _run([launcher, "-0p"], timeout=20)
        found: list[tuple[tuple[int, int, int], str]] = []
        for line in (listing.stdout or "").splitlines():
            if "-V:" not in line:
                continue
            tag = line.split("-V:", 1)[1].split()[0]
            version = parse_version(tag)
            if version and _is_usable(version):
                found.append((version, tag))
        for _, tag in sorted(found):
            candidates.append((f"{launcher} -{tag}", f"py -{tag}"))

    seen: set[str] = set()
    for exe, source in candidates:
        if exe in seen:
            continue
        seen.add(exe)
        if exe.startswith("py "):
            # `py -3.11` 这种带参数的启动方式要拆开跑
            parts = exe.split()
            probe = _run([*parts, "-c", "import sys; print('%d.%d.%d' % sys.version_info[:3])"],
                         timeout=20)
            version = parse_version(probe.stdout) if probe.returncode == 0 else None
            if _is_usable(version):
                return {"path": exe, "version": "%d.%d.%d" % version, "source": source}
            continue
        path = Path(exe)
        if not path.exists():
            continue
        version = python_version(path)
        if _is_usable(version):
            return {"path": str(path), "version": "%d.%d.%d" % version, "source": source}
    return None


def venv_state(root: Path) -> dict[str, Any]:
    """venv 存不存在、解释器跑不跑得起来、pip 在不在。"""
    exe = venv_python(root)
    state: dict[str, Any] = {"path": str(exe), "exists": exe.exists(),
                             "version": None, "has_pip": False}
    if not state["exists"]:
        return state
    version = python_version(exe)
    if version is None:
        return state
    state["version"] = "%d.%d.%d" % version
    pip = _run([str(exe), "-c", "import importlib.util as u; print(bool(u.find_spec('pip')))"],
               timeout=20)
    state["has_pip"] = pip.stdout.strip().lower() == "true"
    return state


def probe_environment(exe: Path | str, root: Path, *, toolkit: bool = True) -> dict[str, Any] | None:
    """跑 `probe_deps.py --json`，拿依赖清单。读不出就返回 None。"""
    script = root / "scripts" / "probe_deps.py"
    if not script.is_file():
        return None
    cmd = [str(exe), str(script), "--json"]
    if toolkit:
        cmd.append("--toolkit")
    result = _run(cmd, timeout=120)
    text = (result.stdout or "").strip().splitlines()
    if not text:
        return None
    try:
        return json.loads(text[-1])
    except ValueError:
        return None


def tmp_dir(root: Path) -> Path:
    """给 pip 用的临时目录：系统 TMP 不可写时 pip 的报错极难懂，自己兜一个。"""
    for candidate in (Path(tempfile.gettempdir()), root / ".tmp", Path.home() / ".spiritscout-tmp"):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / f".write-test-{os.getpid()}"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return candidate
        except OSError:
            continue
    return root


def free_port(preferred: int = 8010) -> int:
    """优先用惯用端口，被占就由系统分配——比让人改配置省事。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def diagnose(root: Path, *, python: str | None = None) -> dict[str, Any]:
    """只体检，不改任何东西。"""
    target = find_python(root, python)
    venv = venv_state(root)
    deps = None
    if venv["exists"] and venv["version"] and venv["has_pip"]:
        deps = probe_environment(venv_python(root), root, toolkit=True)
    elif venv["exists"] and venv["version"]:
        deps = None

    warnings: list[str] = []
    root_text = str(root)
    if not root_text.isascii():
        warnings.append("仓库路径含非 ASCII 字符：个别构建后端会因此编译失败，装不上时把仓库挪到纯英文路径再试")
    writable = os.access(root, os.W_OK)
    if not writable:
        warnings.append(f"仓库目录不可写：{root}（建 venv 与 pip 缓存都写在这里）")
    if deps is None and venv["exists"] and venv["version"] and not venv["has_pip"]:
        warnings.append("venv 里没有 pip：补装不了，需要 --recreate 重建")
    probe_script = root / "scripts" / "probe_deps.py"
    if deps is None and not probe_script.is_file():
        # 探针缺失时「不知道依赖全不全」，和「依赖不全」要分开说：
        # 前者多半是包被裁剪过（比如只有 wheel），后者才是真缺东西。
        warnings.append(f"没有 {probe_script}：没法确认依赖是否齐全（源码包与 zip 里都有）")
    if venv["exists"] and venv["version"] is None:
        warnings.append("venv 里的解释器跑不起来（多半是从别的机器拷过来的）：需要 --recreate")

    missing = list((deps or {}).get("runtime_missing") or [])
    toolkit_missing = list((deps or {}).get("toolkit_missing") or [])
    ok = bool(target) and bool(venv["exists"]) and bool(venv["version"]) and venv["has_pip"] \
        and deps is not None and not missing and bool(deps.get("self_version"))

    if target is None:
        warnings.append("没找到 3.11 或更高的 Python：装一个再跑，或设 SPIRITSCOUT_PYTHON 指向解释器")
    elif not venv["exists"]:
        warnings.append(f"还没有虚拟环境：{venv_python(root)}")

    return {
        "root": root_text,
        "platform": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "python": target,
        "venv": venv,
        "deps": deps,
        "probe": "ok" if deps is not None else ("missing" if not probe_script.is_file() else "failed"),
        "missing": missing,
        "toolkit_missing": toolkit_missing,
        "warnings": warnings,
        "tmp": str(tmp_dir(root)),
        "port": free_port(),
        "ok": ok,
    }


def _pip_install(target: str, *, root: Path, exe: Path, mirrors: Iterable[str],
                 timeout: float, on_line: Callable[[str], None] | None = None) -> dict[str, Any]:
    """装一个 target（`SpiritScout` 或 `SpiritScout[toolkit]`），逐源重试。"""
    attempts: list[dict[str, Any]] = []
    tmp = tmp_dir(root)
    # 缓存也钉在这一处：默认位置在用户目录，某些机器/策略下不可写，
    # 而且会把几个 G 的 wheel 缓存散在别人的家目录里。
    cache = tmp / "pip-cache"
    try:
        cache.mkdir(parents=True, exist_ok=True)
    except OSError:
        cache = tmp
    env = {"TMP": str(tmp), "TEMP": str(tmp), "TMPDIR": str(tmp),
           "PIP_CACHE_DIR": str(cache), "PIP_DISABLE_PIP_VERSION_CHECK": "1"}
    for mirror in mirrors:
        cmd = [str(exe), "-m", "pip", "install", "--disable-pip-version-check",
               "--retries", "2", "--timeout", "30", "--index-url", mirror, "--editable", target]
        say(f"{STEP_PREFIX}pip install -e {target} ← {mirror}")
        started = time.time()
        result = _run(cmd, timeout=timeout, env=env, cwd=root)
        elapsed = time.time() - started
        tail = [line for line in (result.stdout or "").splitlines() if line.strip()][-6:]
        for line in tail:
            say(f"    {line}")
        if result.returncode != 0:
            for line in (result.stderr or "").splitlines()[-4:]:
                say(f"    ! {line}")
        attempts.append({"mirror": mirror, "code": result.returncode,
                         "seconds": round(elapsed, 1)})
        if result.returncode == 0:
            return {"ok": True, "mirror": mirror, "attempts": attempts}
    return {"ok": False, "mirror": None, "attempts": attempts}


def fix(root: Path, *, python: str | None = None, mirror: str | None = None,
        toolkit: bool = False, recreate: bool = False, timeout: float = 1800.0,
        on_line: Callable[[str], None] | None = None) -> dict[str, Any]:
    """按「解释器 → venv → pip → 依赖」的顺序补齐，每一步都在 stdout 留痕。"""
    start = diagnose(root, python=python)
    log: list[str] = []

    def note(text: str) -> None:
        log.append(text)
        say(text)

    target = start["python"]
    if target is None:
        note("[x] 没找到 3.11+ 的 Python，装不了。安装后再跑一次，或用 --python 指路")
        return {"ok": False, "reason": "no-python", **start, "log": log}

    venv = start["venv"]
    exe = venv_python(root)
    if recreate and venv["exists"]:
        note(f"[>] 重建虚拟环境：{exe.parent.parent}")
        shutil.rmtree(exe.parent.parent, ignore_errors=True)
        venv = {"path": str(exe), "exists": False, "version": None, "has_pip": False}

    if not venv["exists"]:
        note(f"[>] 建虚拟环境（{target['source']}：{target['path']}）")
        say(f"{STEP_PREFIX}python -m venv")
        created = _run([*target["path"].split(), "-m", "venv", str(exe.parent.parent)],
                       timeout=300, cwd=root)
        if created.returncode != 0:
            note(f"[x] 建 venv 失败：{(created.stderr or created.stdout or '').strip()[:400]}")
            return {"ok": False, "reason": "venv-create-failed", **start, "log": log}
        venv = venv_state(root)

    if not venv["version"]:
        note("[x] venv 里的解释器跑不起来，加 --recreate 重建")
        return {"ok": False, "reason": "venv-broken", **start, "log": log}

    if not venv["has_pip"]:
        note("[>] venv 里没有 pip，先补 pip")
        say(f"{STEP_PREFIX}python -m ensurepip")
        ensured = _run([str(exe), "-m", "ensurepip", "--upgrade"], timeout=300, cwd=root)
        if ensured.returncode != 0:
            note("[x] ensurepip 也失败，加 --recreate 重建")
            return {"ok": False, "reason": "no-pip", **start, "log": log}

    mirrors = [mirror] if mirror else list(MIRRORS)
    before = probe_environment(exe, root, toolkit=True) or {}
    missing = list(before.get("runtime_missing") or [])
    install_needed = missing or not before.get("self_version")

    attempts: list[dict[str, Any]] = []
    if install_needed:
        note(f"[>] 装运行依赖（缺 {len(missing)} 个，本体{'未装' if not before.get('self_version') else '已装'}）")
        result = _pip_install(".", root=root, exe=exe, mirrors=mirrors,
                              timeout=timeout, on_line=on_line)
        attempts += result["attempts"]
        if not result["ok"]:
            note("[x] 依赖装不上：所有源都失败，把上面的报错尾巴发我")
            return {"ok": False, "reason": "install-failed", **start,
                    "attempts": attempts, "log": log}

    toolkit_missing = list(before.get("toolkit_missing") or [])
    if toolkit and toolkit_missing:
        note(f"[>] 装可选工具包（缺 {len(toolkit_missing)} 个）")
        result = _pip_install(".[toolkit]", root=root, exe=exe,
                              mirrors=mirrors, timeout=timeout, on_line=on_line)
        attempts += result["attempts"]
        if not result["ok"]:
            note("[!] 工具包没装全（不影响启动，只影响 CTF 工具链）")

    after = diagnose(root, python=str(exe))
    note("[+] 环境就绪" if after["ok"] else "[!] 体检仍有问题：见上面几行")
    return {"ok": after["ok"], "attempts": attempts, "log": log, **after}


def render_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, default=str), flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="灵枢环境自检与一键修复")
    parser.add_argument("--root", default="", help="仓库根（默认按脚本位置推断）")
    parser.add_argument("--python", default="", help="指定解释器（可写 `py -3.11`）")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--fix", action="store_true", help="缺什么补什么")
    parser.add_argument("--toolkit", action="store_true", help="连可选工具包一起装")
    parser.add_argument("--recreate", action="store_true", help="venv 坏了就删了重建")
    parser.add_argument("--mirror", default="", help="只用一个源（默认清华→阿里→官方）")
    parser.add_argument("--timeout", type=float, default=1800.0, help="单次 pip 超时秒数")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve() if args.root else package_root()
    python = args.python or None
    if args.fix:
        result = fix(root, python=python, mirror=args.mirror or None, toolkit=args.toolkit,
                     recreate=args.recreate, timeout=args.timeout)
        if args.json:
            render_json(result)
        return 0 if result["ok"] else 1

    result = diagnose(root, python=python)
    if args.json:
        render_json(result)
    else:
        say(f"仓库：{result['root']}")
        say(f"平台：{result['platform']}")
        target = result["python"]
        if target:
            say(f"解释器：{target['path']}（{target['version']}，来自{target['source']}）")
        else:
            say("解释器：没找到 3.11+")
        venv = result["venv"]
        if venv["exists"]:
            say(f"虚拟环境：{venv['path']}（{venv['version'] or '跑不起来'}，"
                f"pip {'有' if venv['has_pip'] else '没有'}）")
        else:
            say(f"虚拟环境：还没建（{venv['path']}）")
        if result["deps"]:
            deps = result["deps"]
            say(f"运行依赖：缺 {len(result['missing'])} 个"
                + ("：" + " ".join(result["missing"]) if result["missing"] else "（齐）"))
            if deps.get("toolkit_missing"):
                say(f"可选工具包：缺 {len(deps['toolkit_missing'])} 个")
        for warning in result["warnings"]:
            say(f"[!] {warning}")
        say(f"结论：{'可用' if result['ok'] else '需要修复（--fix）'}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
