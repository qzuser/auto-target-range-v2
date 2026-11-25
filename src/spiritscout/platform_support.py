"""原生平台的进程与 Node.js 入口；不借助 shell 解释用户参数。"""

from __future__ import annotations

import contextlib
import ctypes
import os
import shutil
import signal
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Any

import psutil


def is_frozen() -> bool:
    """是否为 PyInstaller 等冻结构建（源码运行返回 False）。"""
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    """发行包可指定可写的数据目录；裸单文件默认使用程序旁边。"""
    if is_frozen():
        if value := os.environ.get("SPIRITSCOUT_DATA_HOME"):
            return Path(value).expanduser().resolve()
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def bundle_root() -> Path:
    """只读资源根：源码为仓库根，冻结构建为 PyInstaller 解包目录。"""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", app_root()))
    return Path(__file__).resolve().parents[2]


def process_options() -> dict[str, Any]:
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


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


class ProcessTreeTracker:
    """Track Windows descendants before the direct parent exits."""

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self._descendants: dict[tuple[int, float], None] = {}

    def poll(self) -> None:
        if sys.platform != "win32":
            return
        try:
            children = psutil.Process(self.pid).children(recursive=True)
        except (psutil.Error, OSError):
            return
        for child in children:
            try:
                self._descendants[(child.pid, child.create_time())] = None
            except (psutil.Error, OSError):
                continue

    def terminate(self) -> None:
        if sys.platform != "win32":
            return
        self.poll()
        for pid, created_at in reversed(list(self._descendants)):
            try:
                process = psutil.Process(pid)
                if abs(process.create_time() - created_at) > 0.01:
                    continue
                process.kill()
            except (psutil.Error, OSError):
                continue


class _JobBasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class _JobExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JobBasicLimits),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class WindowsJob:
    """Assign a command and its descendants to a kill-on-close job object."""

    _KILL_ON_CLOSE = 0x00002000
    _EXTENDED_LIMIT_INFORMATION = 9

    def __init__(self) -> None:
        self.handle: int | None = None

    @classmethod
    def attach(cls, process: Any) -> WindowsJob | None:
        if sys.platform != "win32":
            return None
        job = cls()
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.TerminateJobObject.restype = wintypes.BOOL
        job.handle = kernel32.CreateJobObjectW(None, None)
        if not job.handle:
            return None
        limits = _JobExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = cls._KILL_ON_CLOSE
        if not kernel32.SetInformationJobObject(
            job.handle,
            cls._EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            job.terminate()
            return None
        process_handle = getattr(getattr(process, "_transport", None), "_proc", None)
        process_handle = getattr(process_handle, "_handle", None)
        if not process_handle or not kernel32.AssignProcessToJobObject(
            job.handle, wintypes.HANDLE(int(process_handle))
        ):
            job.terminate()
            return None
        # Attach any child that was created in the short interval before the
        # root process was assigned. New descendants inherit the job directly.
        try:
            children = psutil.Process(process.pid).children(recursive=True)
        except (psutil.Error, OSError):
            children = []
        for child in children:
            child_handle = kernel32.OpenProcess(0x0100 | 0x0001, False, child.pid)
            if not child_handle:
                continue
            try:
                kernel32.AssignProcessToJobObject(
                    job.handle, wintypes.HANDLE(child_handle))
            finally:
                kernel32.CloseHandle(child_handle)
        return job

    def terminate(self) -> None:
        if not self.handle:
            return
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.TerminateJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.TerminateJobObject(self.handle, 1)
        kernel32.CloseHandle(self.handle)
        self.handle = None


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
