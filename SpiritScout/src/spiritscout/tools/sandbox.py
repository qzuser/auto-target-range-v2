"""通过 bubblewrap（Linux）或本机受限后端（Windows/macOS）执行 shell 和 Python。

Linux 下优先 bwrap：宿主文件系统只读，用户目录和控制目录遮蔽；附件只读，
会话 sandbox 目录可写并持久化。
Windows/macOS 没有 bwrap 命名空间能力，退到 host 后端：进程工作目录锁在
会话 sandbox 目录、环境变量按白名单重建（HOME/TMP 指向会话目录）、超时强杀
进程树、输出限幅与落盘规则不变；Windows 上再补一层只作用于本会话目录的 ACL
收口（`tools/host_guard.py`：会话目录去继承 + 既有证据文件 deny 写），
但**没有读隔离**——工具结果里会带 ``parsed["sandbox"] = "host"`` 与
``parsed["hardening"]`` 以便审计区分。

后端选择：``SPIRITSCOUT_SANDBOX_BACKEND``（auto/bwrap/host，默认 auto）。
auto = 有 bwrap 用 bwrap；Windows/macOS 退 host；Linux 无 bwrap 时明确报错，
不静默降级（服务器仍应装 bubblewrap）。
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from spiritscout.platform_support import TreeGuard
from spiritscout.tools.spec import ToolResult

_BWRAP = "bwrap"
_BACKEND_ENV = "SPIRITSCOUT_SANDBOX_BACKEND"
_BASH_ENV = "SPIRITSCOUT_HOST_BASH"
_MIN_TIMEOUT = 5.0
_MAX_TIMEOUT = 300.0
_READ_CHUNK = 65536
_LOG_ROTATE_BYTES = 10 * 1024 * 1024    # 单日志超限轮转（保留上一代 .old）
_IS_WINDOWS = os.name == "nt"
# host 后端保留的最小环境变量（其余一律不继承：用户 shell 里的密钥不进沙箱）
_ENV_KEEP = (
    "SystemRoot", "SystemDrive", "windir", "COMSPEC", "PATHEXT",
    "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "OS",
)
_NO_WINDOW = 0x08000000                 # CREATE_NO_WINDOW
_NEW_GROUP = 0x00000200                 # CREATE_NEW_PROCESS_GROUP


class _RotatingLog:
    """写入中按字节轮转，两代有界；stdout/stderr 在同一事件循环共用。"""

    def __init__(self, path: Path):
        self.path = path
        self.previous = path.with_name(path.stem + ".old.log")
        self.limit = max(1, _LOG_ROTATE_BYTES)
        self.rotated = False
        self._fh = path.open("ab", buffering=0)
        self._size = path.stat().st_size
        if self._size > self.limit:
            # 旧版本可能留下超大日志，只保留尾窗，不全额读入内存。
            with path.open("rb") as source:
                source.seek(-self.limit, os.SEEK_END)
                self.previous.write_bytes(source.read(self.limit))
            self._fh.truncate(0)
            self._size = 0
            self.rotated = True

    def write(self, chunk: bytes) -> None:
        data = memoryview(chunk)
        while data:
            if self._size >= self.limit:
                self._fh.close()
                self.path.replace(self.previous)
                self._fh = self.path.open("wb", buffering=0)
                self._size = 0
                self.rotated = True
            take = min(len(data), self.limit - self._size)
            written = self._fh.write(data[:take])
            if not written:
                raise OSError("日志写入未完成")
            self._size += written
            data = data[written:]

    def close(self) -> None:
        self._fh.close()


# ---------------------------------------------------------------- 后端选择


def _requested_backend() -> str:
    raw = (os.environ.get(_BACKEND_ENV) or "auto").strip().lower()
    return raw if raw in {"auto", "bwrap", "host"} else "auto"


def _bwrap_ready() -> bool:
    return sys.platform.startswith("linux") and shutil.which(_BWRAP) is not None


def sandbox_backend() -> str | None:
    """当前生效的执行后端：``bwrap`` / ``host``；不可用返回 None。

    auto 在 Linux 上只认 bwrap（服务器缺 bwrap 应显式修环境，不静默降级）；
    Windows/macOS 没有命名空间能力，auto 即 host。
    """
    want = _requested_backend()
    if want == "bwrap":
        return "bwrap" if _bwrap_ready() else None
    if want == "host":
        return "host"
    if _bwrap_ready():
        return "bwrap"
    if _IS_WINDOWS or sys.platform == "darwin":
        return "host"
    return None


def sandbox_available() -> bool:
    """执行后端可用性探测（工具调用与装配提示共用）。"""
    if sandbox_backend() != "host":
        return sandbox_backend() is not None
    return _host_shell() is not None or _host_python() is not None


# ---------------------------------------------------------------- 路径与解释器


def _project_venv() -> Path | None:
    """项目自带虚拟环境（工具库全部封装于此，不依赖用户系统安装）。

    沙箱路径：src/spiritscout/tools/sandbox.py → 项目根/.venv。
    """
    root = Path(__file__).resolve().parents[3]
    candidates = [Path(os.environ["VIRTUAL_ENV"])] if os.environ.get("VIRTUAL_ENV") else []
    candidates.append(root / ".venv")
    return next((venv for venv in candidates if _venv_python(venv) is not None), None)


def _venv_python(venv: Path) -> Path | None:
    for rel in (("bin", "python3"), ("bin", "python"), ("Scripts", "python.exe")):
        candidate = venv.joinpath(*rel)
        if candidate.exists():
            return candidate
    return None


def _venv_site_dirs(venv: Path) -> list[str]:
    """site-packages：POSIX 在 lib/python*/，Windows 在 Lib/。"""
    posix = [str(p) for p in sorted(venv.glob("lib/python*/site-packages"))]
    return posix or ([str(venv / "Lib" / "site-packages")]
                     if (venv / "Lib" / "site-packages").is_dir() else [])


_BASH_CACHE: dict[str, bool] = {}


def _bash_works(path: str) -> bool:
    """真跑一次再认：System32\\bash.exe 是 WSL 启动器，WSL 没装发行版时会直接失败，
    只按路径存在判断会让每次工具调用都失败。"""
    cached = _BASH_CACHE.get(path)
    if cached is not None:
        return cached
    ok = False
    try:
        proc = subprocess.run(
            [path, "-c", "printf ok"], capture_output=True, timeout=20,
            creationflags=_NO_WINDOW if _IS_WINDOWS else 0, check=False)
        ok = proc.returncode == 0 and b"ok" in proc.stdout
    except (OSError, subprocess.SubprocessError):
        ok = False
    _BASH_CACHE[path] = ok
    return ok


def _find_bash() -> str | None:
    """host 后端优先用 bash（Git Bash / WSL 语义一致，模型写的命令多半是 sh）。

    顺序：显式覆盖 → Git for Windows 安装位 → PATH 里的 bash（排除 WSL 启动器）。
    每个候选都实测能执行才算数。
    """
    override = os.environ.get(_BASH_ENV)
    if override and Path(override).is_file():
        return override
    candidates: list[str] = []
    if _IS_WINDOWS:
        roots: list[Path] = []
        # Git 不一定装在 C:\Program Files：从 git.exe 反推安装根（也覆盖 scoop/自定义盘符）
        for exe in (shutil.which("git"), shutil.which("git.exe")):
            if exe:
                with contextlib.suppress(IndexError, OSError):
                    roots.append(Path(exe).resolve().parents[1])
        for base in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMW6432"),
                     os.environ.get("LOCALAPPDATA")):
            if base:
                roots.append(Path(base) / "Git")
                roots.append(Path(base) / "Programs" / "Git")
        seen: set[str] = set()
        for root in roots:
            for rel in (("bin", "bash.exe"), ("usr", "bin", "bash.exe"),
                        ("mingw64", "bin", "bash.exe")):
                candidate = root.joinpath(*rel)
                text = str(candidate)
                if text not in seen and candidate.is_file():
                    seen.add(text)
                    candidates.append(text)
    found = shutil.which("bash")
    if found:
        system_root = os.environ.get("SYSTEMROOT", r"C:\Windows").lower()
        if not (found.lower().startswith(system_root.lower())):
            candidates.append(found)
    for candidate in candidates:
        if _bash_works(candidate):
            return candidate
    return None


def _host_shell() -> list[str] | None:
    """host 后端的 shell 前缀；bash 用 -c（不加载 profile：避免 login shell 拖慢首调）。"""
    bash = _find_bash()
    if bash:
        return [bash, "-c"]
    if _IS_WINDOWS:
        return [os.environ.get("COMSPEC") or "cmd.exe", "/c"]
    return ["/bin/sh", "-c"]


def _host_python() -> str | None:
    venv = _project_venv()
    exe = _venv_python(venv) if venv is not None else None
    if exe is not None:
        return str(exe)
    return shutil.which("python3") or shutil.which("python")


def _host_path_dirs() -> list[str]:
    """host 后端的 PATH：项目 venv → Git Bash 工具层 → 系统基础层。

    用户主目录下的私有安装（~/.local/bin、pip --user、cargo 等）不进来。
    """
    dirs: list[str] = []
    venv = _project_venv()
    if venv is not None:
        dirs += [str(venv / "Scripts"), str(venv / "bin")]
    bash = _find_bash()
    if bash:
        git_root = Path(bash).resolve().parents[1]
        for rel in ("usr/bin", "mingw64/bin", "bin"):
            candidate = git_root / rel
            if candidate.is_dir():
                dirs.append(str(candidate))
    if _IS_WINDOWS:
        dirs += [str(Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32"),
                 os.environ.get("SYSTEMROOT", r"C:\Windows")]
    else:
        dirs += ["/usr/bin", "/bin"]
    seen: set[str] = set()
    return [d for d in dirs if not (d in seen or seen.add(d))]


def _host_env(rundir: Path) -> dict[str, str]:
    """最小环境：基础系统变量保留，HOME/TEMP 指向会话目录，其余不继承。"""
    env = {key: os.environ[key] for key in _ENV_KEEP if os.environ.get(key)}
    if _IS_WINDOWS:
        sep = ";"
        env["PATHEXT"] = env.get("PATHEXT", ".COM;.EXE;.BAT;.CMD")
    else:
        sep = ":"
    env["PATH"] = sep.join(_host_path_dirs())
    env["HOME"] = str(rundir)
    env["USERPROFILE"] = str(rundir)      # Windows 的 HOME 等价物，别让工具写回真实主目录
    env["TMPDIR"] = env["TEMP"] = env["TMP"] = str(rundir)
    env["LANG"] = "C.UTF-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    venv = _project_venv()
    site_dirs = _venv_site_dirs(venv) if venv is not None else []
    if site_dirs:
        env["PYTHONPATH"] = sep.join(site_dirs)
    return env


def _build_argv(workspace: Path, rundir: Path, inner: list[str], *,
                guard_root: Path | None = None) -> list[str]:
    """bwrap 参数：整机只读 + 控制面遮蔽 + 产物可写/附件只读 + 干净环境。

    工具来源：项目内 .venv（只读回挂并入 PATH/PYTHONPATH）——用户主目录、
    ~/.local、/usr/local 等私有安装层一律不进沙箱，智能体工具能力来自
    项目封装与发行版基础层。
    """
    home = Path.home()
    argv = [
        _BWRAP,
        "--ro-bind", "/", "/",
        "--dev", "/dev",
        "--unshare-pid",               # 不通过宿主 /proc/<pid>/root 绕过文件遮蔽
        "--proc", "/proc",
        "--tmpfs", "/tmp",
        "--tmpfs", str(home),          # 主目录遮蔽：.ssh / 密钥库不可见
        # 宿主私有安装层遮蔽：/usr/local 是手工安装落点（用户自装工具、
        # 独立分发的二进制、私有库），整层遮蔽（bin 内 sbin 是符号链接，
        # 需整目录替换而非逐项挂载）
        "--tmpfs", "/usr/local",
    ]
    # 控制面根目录整层遮蔽（Web 会话：基础工作区，vault 密钥库/兄弟会话/
    # 审计都在里面）。只遮蔽会话自身目录时，同级会话与 vault.key/vault.db
    # 在沙箱内照样可读（密钥与密文同处可读＝供应商 Key 全量可解密）。
    # 置于 .venv 回挂之前：会话工作区含项目根时不把工具层一起盖掉
    if (guard_root is not None and str(guard_root) != "/"
            and guard_root != workspace and guard_root.is_dir()
            and workspace.is_relative_to(guard_root)):
        argv += ["--tmpfs", str(guard_root)]
    venv = _project_venv()
    path_dirs = ["/usr/bin", "/bin"]
    site_dirs: list[str] = []
    if venv is not None:
        argv += ["--ro-bind", str(venv), str(venv)]
        path_dirs = [str(venv / "bin"), *path_dirs]
        site_dirs = _venv_site_dirs(venv)
    # 整个控制目录不可见，只开放约定的产物目录；同样覆盖位于 /tmp
    # 或主目录之外的工作区，不能仅靠遮蔽 execution.key 保护数据库。
    argv += ["--tmpfs", str(workspace), "--bind", str(rundir), str(rundir)]
    for name in ("attachments", "artifacts"):
        directory = workspace / name
        if directory.is_dir():
            argv += ["--ro-bind" if name == "attachments" else "--bind",
                     str(directory), str(directory)]
    # 空控制目录本身也只读，不能伪造同名控制文件；不递归改变产物挂载。
    argv += ["--remount-ro", str(workspace)]
    argv += [
        "--chdir", str(rundir),
        "--die-with-parent",
        "--clearenv",
        "--setenv", "PATH", ":".join(path_dirs),
        "--setenv", "HOME", str(rundir),
        "--setenv", "LANG", "C.UTF-8",
    ]
    if site_dirs:
        argv += ["--setenv", "PYTHONPATH", ":".join(site_dirs)]
    return [*argv, *inner]


async def _read_capped(stream: asyncio.StreamReader | None,
                       cap: int, sink=None) -> tuple[bytes, int]:
    """流式读取并限幅：完整内容逐块写入 sink（落盘，过程不丢），
    内存只保留头尾，返回（保留字节, 实际总量）。"""
    if stream is None:
        return b"", 0
    head_cap = cap * 3 // 4
    tail_cap = cap - head_cap
    head = bytearray()
    tail = bytearray()
    total = 0
    while True:
        chunk = await stream.read(_READ_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if sink is not None:
            try:
                sink.write(chunk)
            except OSError:  # 落盘失败不影响执行与限幅读取
                sink = None
        if len(head) < head_cap:
            take = min(head_cap - len(head), len(chunk))
            head.extend(chunk[:take])
            chunk = chunk[take:]
        if chunk and tail_cap:
            tail.extend(chunk)
            if len(tail) > tail_cap:
                del tail[:-tail_cap]
    return bytes(head + tail), total


def _kill_group(proc: asyncio.subprocess.Process) -> None:
    """杀整个进程组：POSIX 杀 pgid；Windows 用 taskkill /T 连带子进程。"""
    if _IS_WINDOWS:
        with contextlib.suppress(OSError):
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, creationflags=_NO_WINDOW,
                           timeout=10, check=False)
        return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)


def _force_close(proc: asyncio.subprocess.Process) -> None:
    """Windows 收口：进程树已被 taskkill 杀掉，但 MSYS/管道句柄不保证发 EOF。

    直接关传输层，避免 wait() 与读取任务永久挂住（一次超时拖住整条回合）。
    """
    transport = getattr(proc, "_transport", None)
    if transport is not None:
        with contextlib.suppress(BaseException):
            transport.close()
    with contextlib.suppress(BaseException):
        if proc.returncode is None:
            proc.kill()


def _decode(data: bytes, total: int, cap: int) -> str:
    """解码限幅输出；被截断时在保留的头尾之间标明丢弃量。"""
    if total <= cap:
        return data.decode(errors="replace")
    head_cap = cap * 3 // 4
    dropped = total - len(data)
    return (data[:head_cap].decode(errors="replace")
            + f"\n...[输出超限，已丢弃 {dropped} 字节]...\n"
            + data[head_cap:].decode(errors="replace"))


async def sandbox_exec(
    code: str,
    *,
    language: str = "shell",
    timeout: float = 60.0,
    workspace_root: str | None = None,
    workspace_scope: str | None = None,
    guard_root: str | None = None,
    log_name: str = "last_output",
    max_output_chars: int = 20000,
    **_: Any,
) -> ToolResult:
    """沙箱执行：language=shell 跑 shell；language=python 落盘后由项目 venv 运行。

    ok 语义：进程正常结束（任何退出码）即 ok=True——退出码非零是结果不是
    工具故障；只有后端不可用 / 启动失败 / 超时被终止才 ok=False。
    workspace_scope：工作目录作用域（调用方传题级 id 等）。非空时工作目录
    细分为 ``sandbox/<scope>/``——多题并行时各题产物、脚本与日志互不覆盖；
    缺省时沿用会话级 ``sandbox/``（SRC 等单目标场景不受影响）。
    """
    started = time.perf_counter()
    code = str(code or "")
    if not code.strip():
        return ToolResult(tool="sandbox_exec", ok=False, returncode=-1,
                          error="执行内容为空")
    backend = sandbox_backend()
    if backend is None or (backend == "host" and _host_shell() is None
                           and not _host_python()):
        return ToolResult(tool="sandbox_exec", ok=False, returncode=-1, error=(
            "执行后端不可用：Linux 需要 bubblewrap（bwrap）并确认命名空间权限；"
            "Windows/macOS 需要 bash（Git Bash）或本机 Python。"
            "本次未在宿主直接执行任何命令。"))
    if not workspace_root:
        return ToolResult(tool="sandbox_exec", ok=False, returncode=-1,
                          error="缺少工作区配置（workspace_root）")
    try:
        timeout = max(_MIN_TIMEOUT, min(float(timeout), _MAX_TIMEOUT))
    except (TypeError, ValueError):
        timeout = 60.0
    lang = "python" if str(language).lower() == "python" else "shell"
    workspace = Path(workspace_root).resolve()
    try:
        workspace.mkdir(parents=True, exist_ok=True)
        # 不允许旧脚本留下的目录符号链接将控制目录重新挂进沙箱。
        for name in ("sandbox", "attachments", "artifacts"):
            if (workspace / name).is_symlink():
                raise OSError(f"沙箱共享目录不能是符号链接: {name}")
        # 会话持久工作目录：workspace_root 即会话工作区，跨调用保留产物，
        # 供后续回合与附件工具继续使用（/tmp 为每运行 tmpfs，不持久）；
        # 题级作用域在会话工作区内再细分一层（多题并行互不覆盖）。
        rundir = workspace / "sandbox"
        if workspace_scope:
            safe = re.sub(r"[^A-Za-z0-9._-]+", "_", str(workspace_scope)).strip("._-")[:80]
            if safe:
                rundir = rundir / safe
        rundir.mkdir(parents=True, exist_ok=True)
        (workspace / "artifacts").mkdir(exist_ok=True)
        (workspace / "attachments").mkdir(exist_ok=True)
    except OSError as exc:
        return ToolResult(tool="sandbox_exec", ok=False, returncode=-1,
                          error=f"沙箱工作区不可用: {exc}")

    # host 后端没有命名空间，补一层只作用于本会话目录的 ACL 收口：会话目录去继承
    # （别的本地账户读不到本次证据），证据目录 deny 写（Agent 改不了自己的判定依据）。
    # 拿不到权限或非 Windows 时跳过，不阻断执行，原因随 parsed.hardening 留痕。
    hardening = None
    if backend == "host":
        from spiritscout.tools import host_guard

        report = host_guard.harden(workspace, (workspace / "attachments",))
        hardening = report.as_dict()

    env: dict[str, str] | None = None
    popen_kwargs: dict[str, Any] = {}
    if lang == "python":
        script = rundir / f"run_{int(time.time() * 1000)}_{os.urandom(3).hex()}.py"
        script.write_text(code, encoding="utf-8")
        py = _host_python() if backend == "host" else None
        if backend == "bwrap":
            venv = _project_venv()
            inner = [str(venv / "bin" / "python3") if venv is not None else "python3",
                     str(script)]
        else:
            if py is None:
                return ToolResult(tool="sandbox_exec", ok=False, returncode=-1,
                                  error="host 后端缺少可用 Python 解释器")
            inner = [py, str(script)]
    else:
        if backend == "bwrap":
            inner = ["bash", "-c", code]
        else:
            shell = _host_shell()
            if shell is None:
                return ToolResult(tool="sandbox_exec", ok=False, returncode=-1,
                                  error="host 后端缺少可用 shell（装 Git Bash 或改 SPIRITSCOUT_HOST_BASH）")
            inner = [*shell, code]

    if backend == "bwrap":
        guard = Path(guard_root).resolve() if guard_root else None
        argv = _build_argv(workspace, rundir, inner, guard_root=guard)
        popen_kwargs["start_new_session"] = True
    else:
        argv = inner
        env = _host_env(rundir)
        if _IS_WINDOWS:
            popen_kwargs["creationflags"] = _NO_WINDOW | _NEW_GROUP
        else:
            popen_kwargs["start_new_session"] = True

    guard = TreeGuard()
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=str(rundir), env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            **popen_kwargs)
    except OSError as exc:
        guard.close()
        return ToolResult(tool="sandbox_exec", ok=False, returncode=-1,
                          error=f"执行启动失败（{backend}）: {exc}")
    # 正常结束也要收口后代：命令里 `cmd &` 拉起的后台进程不许在工具返回后继续写文件
    guard.attach(proc.pid)

    cap = max(1000, int(max_output_chars))
    # 完整输出逐块落盘（工作目录内，跨调用可查）——上下文只进头尾摘要，
    # 过程不因截断而丢失；需要细节时模型用沙箱按需读取该文件
    log_name = Path(str(log_name)).name[:160] or "last_output"
    log_path = None
    try:
        # 同题分支和同回合多工具可能同名并发，返回的证据路径必须永久对应本次调用。
        fd, filename = tempfile.mkstemp(prefix=f"{log_name}-", suffix=".log", dir=rundir)
        os.close(fd)
        log_path = Path(filename)
        # 日志代际轮转：单文件超限就把上一代挪到 .old——完整过程保留最近
        # 两代，磁盘占用有界；模型读取的 output_file 始终指向当前代
        log_fh = _RotatingLog(log_path)
    except OSError:
        log_fh = None
        log_path = None
    out_task = asyncio.create_task(_read_capped(proc.stdout, cap, sink=log_fh))
    err_task = asyncio.create_task(_read_capped(proc.stderr, cap, sink=log_fh))
    timed_out = False
    try:
        async with guard.tracking():
            try:
                await asyncio.wait_for(proc.wait(), timeout=timeout)
            except TimeoutError:
                timed_out = True
                _kill_group(proc)
                if _IS_WINDOWS:
                    _force_close(proc)
                else:
                    with contextlib.suppress(BaseException):
                        await asyncio.wait_for(proc.wait(), timeout=5)
    except BaseException:
        # 取消（会话停止）/异常路径：tracking 退出时已先收口后代（此时父进程还活着，
        # 进程树完整），这里只补父进程与管道清理，然后原样抛出——不残留沙箱进程
        _kill_group(proc)
        if _IS_WINDOWS:
            _force_close(proc)
        else:
            with contextlib.suppress(BaseException):
                await asyncio.wait_for(proc.wait(), timeout=5)
        out_task.cancel()
        err_task.cancel()
        with contextlib.suppress(BaseException):
            await asyncio.gather(out_task, err_task, return_exceptions=True)
        if log_fh is not None:
            log_fh.close()
        raise
    # 直接子进程已退出：tracking 已把 `cmd &` 式后台子进程一并带走，管道随之关闭
    try:
        # 超时/被杀后管道可能不再发 EOF：只等一小会儿，拿已读到的部分收尾
        (out_b, out_total), (err_b, err_total) = await asyncio.wait_for(
            asyncio.gather(out_task, err_task), timeout=0.8 if timed_out else 5)
    except TimeoutError:
        out_task.cancel()
        err_task.cancel()
        await asyncio.gather(out_task, err_task, return_exceptions=True)
        out_b = err_b = b""
        out_total = err_total = 0
    finally:
        if log_fh is not None:
            log_fh.close()
    rc = proc.returncode if proc.returncode is not None else -1

    duration = (time.perf_counter() - started) * 1000
    stdout = _decode(out_b, out_total, max_output_chars)
    stderr = _decode(err_b, err_total, max_output_chars)
    return ToolResult(
        tool="sandbox_exec", ok=not timed_out, returncode=rc,
        stdout=stdout, stderr=stderr, timed_out=timed_out,
        parsed={"language": lang, "exit_code": rc, "sandbox": backend,
                "duration_ms": round(duration, 1), "workdir": str(rundir),
                "hardening": hardening or {},
                "output_file": str(log_path) if log_path else "",
                "output_rotated": bool(log_fh and log_fh.rotated),
                "previous_output_file": str(log_fh.previous)
                if log_fh and log_fh.previous.exists() else ""},
        error=(f"执行超时（{timeout:.0f}s），进程已终止" if timed_out else ""),
        duration_ms=duration,
    )
