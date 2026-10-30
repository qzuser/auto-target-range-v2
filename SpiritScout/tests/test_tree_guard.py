"""TreeGuard：一次工具调用的进程树收口器（跨平台）。

Windows 没有进程组语义，父进程退出后 `taskkill /T` 找不到树；`TreeGuard` 用
作业对象 + 运行期采样 + 退出快照兜住后代。这里只测契约，不依赖具体实现层：
`backend` 报机制、`attach/close` 幂等、死后代被收口。
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

from spiritscout.platform_support import TreeGuard

try:                              # discover 把 tests/ 直接挂在 sys.path 上
    from tests.process_budget import reap_window
except ImportError:               # 直接跑 `-m unittest test_tree_guard` 时
    from process_budget import reap_window


class TreeGuardContractTests(unittest.TestCase):
    def test_backend_reports_mechanism(self) -> None:
        guard = TreeGuard()
        try:
            if sys.platform == "win32":
                self.assertIn(guard.backend, {"job", "none"})
            else:
                self.assertEqual(guard.backend, "pgid")
        finally:
            guard.close()

    def test_close_without_attach_is_safe_and_idempotent(self) -> None:
        guard = TreeGuard()
        guard.close()
        guard.close()

    def test_attach_dead_pid_does_not_raise(self) -> None:
        guard = TreeGuard()
        try:
            guard.attach(0x7FFFFFF0)      # 不存在的进程：收口器要降级而不是抛错
            guard.close()
        finally:
            guard.close()


class TreeGuardReapTests(unittest.IsolatedAsyncioTestCase):
    async def test_close_reaps_grandchild_after_parent_exit(self) -> None:
        """父进程先退出也要带走孙进程——正是 Windows 上原来的漏洞点。"""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            marker = Path(tmp) / "late"
            ready = Path(tmp) / "child-up"
            child = ("import time; from pathlib import Path; "
                     f"Path({str(ready)!r}).write_text('up'); time.sleep(.5); "
                     f"Path({str(marker)!r}).write_text('late')")
            # 父进程等孙进程真的起来再退出。不然机器一慢，孙进程还没被枚举到父就
            # 已经走完，收口器手上什么都没拿到——那测的是启动速度，不是「父退出后
            # 仍要收口后代」。等 ready 也顺带保证 marker 一定在父退出之后才可能写出。
            parent = ("import subprocess,sys,time; from pathlib import Path; "
                      f"subprocess.Popen([sys.executable,'-c',{child!r}]); "
                      "deadline=time.time()+15\n"
                      f"while not Path({str(ready)!r}).exists() and time.time()<deadline: "
                      "time.sleep(.01)")
            guard = TreeGuard()
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-c", parent,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            guard.attach(proc.pid)
            async with guard.tracking():
                await asyncio.wait_for(proc.wait(), timeout=30)
            await asyncio.sleep(reap_window(.5))
            self.assertFalse(marker.exists(), "父进程退出后孙进程仍在写文件")

    async def test_tracking_enters_and_leaves_cleanly(self) -> None:
        guard = TreeGuard()
        async with guard.tracking():
            pass
        self.assertTrue(guard._closed, "退出保护区即完成收口")


if __name__ == "__main__":
    unittest.main()

