"""会话经验与共享经验库必须是同一本账。

回归：手动提炼曾把条目写进 ``sessions/<id>/experience.db``，而「经验库」页读的是
``<workspace>/experience.db``——两条产出在会话页看得见、在经验库里查不到。
"""
from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from spiritscout.config.settings import SystemConfig, WorkspaceConfig
from spiritscout.knowledge.experience import ExperienceStore, experience_db_path
from spiritscout.web import session_experience as sx
from tests.test_session_experience import _flag, _keyed, _session


class SharedLibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        sx._LOCKS.clear()
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        # experience.root 留空：与 configs/system.yaml 的默认一致
        self.cfg = SystemConfig(workspace=WorkspaceConfig(root=str(self.root)),
                                models_config_path=str(self.root / "models.yaml"))
        self.session = _session(self.root, flags=[_flag("flag{a}", accepted=True)])

    @property
    def library(self) -> Path:
        """「经验库」页与开局召回读的那本库。"""
        return experience_db_path(self.cfg.experience.root, self.cfg.workspace.root)

    def test_session_page_reads_the_shared_library(self) -> None:
        """会话页要读共享库：写进共享库的条目，本会话页签就得看见。"""
        store = ExperienceStore(self.library)
        try:
            store.add("共享库里的一条经验", context="登录接口", tags=["web"],
                      source_session=self.session.session_id, source_model="master")
        finally:
            store.close()
        page = sx.session_page(self.cfg, self.session)
        self.assertEqual([item["insight"] for item in page["items"]],
                         ["共享库里的一条经验"])

    def test_manual_distill_lands_in_the_shared_library(self) -> None:
        """手动提炼写共享库，不在会话目录里另起一本。"""
        async def fake(gateway, store, digest, *, timeout_seconds, audit=None,
                       source_session=""):
            store.add("缺少错误文案的登录接口也可能存在用户名枚举",
                      context="登录接口", tags=["web", "枚举"],
                      source_session=source_session, source_model="master")
            return {"result": "ok", "insights": 1}

        with patch("spiritscout.web.sessions._conversation_gateway", return_value=object()), \
                patch("spiritscout.runtime._distill_experience", fake):
            result = asyncio.run(
                sx.distill_now(self.cfg, self.session, models=[_keyed()]))
        self.assertEqual(result["result"], "ok")
        # 共享库能读到
        shared = sx.read_session_insights(self.library, self.session.session_id)
        self.assertEqual(len(shared), 1, "经验库必须收到这条手动提炼")
        check = ExperienceStore(self.library)
        try:
            self.assertEqual(check.count(), 1)
        finally:
            check.close()
        # 会话目录里不该再多出一本来
        stray = Path(self.session.workspace) / "experience.db"
        self.assertFalse(stray.exists(), f"会话目录不该再有独立经验库：{stray}")

    def test_legacy_session_db_is_absorbed_into_the_library(self) -> None:
        """旧版本留在会话目录里的经验，启动时并进共享库（幂等）。"""
        from spiritscout.knowledge.experience import absorb_session_dbs

        legacy = Path(self.cfg.workspace.root) / "sessions" / self.session.session_id
        legacy.mkdir(parents=True, exist_ok=True)
        store = ExperienceStore(legacy / "experience.db")
        try:
            store.add("旧账：本机端点可以先用占位密钥打通",
                      context="模型网关", tags=["gateway"],
                      source_session=self.session.session_id, source_model="master")
        finally:
            store.close()

        sessions_dir = Path(self.cfg.workspace.root) / "sessions"
        first = absorb_session_dbs(self.library, sessions_dir)
        self.assertEqual(first, 1)
        second = absorb_session_dbs(self.library, sessions_dir)
        self.assertEqual(second, 0, "第二次不该重复并库")

        items = sx.read_session_insights(self.library, self.session.session_id)
        self.assertEqual([item["insight"] for item in items],
                         ["旧账：本机端点可以先用占位密钥打通"])
        self.assertEqual(items[0]["tags"], ["gateway"])


class AutoDistillLibraryTests(unittest.TestCase):
    """自动提炼（含重启后补跑）也必须写共享库——这是「提炼成功但库页没有」的主因。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.cfg = SystemConfig(workspace=WorkspaceConfig(root=str(self.root)),
                                models_config_path=str(self.root / "models.yaml"))
        self.workspace = self.root / "sessions" / "sess-auto"
        self.workspace.mkdir(parents=True)

    def _queue_snapshot(self) -> None:
        from spiritscout.runtime import _write_distill_snapshot

        path = self.workspace / "experience_distill" / "20261102T000000000Z-distill-x.json"
        _write_distill_snapshot(path, {
            "schema": 1, "status": "pending", "attempts": 0,
            "outcome": "completed", "trigger": "end", "challenge": "",
            "digest": {"target": "lab", "outcome": "completed"},
            "session": self.workspace.name, "created_at": "2026-11-02T00:00:00+00:00",
        })

    def test_resume_writes_to_shared_library(self) -> None:
        from spiritscout.runtime import resume_pending_distills

        self._queue_snapshot()
        seen: dict[str, str] = {}

        async def fake(gateway, store, digest, *, timeout_seconds, audit=None,
                       source_session=""):
            seen["db"] = str(store.db_path)
            seen["session"] = source_session
            store.add("自动提炼也要落进共享库", tags=["经验"],
                      source_session=source_session, source_model="master")
            return {"result": "ok", "insights": 1, "duplicates": 0}

        with patch("spiritscout.runtime._distill_experience", fake):
            done = asyncio.run(resume_pending_distills(
                workspace=self.workspace, cfg=self.cfg,
                models=[_keyed()]))
        self.assertEqual(done, 1)
        expected = sx.experience_library(self.cfg)
        self.assertEqual(seen["db"], str(expected), "补跑提炼要写共享库")
        self.assertEqual(seen["session"], "sess-auto")
        self.assertFalse((self.workspace / "experience.db").exists(),
                         "会话目录里不该另起一本经验库")
        store = ExperienceStore(expected)
        try:
            self.assertEqual(store.count(), 1)
        finally:
            store.close()


if __name__ == "__main__":   # pragma: no cover
    unittest.main()
