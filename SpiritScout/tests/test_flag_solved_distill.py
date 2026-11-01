"""解出 Flag 即提炼：回调触点、单题材料、去重与审计口径。"""
from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from spiritscout.blackboard import Blackboard
from spiritscout.core.audit import AuditLogger, NullAuditLogger
from spiritscout.core.models import (
    Authorization,
    BlackboardLayer,
    FlagCandidate,
    RunMode,
    Scope,
)
from spiritscout.ctf.flags import FlagManager, SubmitResult
from spiritscout.runtime import (
    _flag_digest,
    _schedule_flag_distill,
)


def _authorization() -> Authorization:
    return Authorization(auth_id="auth-flag-distill", mode=RunMode.CTF,
                         scope=Scope(), target_description="ctf://demo")


def _candidate(value: str = "flag{test_value}", challenge_id: str = "c1") -> FlagCandidate:
    return FlagCandidate(flag_id="fid-1", challenge_id=challenge_id, value=value,
                         format_ok=True, found_by="ctf-web")


class SolvedHookTests(unittest.IsolatedAsyncioTestCase):
    """FlagManager 只在「真解出」时回调，且每枚 Flag 只回调一次。"""

    async def test_accepted_submit_notifies_once(self) -> None:
        fired: list[str] = []

        async def hook(cand: FlagCandidate) -> None:
            fired.append(cand.value)

        async def accept(value: str, challenge_id: str) -> SubmitResult:
            return SubmitResult(True, "正确")

        manager = FlagManager(submit_fn=accept, audit=NullAuditLogger(),
                              rate_limit_per_minute=600, on_solved=hook)
        cand = manager.register("flag{ok}", challenge_id="c1", found_by="web")
        assert cand is not None
        await manager.submit(cand)
        await asyncio.sleep(0)
        self.assertEqual(fired, ["flag{ok}"])
        await manager.submit(cand)          # 幂等重提不再回调
        await asyncio.sleep(0)
        self.assertEqual(fired, ["flag{ok}"])

    async def test_rejected_and_undecided_do_not_notify(self) -> None:
        fired: list[str] = []

        async def hook(cand: FlagCandidate) -> None:
            fired.append(cand.value)

        async def reject(value: str, challenge_id: str) -> SubmitResult:
            return SubmitResult(False, "错误")

        async def undecided(value: str, challenge_id: str) -> SubmitResult:
            return SubmitResult(None, "频率限制")

        for submit_fn in (reject, undecided):
            manager = FlagManager(submit_fn=submit_fn, audit=NullAuditLogger(),
                                  rate_limit_per_minute=600, on_solved=hook)
            cand = manager.register("flag{maybe}", challenge_id="c1", found_by="web")
            assert cand is not None
            await manager.submit(cand)
            await asyncio.sleep(0)
        self.assertEqual(fired, [])

    async def test_manual_mode_notifies_on_register_only(self) -> None:
        fired: list[str] = []

        async def hook(cand: FlagCandidate) -> None:
            fired.append(cand.value)

        manager = FlagManager(audit=NullAuditLogger(), on_solved=hook,  # 无提交接口
                              rate_limit_per_minute=600)
        # 正则扫描出来的候选不算解出
        manager.extract("输出里有 flag{from_regex} 一段", challenge_id="c1",
                        found_by="web")
        await asyncio.sleep(0)
        self.assertEqual(fired, [])
        cand = manager.register("flag{model_says}", challenge_id="c1", found_by="web")
        assert cand is not None
        await asyncio.sleep(0)
        self.assertEqual(fired, ["flag{model_says}"])

    async def test_hook_failure_does_not_break_submit(self) -> None:
        async def boom(cand: FlagCandidate) -> None:
            raise RuntimeError("提炼炸了")

        async def accept(value: str, challenge_id: str) -> SubmitResult:
            return SubmitResult(True, "正确")

        manager = FlagManager(submit_fn=accept, audit=NullAuditLogger(),
                              rate_limit_per_minute=600, on_solved=boom)
        cand = manager.register("flag{ok}", challenge_id="c1", found_by="web")
        assert cand is not None
        judged = await manager.submit(cand)
        await asyncio.sleep(0)
        self.assertTrue(judged.accepted)     # 提交结果照旧


class FlagDistillTests(unittest.IsolatedAsyncioTestCase):
    """解出后的单题提炼：材料、去重、快照与审计口径。"""

    def _infra(self, tmp: Path, audit):  # noqa: ANN001
        return SimpleNamespace(
            audit=audit,
            gateway=None,
            blackboard=Blackboard(tmp / "bb.db"),
            agent_models={"master": ""},
            authorization=_authorization(),
            workspace=tmp,
            flag_distilled=set(),
            flag_distill_closed=False,
            cfg=SimpleNamespace(
                experience=SimpleNamespace(distill_timeout_seconds=45)),
        )

    async def test_flag_distill_runs_in_background_with_flag_trigger(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            audit = AuditLogger(tmp / "audit.jsonl")
            store = SimpleNamespace(closed=False)

            def close() -> None:
                store.closed = True

            store.close = close          # type: ignore[attr-defined]
            infra = self._infra(tmp, audit)

            async def fake_distill(gateway, experience, digest, *, timeout_seconds,
                                   audit=None, source_session=""):
                return {"result": "ok", "insights": 2}

            try:
                with patch("spiritscout.runtime._distill_experience",
                           new=fake_distill):
                    task = _schedule_flag_distill(
                        infra, store, True, _candidate(),
                        {"id": "c1", "title": "登录绕过", "direction": "web"})
                    self.assertIsNotNone(task)
                    assert task is not None
                    await task
            finally:
                infra.blackboard.close()

            self.assertFalse(store.closed)   # 会话还在跑，经验库不能关
            # 跑完后快照已是 done，pending_distill_snapshots 不再收录，直接读队列目录
            snapshots = sorted((tmp / "experience_distill").glob("*.json"))
            self.assertEqual(len(snapshots), 1)
            payload = json.loads(snapshots[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["trigger"], "flag")
            self.assertEqual(payload["challenge"], "c1")
            self.assertEqual(payload["status"], "done")
            self.assertNotIn("flag{test_value}",
                             json.dumps(payload, ensure_ascii=False))

            events = [json.loads(line) for line
                      in (tmp / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
            distill = [rec["detail"] for rec in events
                       if rec.get("type") == "experience.distill"]
            self.assertEqual(len(distill), 1)
            self.assertEqual(distill[0]["trigger"], "flag")
            self.assertEqual(distill[0]["outcome"], "flag_solved")
            self.assertEqual(distill[0]["result"], "ok")

    async def test_same_challenge_distills_once(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            infra = self._infra(tmp, NullAuditLogger())
            store = SimpleNamespace(close=lambda: None)

            async def fake_distill(*args, **kwargs):
                return {"result": "ok", "insights": 1}

            try:
                with patch("spiritscout.runtime._distill_experience",
                           new=fake_distill):
                    first = _schedule_flag_distill(
                        infra, store, True, _candidate("flag{a}"), {"id": "c1"})
                    second = _schedule_flag_distill(
                        infra, store, True, _candidate("flag{b}"), {"id": "c1"})
                    self.assertIsNotNone(first)
                    self.assertIsNone(second)
                    assert first is not None
                    await first
            finally:
                infra.blackboard.close()

    async def test_closed_or_disabled_never_schedules(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            infra = self._infra(tmp, NullAuditLogger())
            store = SimpleNamespace(close=lambda: None)
            try:
                self.assertIsNone(_schedule_flag_distill(
                    infra, store, False, _candidate(), {"id": "c1"}))
                infra.flag_distill_closed = True
                self.assertIsNone(_schedule_flag_distill(
                    infra, store, True, _candidate(), {"id": "c1"}))
                self.assertIsNone(_schedule_flag_distill(
                    infra, None, True, _candidate(), {"id": "c1"}))
            finally:
                infra.blackboard.close()

    def test_digest_carries_challenge_and_masks_flag(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            infra = self._infra(tmp, NullAuditLogger())
            infra.blackboard.write(BlackboardLayer.TASK_STATE, "t1", {
                "task": {"task_id": "t1", "agent_type": "ctf-web",
                         "payload": {"node_id": "c1", "node_title": "登录绕过"}},
                "routes": [{"name": "主路线", "status": "done",
                            "notes": ["用户名处永真式绕过登录"]}],
            }, updated_by="ctf-web")
            try:
                digest = _flag_digest(infra, _candidate(), {"id": "c1",
                                                           "title": "登录绕过"})
            finally:
                infra.blackboard.close()
        self.assertEqual(digest["event"], "flag_solved")
        self.assertEqual(digest["challenge"]["id"], "c1")
        self.assertEqual(digest["flag"]["preview"], "flag{t…")
        self.assertEqual(digest["routes"][0]["note"], "用户名处永真式绕过登录")
        self.assertNotIn("flag{test_value}", json.dumps(digest, ensure_ascii=False))


class ResumeAuditTests(unittest.IsolatedAsyncioTestCase):
    async def test_resumed_snapshot_records_trigger(self) -> None:
        from spiritscout.config.settings import (
            ExperienceConfig,
            ModelEntry,
            SystemConfig,
            WorkspaceConfig,
        )
        from spiritscout.runtime import resume_pending_distills

        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            workspace = tmp / "sess-demo"
            queue = workspace / "experience_distill"
            queue.mkdir(parents=True)
            (queue / "20260101T000000000Z-distill-1.json").write_text(json.dumps({
                "schema": 1, "status": "pending", "attempts": 0,
                "outcome": "flag_solved", "trigger": "flag", "challenge": "c1",
                "digest": {"event": "flag_solved"},
                "session": "sess-demo"}), encoding="utf-8")
            audit_path = tmp / "audit.jsonl"
            cfg = SystemConfig(
                workspace=WorkspaceConfig(root=str(tmp)),
                experience=ExperienceConfig(root=str(tmp / "exp")),
                audit_log_path=str(audit_path))
            models = [ModelEntry(model="mock:model", provider="mock",
                                 api_key="fixture-key")]

            async def fake_distill(gateway, store, digest, *, timeout_seconds,
                                   audit=None, source_session=""):
                return {"result": "ok", "insights": 3}

            with patch("spiritscout.runtime._distill_experience",
                       new=fake_distill):
                completed = await resume_pending_distills(
                    workspace=workspace, cfg=cfg, models=models)
            self.assertEqual(completed, 1)
            events = [json.loads(line) for line
                      in audit_path.read_text(encoding="utf-8").splitlines()]
            distill = [rec["detail"] for rec in events
                       if rec.get("type") == "experience.distill"]
            self.assertEqual(distill[0]["trigger"], "flag")
            self.assertEqual(distill[0]["recovered"], True)
            snapshot = json.loads(
                (queue / "20260101T000000000Z-distill-1.json").read_text(
                    encoding="utf-8"))
            self.assertEqual(snapshot["status"], "done")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
