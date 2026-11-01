"""「提炼中 / 询问中」这两个派生状态。

它们都不是持久化 status——提炼是收尾后的附加动作，询问是运行中挂起等答——
所以由进程内登记表 + 待答队列现算，前端才能和 运行中/已完成/已中断 并列显示。
"""
from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from spiritscout.config.settings import SystemConfig, WorkspaceConfig
from spiritscout.core import distill_state
from spiritscout.web import session_experience as sx
from spiritscout.web.status import ASKING, DISTILLING, derived, display_status


class DistillStateTests(unittest.TestCase):
    def setUp(self) -> None:
        distill_state._ACTIVE.clear()          # noqa: SLF001 —— 测试间互不影响
        self.addCleanup(distill_state._ACTIVE.clear)

    def test_active_only_while_inside(self) -> None:
        self.assertFalse(distill_state.active("sess-a"))
        with distill_state.tracked("sess-a"):
            self.assertTrue(distill_state.active("sess-a"))
            self.assertFalse(distill_state.active("sess-A"), "会话 ID 区分大小写")
        self.assertFalse(distill_state.active("sess-a"), "退出后要摘掉")

    def test_nested_counts_references(self) -> None:
        with distill_state.tracked("sess-b"):
            with distill_state.tracked("sess-b"):
                self.assertTrue(distill_state.active("sess-b"))
            self.assertTrue(distill_state.active("sess-b"), "外层还在提炼")
        self.assertFalse(distill_state.active("sess-b"), "嵌套退出不能提前清空")

    def test_exception_still_releases(self) -> None:
        with self.assertRaises(RuntimeError):
            with distill_state.tracked("sess-c"):
                raise RuntimeError("模型炸了")
        self.assertFalse(distill_state.active("sess-c"))

    def test_concurrent_sessions_are_independent(self) -> None:
        with distill_state.tracked("sess-1"), distill_state.tracked("sess-2"):
            self.assertEqual(distill_state.active_ids(), {"sess-1", "sess-2"})
        self.assertEqual(distill_state.active_ids(), set())


class _Stub:
    """display_status 只碰这几样：session_id / status / questions.view()。"""

    def __init__(self, sid: str = "sess-x", status: str = "running",
                 questions: int = 0) -> None:
        self.session_id = sid
        self.status = status
        self._questions = questions

    @property
    def questions(self) -> Any:
        return SimpleNamespace(view=lambda: [{"question_id": f"q{i}"}
                                             for i in range(self._questions)])


class DisplayStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        distill_state._ACTIVE.clear()          # noqa: SLF001
        self.addCleanup(distill_state._ACTIVE.clear)

    def test_distilling_beats_terminal_status(self) -> None:
        """自动提炼发生在会话收尾之后：这时候徽标必须是「提炼中」。"""
        session = _Stub(status="completed")
        with distill_state.tracked("sess-x"):
            self.assertEqual(display_status(session), DISTILLING)

    def test_asking_when_a_question_waits(self) -> None:
        self.assertEqual(display_status(_Stub(questions=2)), ASKING)
        self.assertEqual(derived(_Stub(questions=2))["pending_questions"], 2)

    def test_distilling_outranks_asking(self) -> None:
        session = _Stub(status="running", questions=1)
        with distill_state.tracked("sess-x"):
            self.assertEqual(display_status(session), DISTILLING)

    def test_plain_status_when_neither(self) -> None:
        self.assertEqual(display_status(_Stub(status="interrupted")), "interrupted")
        self.assertEqual(display_status(_Stub(status="running")), "running")

    def test_terminal_with_question_still_shows_status(self) -> None:
        """已经结束的会话不该因为残留待答而一直显示询问中。"""
        self.assertEqual(display_status(_Stub(status="completed", questions=1)), "completed")

    def test_derived_fields_are_flags_for_the_frontend(self) -> None:
        fields = derived(_Stub(status="running"))
        self.assertEqual(fields, {"distilling": False, "pending_questions": 0})


class _FakeStore:
    def __init__(self) -> None:
        self.added: list[str] = []

    def add(self, insight: str, **_kwargs: Any) -> str:
        self.added.append(insight)
        return "id-1"


class DistillHookTests(unittest.TestCase):
    """提炼入口要登记，前端才可能看见「提炼中」。"""

    def setUp(self) -> None:
        distill_state._ACTIVE.clear()          # noqa: SLF001
        self.addCleanup(distill_state._ACTIVE.clear)

    def test_runtime_distill_registers_source_session(self) -> None:
        from spiritscout.runtime import _distill_experience

        seen: list[bool] = []

        async def fake_chat(_gateway, _messages, **_kwargs):
            seen.append(distill_state.active("sess-auto"))
            return SimpleNamespace(content='{"insights": [{"insight": "一条洞察", '
                                            '"context": "", "tags": []}]}')

        store = _FakeStore()
        with patch("spiritscout.gateway.gateway.chat_decision", fake_chat):
            result = asyncio.run(_distill_experience(
                object(), store, {"session": "x"}, timeout_seconds=1,
                source_session="sess-auto"))
        self.assertEqual(result["result"], "ok")
        self.assertEqual(seen, [True], "提炼过程中必须登记为提炼中")
        self.assertFalse(distill_state.active("sess-auto"), "结束后要摘掉")

    def test_manual_distill_registers_too(self) -> None:
        """手动提炼与自动提炼共用一个登记：两条路都要亮「提炼中」。"""
        sx._LOCKS.clear()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
            root = Path(raw)
            cfg = SystemConfig(workspace=WorkspaceConfig(root=str(root)),
                              models_config_path=str(root / "models.yaml"))
            from tests.test_session_experience import _flag, _keyed, _session

            session = _session(root, flags=[_flag("flag{a}", accepted=True)])
            seen: list[bool] = []

            async def fake_chat(_gateway, _messages, **_kwargs):
                seen.append(distill_state.active(session.session_id))
                return SimpleNamespace(content='{"insights": []}')

            with patch("spiritscout.web.sessions._conversation_gateway",
                       return_value=object()), \
                    patch("spiritscout.gateway.gateway.chat_decision", fake_chat):
                asyncio.run(sx.distill_now(cfg, session, models=[_keyed()]))
            self.assertEqual(seen, [True], "手动提炼期间同样要亮「提炼中」")
            self.assertFalse(distill_state.active(session.session_id))


if __name__ == "__main__":   # pragma: no cover
    unittest.main()
