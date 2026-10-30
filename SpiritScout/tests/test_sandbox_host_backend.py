"""host 后端（Windows/macOS 无 bwrap）：执行、隔离边界、超时收口、输出落盘。

隔离语义按后端分级：bwrap 断言「整机只读 + 主目录遮蔽」（见 test_audit_repairs）；
host 后端只承诺「工作目录锁定 + 环境白名单 + 超时杀进程树 + 输出限幅」。
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

from spiritscout.tools.sandbox import (
    sandbox_available,
    sandbox_backend,
    sandbox_exec,
)

_HOST_ONLY = unittest.skipUnless(
    sandbox_backend() == "host", "只在 host 后端（Windows/macOS 无 bwrap）验证")


class BackendResolutionTests(unittest.TestCase):
    def test_explicit_bwrap_without_binary_is_unavailable(self) -> None:
        previous = os.environ.get("SPIRITSCOUT_SANDBOX_BACKEND")
        os.environ["SPIRITSCOUT_SANDBOX_BACKEND"] = "bwrap"
        try:
            if sys.platform.startswith("linux") and sandbox_backend() == "bwrap":
                self.skipTest("本机确有 bwrap")
            self.assertIsNone(sandbox_backend())
            self.assertFalse(sandbox_available())
        finally:
            if previous is None:
                os.environ.pop("SPIRITSCOUT_SANDBOX_BACKEND", None)
            else:
                os.environ["SPIRITSCOUT_SANDBOX_BACKEND"] = previous

    def test_unknown_value_falls_back_to_auto(self) -> None:
        previous = os.environ.get("SPIRITSCOUT_SANDBOX_BACKEND")
        os.environ["SPIRITSCOUT_SANDBOX_BACKEND"] = "banana"
        try:
            self.assertIn(sandbox_backend(), {"bwrap", "host", None})
        finally:
            if previous is None:
                os.environ.pop("SPIRITSCOUT_SANDBOX_BACKEND", None)
            else:
                os.environ["SPIRITSCOUT_SANDBOX_BACKEND"] = previous


@_HOST_ONLY
class HostBackendTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    async def test_shell_runs_with_common_unix_utilities(self) -> None:
        result = await sandbox_exec(
            "printf 'a\\nb\\n' | grep b | sed 's/b/B/'", workspace_root=str(self.root))
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "B")
        self.assertEqual(result.parsed["sandbox"], "host")

    async def test_python_uses_project_venv(self) -> None:
        result = await sandbox_exec(
            "import sys; print(sys.prefix)", language="python",
            workspace_root=str(self.root))
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(".venv", result.stdout)

    async def test_workdir_is_scoped_per_challenge_and_persistent(self) -> None:
        first = await sandbox_exec("echo A > marker", workspace_root=str(self.root),
                                   workspace_scope="e1-01")
        second = await sandbox_exec("echo B > marker", workspace_root=str(self.root),
                                    workspace_scope="e1-02")
        self.assertTrue(first.ok and second.ok, first.error + second.error)
        self.assertEqual(Path(first.parsed["workdir"]).parent.name, "sandbox")
        self.assertEqual(Path(first.parsed["workdir"]).name, "e1-01")
        self.assertEqual((self.root / "sandbox" / "e1-01" / "marker").read_text().strip(), "A")
        self.assertEqual((self.root / "sandbox" / "e1-02" / "marker").read_text().strip(), "B")

    async def test_timeout_kills_process_tree_without_hanging(self) -> None:
        started = time.perf_counter()
        result = await sandbox_exec("sleep 30 & sleep 30", workspace_root=str(self.root),
                                    timeout=5)
        spent = time.perf_counter() - started
        self.assertTrue(result.timed_out)
        self.assertFalse(result.ok)
        self.assertLess(spent, 20, f"超时收口过慢：{spent:.1f}s")

    async def test_output_capped_but_full_log_persisted(self) -> None:
        result = await sandbox_exec(
            "for i in $(seq 1 4000); do echo line-$i; done",
            workspace_root=str(self.root), max_output_chars=2000)
        self.assertTrue(result.ok, result.error)
        self.assertLess(len(result.stdout), 4000)
        self.assertIn("丢弃", result.stdout)
        log = Path(result.parsed["output_file"])
        self.assertTrue(log.is_file())
        self.assertGreater(log.stat().st_size, 20000)

    async def test_host_env_is_whitelisted(self) -> None:
        os.environ["SPIRITSCOUT_LEAK_PROBE"] = "must-not-leak"
        try:
            result = await sandbox_exec('echo "[${SPIRITSCOUT_LEAK_PROBE}]"',
                                        workspace_root=str(self.root))
        finally:
            os.environ.pop("SPIRITSCOUT_LEAK_PROBE", None)
        self.assertTrue(result.ok, result.error)
        self.assertNotIn("must-not-leak", result.stdout)

    async def test_blank_code_rejected(self) -> None:
        result = await sandbox_exec("   ", workspace_root=str(self.root))
        self.assertFalse(result.ok)
        self.assertIn("执行内容为空", result.error)


if __name__ == "__main__":
    unittest.main()
