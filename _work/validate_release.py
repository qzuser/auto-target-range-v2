"""把发布包当成「别人拿到手」的样子验一遍。

验三件事：
  1. 自带解释器能 import 程序与全部重依赖（litellm / fastapi / pwntools …）
  2. 宿主后端的解释器探测走 VIRTUAL_ENV=runtime（即 python 工具可用），
     并且清掉编辑安装残留后 import spiritscout 真的来自 app\\src
  3. 控制台能真起来：GET / 返回 200（用包内配置，cwd=包根）
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PKG = Path(r"C:\Users\admin\Desktop\全自动打靶\packages\SpiritScout-0.23.0-portable")
PY = PKG / "runtime" / "python.exe"
CONSOLE_PORT = 8092


def clean_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith(("PYTHON", "SPIRITSCOUT_"))}
    env["VIRTUAL_ENV"] = str(PKG / "runtime")
    env["PYTHONPATH"] = str(PKG / "app" / "src")
    env["PYTHONUTF8"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def free(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", port)) != 0


def get(url: str, timeout: float = 5.0) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read(2000).decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        return -1, str(exc)


def step(title: str) -> None:
    print(f"\n=== {title} ===")


def run_py(code: str, timeout: int = 600) -> tuple[int, str]:
    r = subprocess.run([str(PY), "-X", "utf8", "-c", code], capture_output=True,
                       text=True, env=clean_env(), cwd=str(PKG), timeout=timeout)
    return r.returncode, ((r.stdout or "").strip() + "\n" + (r.stderr or "").strip()).strip()


def boot(argv: list[str], port: int, wait: float = 180.0) -> subprocess.Popen:
    log = PKG.parent / f"_boot_{port}.log"
    fh = log.open("w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen([str(PY), "-X", "utf8", *argv], stdout=fh,
                            stderr=subprocess.STDOUT, env=clean_env(), cwd=str(PKG))
    deadline = time.time() + wait
    while time.time() < deadline:
        if proc.poll() is not None or not free(port):
            return proc
        time.sleep(0.5)
    return proc


def main() -> int:
    print("包:", PKG, "| python:", PY.exists())
    fails: list[str] = []

    step("1) 依赖 import")
    rc, out = run_py(
        "import spiritscout, fastapi, uvicorn, litellm, pydantic, yaml, httpx;"
        "print('version', spiritscout.__version__);"
        "print('module', spiritscout.__file__);"
        "import pwnlib, capstone, z3, scapy, sqlmap, cv2;"
        "print('toolkit ok')")
    print(out[:600])
    if rc != 0 or str(PKG / "app" / "src") not in out:
        fails.append("import / 模块来源")

    step("2) 沙箱解释器探测（python 工具可用性）")
    rc, out = run_py(
        "from spiritscout.tools import sandbox;"
        "v = sandbox._project_venv();"
        "print('venv', v);"
        "print('python', sandbox._host_python());"
        "print('site', sandbox._venv_site_dirs(v) if v else None);"
        "print('backend', sandbox.sandbox_backend());"
        "print('shell', sandbox._host_shell())")
    print(out[:800])
    if rc != 0 or f"{PKG}\\runtime" not in out:
        fails.append("VIRTUAL_ENV 探测")
    if f"Scripts\\python.exe" not in out:
        fails.append("Scripts/python.exe 未命中")

    step("3) 真跑一次 python 工具（沙箱内 import 依赖）")
    r = subprocess.run([str(PKG / "runtime" / "Scripts" / "python.exe"), "-X", "utf8", "-c",
                        "import sys;"
                        "print('prefix', sys.prefix);"
                        "print('exe', sys.executable);"
                        "print('litellm', bool(__import__('litellm')));"
                        "print('stdlib', __import__('os').__file__)"],
                       capture_output=True, text=True, env=clean_env(), cwd=str(PKG))
    print("Scripts\\python.exe:\n" + (r.stdout or r.stderr).strip()[:500])
    if r.returncode != 0 or str(PKG / "runtime") not in (r.stdout or ""):
        fails.append("Scripts/python.exe 独立可用")

    step("4) 配置文件")
    rc, out = run_py(
        "import yaml, pathlib;"
        "c = yaml.safe_load(pathlib.Path('configs/system.yaml').read_text(encoding='utf-8'));"
        "print('workspace', c['workspace']['root']);"
        "print('blackboard', c['blackboard']['sqlite_path']);"
        "print('knowledge', c['knowledge']['sqlite_path'], c['knowledge']['chroma_path']);"
        "print('reports', c['report']['output_dir']);"
        "print('audit', c['audit_log_path']);"
        "print('models', c['models_config_path']);"
        "print('mcp', [m['name'] for m in c.get('mcp_servers', [])])")
    print(out[:800])
    if rc != 0 or "data/workspace" not in out:
        fails.append("system.yaml 数据落点")
    if "'ida'" in out or "'yakit'" in out:
        fails.append("MCP 摘除不干净")

    step("5) 控制台启动")
    if not free(CONSOLE_PORT):
        print("端口占用，跳过", CONSOLE_PORT)
        fails.append(f"{CONSOLE_PORT} 占用")
    else:
        proc = boot(["-m", "spiritscout", "--config", str(PKG / "configs" / "system.yaml"),
                     "--port", str(CONSOLE_PORT)], CONSOLE_PORT)
        code, body = get(f"http://127.0.0.1:{CONSOLE_PORT}/")
        print("GET / ->", code, "|", body[:160].replace("\n", " "))
        alive = code in (200, 302, 307, 401, 403)
        if not alive:
            fails.append(f"控制台启动（rc={proc.poll()}）")
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
        log = PKG.parent / f"_boot_{CONSOLE_PORT}.log"
        tail = log.read_text(encoding="utf-8", errors="replace")[-2500:]
        print("--- 控制台日志尾部 ---\n" + tail)

    step("6) data 目录独立（配置落点真的在 data\\）")
    for rel in ("data/workspace",):
        print(rel, "exists:", (PKG / rel).exists())
    stray = [str(p.relative_to(PKG)) for p in PKG.glob(".spiritscout/*")][:5]
    print("包根误建 .spiritscout:", stray or "无")
    if stray:
        fails.append("数据落到了包根 .spiritscout")

    print("\n================ 结果 ================")
    if fails:
        for f in fails:
            print("  [FAIL]", f)
        return 1
    print("  全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
