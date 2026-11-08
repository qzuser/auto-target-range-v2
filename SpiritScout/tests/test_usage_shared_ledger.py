"""共享用量账本：解题用量要落进「用量」页读的那本库，不能跟着会话目录消失。

0.36.5 及以前 `runtime` 把账本绑在会话工作区（`sessions/<id>/usage.db`），
而「用量」页读的是基础工作区的共享库，于是「跑了题、花了 token、页面还是 0」。
这组测试盯住落点选择、并库与去重三件事。
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from spiritscout.config.settings import SystemConfig, WorkspaceConfig
from spiritscout.gateway.usage import (
    UsageLedger,
    absorb_session_ledgers,
    shared_ledger_path,
)


def _cfg(root: Path, *, guard_root: str = "") -> SystemConfig:
    return SystemConfig(
        workspace=WorkspaceConfig(root=str(root), guard_root=guard_root),
        models_config_path=str(root / "models.yaml"),
        agent_models_path=str(root / "agents.yaml"),
        audit_log_path=str(root / "audit.jsonl"),
    )


class SharedLedgerPathTests(unittest.TestCase):
    def test_uses_guard_root_when_session_cfg_redirects_workspace(self) -> None:
        """会话配置把 workspace.root 指到 sessions/<id>，账本仍要落在基础工作区。"""
        cfg = _cfg(Path("C:/base/.spiritscout/sessions/s1"),
                   guard_root="C:/base/.spiritscout")
        self.assertEqual(shared_ledger_path(cfg).parent,
                         Path("C:/base/.spiritscout"))

    def test_falls_back_to_workspace_root_without_guard_root(self) -> None:
        """单机 CLI 没有控制面重定向，就用 workspace.root。"""
        cfg = _cfg(Path("C:/work"))
        self.assertEqual(shared_ledger_path(cfg), Path("C:/work/usage.json"))


class AbsorbSessionLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.shared = self.root / "shared" / "usage.json"
        self.sessions = self.root / "sessions"
        self.sessions.mkdir(parents=True)

    def _ledger(self, session_id: str, calls: list[tuple[str, int]]) -> Path:
        path = self.sessions / session_id / "usage.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        ledger = UsageLedger(path)
        for call_id, tokens in calls:
            ledger.append({"ts": 1.0, "tokens": tokens, "model": "m",
                           "call_id": call_id, "task_type": "ctf"})
        return path

    def _count(self) -> int:
        if not self.shared.exists():
            return 0
        conn = sqlite3.connect(str(self.shared))
        try:
            return int(conn.execute("SELECT COUNT(*) FROM calls").fetchone()[0])
        finally:
            conn.close()

    def test_merges_session_ledgers_into_shared(self) -> None:
        """两个会话各记两笔，并库后共享库有四笔。"""
        self._ledger("s1", [("c1", 100), ("c2", 200)])
        self._ledger("s2", [("c3", 300), ("c4", 400)])
        self.assertEqual(absorb_session_ledgers(self.shared, self.sessions), 4)
        self.assertEqual(self._count(), 4)

    def test_absorb_is_idempotent(self) -> None:
        """重复并库不重复计——启动时每次 start 都会扫一遍。"""
        self._ledger("s1", [("c1", 100)])
        absorb_session_ledgers(self.shared, self.sessions)
        self.assertEqual(absorb_session_ledgers(self.shared, self.sessions), 0)
        self.assertEqual(self._count(), 1)

    def test_missing_sessions_dir_is_harmless(self) -> None:
        """没有 sessions 目录（全新工作区）不该报错。"""
        self.assertEqual(
            absorb_session_ledgers(self.shared, self.root / "nope"), 0)
        self.assertEqual(self._count(), 0)


class AppendResultTests(unittest.TestCase):
    def test_append_reports_new_then_duplicate(self) -> None:
        """append 的返回值供并库计数：同 call_id 第二次是 False。"""
        with tempfile.TemporaryDirectory() as tmp:
            ledger = UsageLedger(Path(tmp) / "usage.db")
            entry = {"ts": 1.0, "tokens": 10, "model": "m", "call_id": "c1"}
            self.assertTrue(ledger.append(entry))
            self.assertFalse(ledger.append(entry))


if __name__ == "__main__":
    unittest.main()
