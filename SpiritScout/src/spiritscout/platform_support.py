"""原生平台的进程与 Node.js 入口；不借助 shell 解释用户参数。"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

# 采样间隔：venv 的 python.exe 转发进程活得很短，太稀会漏掉中间那一环
_WIN_SAMPLE_INTERVAL = 0.08


def process_options() -> dict[str, Any]:
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


_BENIGN_LOOP_ERRORS = (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)
"""客户端断开长连接时事件循环抛的「异常」，服务本身没事。"""


def quiet_event_loop_errors() -> None:
    """让「浏览器/SSE 客户端断开」不再打印成 traceback。

    Windows 的 Proactor 在客户端强断（关标签页、切网络、Ctrl+C 掉客户端）时会
    在 ``_call_connection_lost`` 回调里抛 ``ConnectionResetError: [WinError 10054]
    远程主机强迫关闭了一个现有的连接``。这是 asyncio 在回调里无人可抛的噪音，
    日志里看着像服务崩了，实际一切正常。只对这几类连接错误静默，其它异常照旧
    走默认处理器——不掩盖真正的故障。
    """

    class _QuietPolicy(asyncio.DefaultEventLoopPolicy):
        def new_event_loop(self) -> asyncio.AbstractEventLoop:
            loop = super().new_event_loop()
            loop.set_exception_handler(_quiet_handler)
            return loop

    with contextlib.suppress(Exception):
        asyncio.set_event_loop_policy(_QuietPolicy())


def _quiet_handler(loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
    exc = context.get("exception")
    if isinstance(exc, _BENIGN_LOOP_ERRORS):
        return
    loop.default_exception_handler(context)


def force_utf8_streams() -> None:
    """把控制台/管道输出钉成 UTF-8。

    中文 Windows 的控制台默认 cp936：中文提示写进管道后，父进程按 UTF-8 读会
    解码失败（`UnicodeDecodeError: 0xd5`），`subprocess` 的读线程随之崩掉、
    `stderr` 直接变成 None。凡是可能被别的程序消费的输出都走这里统一。
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")


class TreeGuard:
    """一次执行的进程树收口器：直接子进程退出后，后代也不许再活下去。

    POSIX 靠独立进程组（`start_new_session` 让 pgid == 子进程 pid），父进程退出后
    `killpg` 仍能扫到同组后代。Windows 没有这套语义——父进程一退出，`taskkill /T`
    就再也找不到可遍历的树，孤儿孙进程会继续写文件。因此 Windows 叠三层：

    1. 作业对象（`KILL_ON_JOB_CLOSE`）：成员随句柄关闭连坐终止；
    2. 运行期采样：venv 的 `python.exe` 是转发器，会拉起真正的解释器当子进程，
       中间进程一旦先退出，从快照按 ppid 回溯就断链，只有事先记下 pid 才追得动；
    3. 退出复核：再回溯一次，收掉采样间隙内新起的子进程。

    三层都不成立时退回 `taskkill /T` 的旧行为；`backend` 如实报告当前机制。
    """

    __slots__ = ("_closed", "_job", "_pid", "_seen", "backend")

    def __init__(self) -> None:
        self._pid: int | None = None
        self._seen: set[int] = set()
        self._closed = False
        self._job = _win_job_create() if sys.platform == "win32" else None
        if sys.platform != "win32":
            self.backend = "pgid"
        else:
            self.backend = "job" if self._job else "none"

    def attach(self, pid: int) -> None:
        self._pid = pid
        if self._job and not _win_job_assign(self._job, pid):
            # 加入失败就关掉句柄，别把进程留在半套机制里；采样与复核仍然有效
            _win_job_close(self._job)
            self._job = None
            self.backend = "none"

    @contextlib.asynccontextmanager
    async def tracking(self) -> AsyncIterator[None]:
        """覆盖一次等待：期间持续采样后代，退出时停采样并收口。"""
        self._collect()                     # 进保护区先记一次，不等采样任务首次调度
        sampler = asyncio.create_task(self._sample())
        try:
            yield
        finally:
            sampler.cancel()
            with contextlib.suppress(BaseException):
                await asyncio.gather(sampler, return_exceptions=True)
            self.close()

    async def _sample(self, interval: float = _WIN_SAMPLE_INTERVAL) -> None:
        if sys.platform != "win32":
            return
        while True:
            self._collect()
            await asyncio.sleep(interval)

    def _collect(self) -> set[int]:
        """把当前能追溯到的后代并入记录集，返回新增部分。"""
        if self._pid is None or sys.platform != "win32":
            return set()
        fresh = _win_descendants(self._pid, self._seen) - self._seen
        self._seen |= fresh
        return fresh

    def close(self) -> None:
        """终止仍活着的后代；可重复调用——已收口过就直接返回，不做二次复核。"""
        if self._closed:
            return
        self._closed = True
        if self._pid is None:
            return
        if sys.platform != "win32":
            with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
                os.killpg(self._pid, signal.SIGKILL)
            return
        self._collect()
        _win_kill_pids(self._seen | _win_descendants(self._pid))
        if self._job:
            _win_job_close(self._job)      # 关句柄即连坐（成员继承时生效）
            self._job = None
        # 采样间隙里刚起的子进程可能晚一步才可见：复核一次再收工
        time.sleep(0.03)
        self._collect()
        _win_kill_pids(self._seen)


_WIN: dict[str, Any] = {}


def _win_api() -> dict[str, Any]:  # pragma: no cover —— 仅 Windows
    """惰性构建 ctypes 句柄、结构与常量；全模块共用一份。"""
    if _WIN:
        return _WIN
    import ctypes
    from ctypes import wintypes

    class IoCounters(ctypes.Structure):
        _fields_ = [("ReadOperationCount", ctypes.c_ulonglong),
                    ("WriteOperationCount", ctypes.c_ulonglong),
                    ("OtherOperationCount", ctypes.c_ulonglong),
                    ("ReadTransferCount", ctypes.c_ulonglong),
                    ("WriteTransferCount", ctypes.c_ulonglong),
                    ("OtherTransferCount", ctypes.c_ulonglong)]

    class BasicLimits(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
                    ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
                    ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BasicLimits),
                    ("IoInfo", IoCounters),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    class ProcessEntry32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD),
                    ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle, bool_, dword, ptr = wintypes.HANDLE, wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p
    for name, res, args in (
        ("CreateJobObjectW", handle, [ptr, wintypes.LPCWSTR]),
        ("SetInformationJobObject", bool_, [handle, ctypes.c_int, ptr, dword]),
        ("AssignProcessToJobObject", bool_, [handle, handle]),
        ("OpenProcess", handle, [dword, bool_, dword]),
        ("CloseHandle", bool_, [handle]),
        ("TerminateProcess", bool_, [handle, wintypes.UINT]),
        ("CreateToolhelp32Snapshot", handle, [dword, dword]),
        ("Process32FirstW", bool_, [handle, ctypes.POINTER(ProcessEntry32W)]),
        ("Process32NextW", bool_, [handle, ctypes.POINTER(ProcessEntry32W)]),
    ):
        getattr(k32, name).restype = res
        getattr(k32, name).argtypes = args
    _WIN.update(k32=k32, ExtendedLimits=ExtendedLimits, ProcessEntry32W=ProcessEntry32W,
                JobObjectExtendedLimitInformation=9, KillOnJobClose=0x2000,
                ProcessSetQuota=0x0100, ProcessTerminate=0x0001,
                TH32CS_SNAPPROCESS=0x00000002)
    return _WIN


def _win_job_create() -> int | None:  # pragma: no cover —— 仅 Windows
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        api = _win_api()
        k32 = api["k32"]
        if not (job := k32.CreateJobObjectW(None, None)):
            return None
        limits = api["ExtendedLimits"]()
        limits.BasicLimitInformation.LimitFlags = api["KillOnJobClose"]
        ok = k32.SetInformationJobObject(job, api["JobObjectExtendedLimitInformation"],
                                         ctypes.byref(limits), ctypes.sizeof(limits))
        if ok:
            return int(job)
        k32.CloseHandle(job)
        return None
    except (OSError, AttributeError):
        return None


def _win_job_assign(job: int, pid: int) -> bool:  # pragma: no cover —— 仅 Windows
    try:
        api = _win_api()
        k32 = api["k32"]
        handle = k32.OpenProcess(api["ProcessSetQuota"] | api["ProcessTerminate"], False, pid)
        if not handle:
            return False
        try:
            return bool(k32.AssignProcessToJobObject(job, handle))
        finally:
            k32.CloseHandle(handle)
    except OSError:
        return False


def _win_job_close(job: int) -> None:  # pragma: no cover —— 仅 Windows
    with contextlib.suppress(OSError, AttributeError):
        _win_api()["k32"].CloseHandle(job)


def _win_snapshot() -> dict[int, int]:  # pragma: no cover —— 仅 Windows
    """一次进程快照：pid -> 父 pid。父进程死后父 pid 字段仍保留。"""
    import ctypes

    api = _win_api()
    k32 = api["k32"]
    snapshot = k32.CreateToolhelp32Snapshot(api["TH32CS_SNAPPROCESS"], 0)
    if snapshot in (0, -1):
        return {}
    entry_type = api["ProcessEntry32W"]
    parents: dict[int, int] = {}
    try:
        entry = entry_type()
        entry.dwSize = ctypes.sizeof(entry_type)
        if k32.Process32FirstW(snapshot, ctypes.byref(entry)):
            while True:
                parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
                if not k32.Process32NextW(snapshot, ctypes.byref(entry)):
                    break
    finally:
        k32.CloseHandle(snapshot)
    return parents


def _win_kill_pids(pids: Any) -> int:  # pragma: no cover —— 仅 Windows
    """终止给定 pid 集合里仍活着的进程，返回成功数。"""
    if sys.platform != "win32" or not pids:
        return 0
    api = _win_api()
    k32 = api["k32"]
    killed = 0
    for pid in pids:
        handle = k32.OpenProcess(api["ProcessTerminate"], False, pid)
        if not handle:
            continue
        try:
            killed += bool(k32.TerminateProcess(handle, 1))
        finally:
            k32.CloseHandle(handle)
    return killed


def _win_descendants(root_pid: int, known: Any = ()) -> set[int]:  # pragma: no cover —— 仅 Windows
    """按一次快照回溯 root_pid 的整棵子进程树（按 ppid 迭代到不动点）。

    `known` 是已经确认过的后代 pid：中间转发进程先退出后链条会断，
    以它们为额外起点仍能接上更下面的孙进程。
    """
    if sys.platform != "win32":
        return set()
    parents = _win_snapshot()
    if not parents:
        return set()
    descendants: set[int] = set()
    frontier = {root_pid} | set(known)
    while frontier:
        step = {pid for pid, ppid in parents.items()
                if ppid in frontier and pid not in descendants and pid != root_pid}
        if not step:
            break
        descendants |= step
        frontier = step
    return descendants


def _win_kill_descendants(root_pid: int) -> int:  # pragma: no cover —— 仅 Windows
    """按快照把 root_pid 的整棵子进程树终止，返回成功终止的进程数。"""
    return _win_kill_pids(_win_descendants(root_pid))


def kill_process_tree(process: Any) -> None:
    """Unix 清理独立进程组；Windows 使用系统任务树终止，失败再终止父进程。"""
    if sys.platform == "win32":
        if process.returncode is not None:
            return
        with contextlib.suppress(OSError, subprocess.TimeoutExpired):
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=5, check=False)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
            return
        except (ProcessLookupError, PermissionError, OSError):
            pass
    with contextlib.suppress(ProcessLookupError):
        process.kill()


def node_cli_command(name: str) -> list[str]:
    """Windows 的 npm/npx 是 .cmd；直接执行其 JS 入口，避免 cmd.exe 引号注入。"""
    executable = shutil.which(name)
    if not executable:
        raise ValueError(f"找不到 {name}，请安装 Node.js 22+")
    if sys.platform == "win32" and Path(executable).suffix.lower() in {".cmd", ".bat"}:
        cli = Path(executable).parent / "node_modules" / "npm" / "bin" / f"{name}-cli.js"
        node = shutil.which("node")
        if node and cli.is_file():
            return [node, str(cli)]
        raise ValueError(f"找不到 {name} 的 Node.js CLI，请修复 Node.js 安装或使用 Docker")
    return [executable]


def chrome_executable(env: dict[str, str]) -> str:
    """显式路径优先，再找 PATH 和 Windows/macOS 的标准安装位置。"""
    if env.get("SPIRITSCOUT_CHROME_EXECUTABLE"):
        return str(Path(env["SPIRITSCOUT_CHROME_EXECUTABLE"]).expanduser())
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        if found := shutil.which(name):
            return found
    candidates: list[Path] = []
    if sys.platform == "darwin":
        for root in (Path("/Applications"), Path.home() / "Applications"):
            candidates += [root / "Google Chrome.app/Contents/MacOS/Google Chrome",
                           root / "Chromium.app/Contents/MacOS/Chromium"]
    elif sys.platform == "win32":
        for key, fallback in (("PROGRAMFILES", "C:/Program Files"),
                              ("PROGRAMFILES(X86)", "C:/Program Files (x86)"),
                              ("LOCALAPPDATA", str(Path.home() / "AppData/Local"))):
            candidates.append(Path(env.get(key) or fallback) / "Google/Chrome/Application/chrome.exe")
    return next((str(path) for path in candidates if path.is_file()), "")


