"""Desktop process lifetime guard.

The native desktop owns the local web backend. If the desktop JVM exits
without running its normal shutdown path, the backend must not remain
reachable as an orphaned local web server.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable

import psutil

PARENT_PID_ENV = "SPIRITSCOUT_DESKTOP_PARENT_PID"
PARENT_START_ENV = "SPIRITSCOUT_DESKTOP_PARENT_START_MS"


def parent_alive(pid: int, start_ms: int | None = None) -> bool:
    if pid <= 1:
        return False
    try:
        process = psutil.Process(pid)
        if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
            return False
        if start_ms is not None:
            created_ms = round(process.create_time() * 1000)
            if abs(created_ms - start_ms) > 2_000:
                return False
        return True
    except psutil.NoSuchProcess:
        return False
    except (psutil.AccessDenied, OSError):
        # AccessDenied means the process still exists; do not kill the backend.
        return True


def install_parent_watchdog(
    *,
    exit_callback: Callable[[int], None] | None = None,
    interval_seconds: float = 1.0,
    parent_pid_override: int | None = None,
    parent_start_ms_override: int | None = None,
) -> threading.Thread | None:
    if parent_pid_override is not None:
        parent_pid = parent_pid_override
    else:
        raw_pid = os.environ.get(PARENT_PID_ENV, "").strip()
        if not raw_pid:
            return None
        try:
            parent_pid = int(raw_pid)
        except ValueError:
            return None
    if parent_start_ms_override is not None:
        parent_start_ms = parent_start_ms_override
    else:
        raw_start = os.environ.get(PARENT_START_ENV, "").strip()
        try:
            parent_start_ms = int(raw_start) if raw_start else None
        except ValueError:
            parent_start_ms = None
    callback = exit_callback or exit_process_tree

    def watch() -> None:
        while True:
            if not parent_alive(parent_pid, parent_start_ms):
                callback(0)
                return
            time.sleep(max(0.05, interval_seconds))

    thread = threading.Thread(
        target=watch,
        name="spiritscout-desktop-parent-watchdog",
        daemon=True,
    )
    thread.start()
    return thread


def exit_process_tree() -> None:
    """Exit the orphaned backend after terminating its child process tree."""
    current = psutil.Process()
    children = current.children(recursive=True)
    for child in reversed(children):
        try:
            child.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    _, alive = psutil.wait_procs(children, timeout=1.5)
    for child in alive:
        try:
            child.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    os._exit(0)
