"""把发布包当成「别人拿到手」的样子验一遍。

验三件事：
  1. 自带解释器能 import 程序与全部重依赖（litellm / fastapi / pwntools …）
  2. 宿主后端的解释器探测走 VIRTUAL_ENV=runtime（即 python 工具可用），
     并且清掉编辑安装残留后 import spiritscout 真的来自 app\\src
  3. 控制台能真起来：GET / 返回 200（用包内配置，cwd=包根）
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

VERSION = (Path(r"C:\Users\admin\Desktop\全自动打靶\SpiritScout") / "src" / "spiritscout" /
           "__init__.py").read_text(encoding="utf-8").split('__version__ = "')[1].split('"')[0]
PKG = Path(r"C:\Users\admin\Desktop\全自动打靶\packages") / f"SpiritScout-{VERSION}-portable"
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
    # 验包会把控制台真起一次；不关字节码缓存，app\src 下就会留下这次编译的
    # __pycache__，下一步 --zip-only 把它们一起打进发布包（自己代码的陈旧 .pyc）。
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def free(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", port)) != 0


def can_bind(port: int) -> bool:
    """端口能不能真拿来 listen。

    free() 只看「有没有人占着」，看不出 Windows 的保留端口段：那种端口连不上，
    但也绑不上，控制台会直接以 WinError 10013 退出。
    """
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


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
                       text=True, encoding="utf-8", errors="replace",
                       env=clean_env(), cwd=str(PKG), timeout=timeout)
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


def snapshot(root: Path) -> set[Path]:
    return {p for p in root.rglob("*") if p.is_file()} if root.exists() else set()


def sweep(root: Path, before: set[Path]) -> list[str]:
    """删掉这次验包跑出来的运行数据。

    验包会把控制台真起起来一次，data\\ 下就会多出黑板、资源目录之类的文件；
    不清掉的话下一步 --zip-only 会把「被人点开过一次」的包打出去。
    """
    removed = []
    for p in sorted(snapshot(root) - before):
        try:
            p.unlink()
            removed.append(str(p.relative_to(root)))
        except OSError:
            removed.append(f"{p}（删不掉）")
    for d in sorted((p for p in root.rglob("*") if p.is_dir()), reverse=True):
        if not any(d.iterdir()):
            d.rmdir()
    return removed


def prune_bytecode(root: Path) -> list[str]:
    """删掉验包跑出来的 __pycache__（app\\ 是自家代码，不该带着编译残渣出包）。"""
    removed = []
    app = root / "app"
    if not app.exists():
        return removed
    for d in app.rglob("__pycache__"):
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
            removed.append(str(d.relative_to(root)))
    return removed


def main() -> int:
    print("包:", PKG, "| python:", PY.exists())
    fails: list[str] = []
    data_before = snapshot(PKG / "data")

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
    if "Scripts\\python.exe" not in out:
        fails.append("VIRTUAL_ENV 里的 python.exe 没被探测到")
        fails.append("Scripts/python.exe 未命中")

    step("3) 真跑一次 python 工具（沙箱内 import 依赖）")
    r = subprocess.run([str(PKG / "runtime" / "Scripts" / "python.exe"), "-X", "utf8", "-c",
                        "import sys;"
                        "print('prefix', sys.prefix);"
                        "print('exe', sys.executable);"
                        "print('litellm', bool(__import__('litellm')));"
                        "print('stdlib', __import__('os').__file__)"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=clean_env(), cwd=str(PKG))
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
    port = next((p for p in range(CONSOLE_PORT, CONSOLE_PORT + 20)
                 if free(p) and can_bind(p)), None)
    if port is None:
        print(f"{CONSOLE_PORT} 起连续 20 个端口都不可用（被占或是 Windows 保留段），跳过")
        fails.append("没有可绑定的端口")
    else:
        proc = boot(["-m", "spiritscout", "--config", str(PKG / "configs" / "system.yaml"),
                     "--port", str(port)], port)
        code, body = get(f"http://127.0.0.1:{port}/")
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
        log = PKG.parent / f"_boot_{port}.log"
        tail = log.read_text(encoding="utf-8", errors="replace")[-2500:]
        print("--- 控制台日志尾部 ---\n" + tail)

    step("6) data 目录独立（配置落点真的在 data\\）")
    for rel in ("data/workspace",):
        print(rel, "exists:", (PKG / rel).exists())
    stray = [str(p.relative_to(PKG)) for p in PKG.glob(".spiritscout/*")][:5]
    print("包根误建 .spiritscout:", stray or "无")
    if stray:
        fails.append("数据落到了包根 .spiritscout")
        for p in PKG.glob(".spiritscout/*"):
            shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)

    step("7) 清场（下一步 --zip-only 打的必须是没跑过的包）")
    removed = sweep(PKG / "data", data_before)
    print("清掉验包跑出的文件:", removed or "无")
    pycache = prune_bytecode(PKG)
    print("清掉验包写出的 __pycache__:", pycache or "无")

    step("8) 出厂包不带本机凭据")
    workspace = PKG / "data" / "workspace"
    creds = [name for name in ("admin.db", "auth.key", "vault.db", "vault.key")
             if (workspace / name).exists()]
    print("data/workspace 下的凭据文件:", creds or "无")
    if creds:
        fails.append(f"出厂包含本机凭据：{creds}")
        for name in creds:
            (workspace / name).unlink(missing_ok=True)

    step("9) 包内 --set-admin-password：明文不进文件、二次调用跳过")
    probe = PKG.parent / "_admin_probe"
    shutil.rmtree(probe, ignore_errors=True)
    probe_ws = probe / "workspace"
    probe_cfg = probe / "system.yaml"
    probe.mkdir(parents=True, exist_ok=True)
    probe_cfg.write_text(f'workspace:\n  root: "{probe_ws.as_posix()}"\n',
                         encoding="utf-8")
    plaintext = "Probe-Pass-1234"
    base = [str(PY), "-X", "utf8", "-m", "spiritscout", "--config",
            str(probe_cfg), "--set-admin-password", "--password-stdin"]

    def probe_run(password: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([*base, "--if-missing"], input=password + "\n",
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", env=clean_env(), cwd=str(PKG),
                              timeout=180)

    first = probe_run(plaintext)
    db = probe_ws / "admin.db"
    print("首次设密退出码:", first.returncode, "| admin.db:", db.exists())
    print((first.stdout or "").strip() or "(无输出)")
    if first.returncode != 0 or not db.exists():
        fails.append(f"--set-admin-password 失败：rc={first.returncode}")
    else:
        blob = db.read_bytes()
        if plaintext.encode() in blob:
            fails.append("admin.db 里出现了明文密码")
        if b"scrypt$" not in blob:
            fails.append("admin.db 里没有 scrypt 哈希")
        if plaintext in (first.stdout or "") + (first.stderr or ""):
            fails.append("命令行输出里出现了明文密码")
        second = probe_run("Another-Pass-99")
        print("二次调用退出码:", second.returncode, "|",
              (second.stdout or "").strip().splitlines()[-1:] or "")
        if second.returncode != 0 or "跳过" not in (second.stdout or ""):
            fails.append("--if-missing 没有跳过已有管理员")
    shutil.rmtree(probe, ignore_errors=True)

    print("\n================ 结果 ================")
    if fails:
        for f in fails:
            print("  [FAIL]", f)
        return 1
    print("  全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
