"""会话页的经验提炼：本次产出、提炼记录与手动补提炼。

口径要钉住三件事：

* 只认本会话产出的经验（``source_session`` 相等），别人的不能串进来；
* 战报从落盘状态重建，已停止的会话也能提炼（不依赖运行中的 runtime）；
* 手动提炼照实记账——失败要能看见原因，不能伪装成「提炼成功但没内容」。
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from spiritscout.blackboard import Blackboard
from spiritscout.config.settings import SystemConfig, WorkspaceConfig
from spiritscout.core.models import BlackboardLayer
from spiritscout.knowledge.experience import ExperienceStore
from spiritscout.web import session_experience as sx
from spiritscout.web.routes.session_detail import mount_session_detail

VULN = BlackboardLayer.VULN
TASKS = BlackboardLayer.TASK_STATE


def _write_bb(path: Path, *, vulns: list[dict[str, Any]] | None = None,
              tasks: list[dict[str, Any]] | None = None) -> None:
    board = Blackboard(path)
    try:
        for index, data in enumerate(vulns or []):
            board.write(VULN, f"vuln-{index}", data, updated_by="web-agent")
        for index, data in enumerate(tasks or []):
            board.write(TASKS, f"task-{index}", data, updated_by="web-agent")
    finally:
        board.close()


def _session(root: Path, *, session_id: str = "sess-exp", status: str = "completed",
             flags: list[dict[str, Any]] | None = None,
             vulns: list[dict[str, Any]] | None = None,
             tasks: list[dict[str, Any]] | None = None,
             mission: str = "打一台 Web", dialogue: list[dict[str, str]] | None = None,
             error: str = "", summary: dict[str, Any] | None = None) -> SimpleNamespace:
    workspace = root / session_id
    workspace.mkdir(parents=True, exist_ok=True)
    if flags is not None:
        (workspace / "flags.json").write_text(json.dumps(flags, ensure_ascii=False),
                                              encoding="utf-8")
    if vulns is not None or tasks is not None:
        _write_bb(workspace / "bb.db", vulns=vulns, tasks=tasks)
    return SimpleNamespace(
        session_id=session_id, mode="ctf", target="http://target.test", workspace=workspace,
        status=status, error=error, summary=summary or {},
        request={"mission": mission} if mission else {},
        dialogue_history=dialogue or [],
        meta_path=workspace / "meta.json", bb_path=workspace / "bb.db",
        flags_path=workspace / "flags.json", audit_path=workspace / "audit.jsonl")


def _flag(value: str, *, accepted: bool | None, submitted: bool = True) -> dict[str, Any]:
    return {"flag_id": "", "challenge_id": "web-1", "value": value, "format_ok": True,
            "submitted": submitted, "accepted": accepted, "submit_response": "",
            "found_by": "agent-1"}


def _keyed(provider_ref: str = "glm", model: str = "cn:glm-5.3-flash") -> SimpleNamespace:
    """配了 Key 的模型条目：提炼只认这种，没 Key 的会被剔掉。"""
    return SimpleNamespace(api_key="sk-local-test", provider_ref=provider_ref, model=model)


def _audit_event(audit_path: Path, detail: dict[str, Any], *,
                 ts: str = "2026-11-01T20:00:00") -> None:
    record = {"ts": ts, "seq": 1, "type": "experience.distill", "actor": "master",
              "detail": detail}
    with audit_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


class Case(unittest.TestCase):
    def setUp(self) -> None:
        sx._LOCKS.clear()
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.cfg = SystemConfig(workspace=WorkspaceConfig(root=str(self.root)),
                                models_config_path=str(self.root / "models.yaml"))

    def db_path(self, session: Any) -> Path:
        """共享经验库：会话页与经验库页读的是同一本。"""
        return sx.experience_library(self.cfg)


class ReadInsightTests(Case):
    def test_only_this_session_newest_first(self) -> None:
        session = _session(self.root)
        store = ExperienceStore(self.db_path(session))
        try:
            store.add("第一条经验", context="会员接口", tags=["web"],
                      source_session=session.session_id, source_model="master")
            store.add("别人的经验", source_session="sess-other", source_model="master")
            store.add("第二条经验", tags=["越权"], source_session=session.session_id)
        finally:
            store.close()
        items = sx.read_session_insights(self.db_path(session), session.session_id)
        self.assertEqual([item["insight"] for item in items],
                         ["第二条经验", "第一条经验"], "只给本会话，最新在前")
        self.assertEqual(items[1]["tags"], ["web"])
        self.assertEqual(items[1]["context"], "会员接口")

    def test_missing_or_broken_db_is_empty(self) -> None:
        session = _session(self.root)
        self.assertEqual(sx.read_session_insights(self.db_path(session), "sess-exp"), [])
        broken = self.root / "broken.db"
        broken.write_bytes(b"not a database at all")
        self.assertEqual(sx.read_session_insights(broken, "sess-exp"), [])
        self.assertEqual(sx.read_session_insights(self.db_path(session), ""), [])


class DigestTests(Case):
    def test_digest_carries_flags_findings_and_failed_routes(self) -> None:
        session = _session(
            self.root,
            flags=[_flag("flag{a}", accepted=True), _flag("flag{b}", accepted=False)],
            vulns=[{"status": "accepted", "title": "会员接口越权", "severity": "high",
                    "vuln_type": "idor"},
                   {"status": "candidate", "title": "待验证"}],
            tasks=[{"task": {"agent_type": "web"},
                    "routes": [{"name": "登录爆破", "status": "failed",
                                "notes": ["被限速拦下"]}]}])
        digest = sx.session_digest(session)
        self.assertEqual(digest["outcome"], "completed")
        self.assertEqual(digest["flags"],
                         {"extracted": 2, "submitted": 2, "accepted": 1, "rejected": 1})
        self.assertEqual(digest["findings"]["total"], 2)
        self.assertEqual(digest["findings"]["accepted"][0]["title"], "会员接口越权")
        self.assertEqual(digest["trials"][0]["route"], "登录爆破")
        self.assertEqual(digest["tasks_recorded"], 1)
        self.assertEqual(digest["mission"], "打一台 Web")

    def test_mission_falls_back_to_first_user_message(self) -> None:
        session = _session(self.root, mission="",
                           dialogue=[{"role": "system", "content": "忽略"},
                                     {"role": "user", "content": "先看登录"}])
        self.assertEqual(sx.session_digest(session)["mission"], "先看登录")

    def test_interrupted_session_keeps_outcome(self) -> None:
        session = _session(self.root, status="interrupted", error="模型超时")
        digest = sx.session_digest(session)
        self.assertEqual(digest["outcome"], "interrupted")
        self.assertEqual(digest["error"], "模型超时")


class BlockerTests(Case):
    def test_running_session_waits(self) -> None:
        session = _session(self.root, status="running")
        self.assertIn("还在执行", sx.distill_blocker(session))

    def test_empty_session_is_refused(self) -> None:
        session = _session(self.root, mission="")
        self.assertEqual(sx.distill_blocker(session), "这次会话没有可提炼的活动")

    def test_session_with_output_can_distill(self) -> None:
        session = _session(self.root, flags=[_flag("flag{a}", accepted=True)])
        self.assertEqual(sx.distill_blocker(session), "")


class DistillTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        sx._LOCKS.clear()
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.cfg = SystemConfig(workspace=WorkspaceConfig(root=str(self.root)),
                                models_config_path=str(self.root / "models.yaml"))
        self.session = _session(self.root, flags=[_flag("flag{a}", accepted=True)])

    async def test_manual_distill_writes_insights_and_audits_trigger(self) -> None:
        async def fake(gateway, store, digest, *, timeout_seconds, audit=None,
                       source_session=""):
            store.add("同类登录接口在缺少错误文案时也可能存在用户名枚举",
                      context="登录接口", tags=["web", "枚举"],
                      source_session=source_session, source_model="master")
            return {"result": "ok", "insights": 1}

        with patch("spiritscout.web.sessions._conversation_gateway", return_value=object()), \
                patch("spiritscout.runtime._distill_experience", fake):
            result = await sx.distill_now(self.cfg, self.session, models=[_keyed()])
        self.assertEqual(result["result"], "ok")
        self.assertEqual(result["trigger"], "manual")
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["source_session"], self.session.session_id)
        self.assertEqual(result["history"][0]["trigger"], "manual")
        lines = [json.loads(line) for line in
                 self.session.audit_path.read_text(encoding="utf-8").splitlines()]
        manual = [rec for rec in lines if rec["type"] == "experience.distill"]
        self.assertEqual(manual[0]["detail"]["trigger"], "manual")
        self.assertEqual(manual[0]["detail"]["insights"], 1)

    async def test_model_failure_is_reported_not_raised(self) -> None:
        async def boom(*_args, **_kwargs):
            raise TimeoutError("模型 45 秒没回")

        with patch("spiritscout.web.sessions._conversation_gateway", return_value=object()), \
                patch("spiritscout.runtime._distill_experience", boom):
            result = await sx.distill_now(self.cfg, self.session, models=[_keyed()])
        self.assertEqual(result["result"], "error")
        self.assertIn("TimeoutError", result["error"])
        self.assertEqual(result["items"], [])
        self.assertEqual(result["history"][0]["result"], "error")

    async def test_second_call_while_running_is_busy(self) -> None:
        gate = asyncio.Event()

        async def slow(gateway, store, digest, *, timeout_seconds, audit=None,
                       source_session=""):
            await gate.wait()
            return {"result": "empty", "insights": 0}

        with patch("spiritscout.web.sessions._conversation_gateway", return_value=object()), \
                patch("spiritscout.runtime._distill_experience", slow):
            first = asyncio.create_task(
                sx.distill_now(self.cfg, self.session, models=[_keyed()]))
            await asyncio.sleep(0.05)
            second = await sx.distill_now(self.cfg, self.session, models=[_keyed()])
            gate.set()
            done = await first
        self.assertEqual(second["result"], "busy")
        self.assertEqual(done["result"], "empty")

    async def test_channels_without_keys_never_reach_the_gateway(self) -> None:
        """没 Key 的渠道进链只会白跑一次：提炼要先把它们剔掉，只拿能调通的。"""
        seen: list[list[Any]] = []

        async def fake(gateway, store, digest, *, timeout_seconds, audit=None,
                       source_session=""):
            return {"result": "ok", "insights": 0}

        keyed = SimpleNamespace(api_key="sk-xxxx", provider_ref="glm",
                                model="cn:glm-5.3-flash")
        keyless = SimpleNamespace(api_key="", provider_ref="zerohh",
                                  model="cn:deepseek-v4.1-flash")
        with patch("spiritscout.web.sessions._conversation_gateway",
                   side_effect=lambda cfg, models, audit: seen.append(models) or object()), \
                patch("spiritscout.runtime._distill_experience", fake):
            result = await sx.distill_now(self.cfg, self.session, models=[keyless, keyed])
        self.assertEqual(result["result"], "ok")
        self.assertEqual([entry.provider_ref for entry in seen[0]], ["glm"],
                         "只有配了 Key 的渠道该送到网关")

    async def test_all_channels_without_keys_refuses_before_calling(self) -> None:
        keyless = SimpleNamespace(api_key="", provider_ref="zerohh",
                                  model="cn:deepseek-v4.1-flash")
        with patch("spiritscout.web.sessions._conversation_gateway") as gateway:
            result = await sx.distill_now(self.cfg, self.session, models=[keyless])
        self.assertEqual(result["result"], "error")
        self.assertIn("zerohh", result["error"])
        self.assertIn("API Key", result["error"])
        gateway.assert_not_called()

    async def test_without_models_there_is_nothing_to_call(self) -> None:
        result = await sx.distill_now(self.cfg, self.session, models=[])
        self.assertEqual(result["result"], "error")
        self.assertIn("没有可用模型", result["error"])
        self.assertEqual(result["items"], [], "失败也要给页面能直接用的结构")

    async def test_skipped_channels_are_named_when_the_call_still_fails(self) -> None:
        """跳过了哪些没 key 的渠道要说清楚——不然用户不知道报错背后少了谁。"""

        async def boom(*_args, **_kwargs):
            raise RuntimeError("Missing credentials")

        keyed = SimpleNamespace(api_key="sk-xxxx", provider_ref="glm", model="cn:glm-5.3-flash")
        keyless = SimpleNamespace(api_key="", provider_ref="zerohh",
                                  model="cn:deepseek-v4.1-flash")
        with patch("spiritscout.web.sessions._conversation_gateway", return_value=object()), \
                patch("spiritscout.runtime._distill_experience", boom):
            result = await sx.distill_now(self.cfg, self.session, models=[keyless, keyed])
        self.assertEqual(result["result"], "error")
        self.assertIn("zerohh", result["error"], "被跳过的渠道要出现在报错里")
        self.assertIn("跳过", result["error"])
        self.assertIn("zerohh", result["history"][0]["error"], "提炼记录里也要留痕")

    async def test_missing_runtime_dependency_is_explained_not_raised(self) -> None:
        """解释器跑错（缺 langgraph）时，用户看到的要是一句能照做的话，不是 500。"""
        import builtins

        real_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "spiritscout.runtime":
                raise ModuleNotFoundError("No module named 'langgraph'", name="langgraph")
            return real_import(name, globals, locals, fromlist, level)

        with patch("builtins.__import__", fake_import):
            result = await sx.distill_now(self.cfg, self.session, models=[_keyed()])
        self.assertEqual(result["result"], "error")
        self.assertIn("langgraph", result["error"])
        self.assertIn(".venv", result["error"], "要告诉用户换成项目虚拟环境启动")


class PageTests(Case):
    def test_page_shape(self) -> None:
        session = _session(self.root, flags=[_flag("flag{a}", accepted=True)])
        data = sx.session_page(self.cfg, session)
        self.assertEqual(data["session_id"], "sess-exp")
        self.assertEqual(data["items"], [])
        self.assertEqual(data["total"], 0)
        self.assertTrue(data["state"]["can_distill"])
        self.assertEqual(data["state"]["reason"], "")
        self.assertEqual(data["history"], [])
        self.assertGreater(data["distill"]["timeout"], 0)

    def test_history_reads_tail_and_marks_trigger(self) -> None:
        session = _session(self.root, flags=[_flag("flag{a}", accepted=True)])
        _audit_event(session.audit_path, {"result": "ok", "insights": 2, "outcome": "completed"},
                     ts="2026-11-01T19:00:00")
        _audit_event(session.audit_path,
                     {"result": "error", "insights": 0, "error": "ValueError: 空返回",
                      "trigger": "manual"}, ts="2026-11-01T19:30:00")
        history = sx.read_distill_events(session.audit_path)
        self.assertEqual([item["result"] for item in history], ["error", "ok"], "最新在前")
        self.assertEqual([item["trigger"] for item in history], ["manual", "auto"])
        self.assertIn("ValueError", history[0]["error"])

    def test_running_session_cannot_distill(self) -> None:
        data = sx.session_page(self.cfg, _session(self.root, status="running"))
        self.assertFalse(data["state"]["can_distill"])
        self.assertIn("还在执行", data["state"]["reason"])


class RouteTests(Case):
    def build(self, session: Any) -> TestClient:
        app = FastAPI()
        mount_session_detail(app, manager=SimpleNamespace(models=[]), cfg=self.cfg,
                             require=lambda _sid: session)
        return TestClient(app)

    def test_get_returns_page(self) -> None:
        session = _session(self.root, flags=[_flag("flag{a}", accepted=True)])
        response = self.build(session).get(f"/api/sessions/{session.session_id}/experience")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["session_id"], session.session_id)
        self.assertIn("items", payload)
        self.assertIn("can_distill", payload["state"])

    def test_post_refuses_while_running(self) -> None:
        session = _session(self.root, status="running")
        response = self.build(session).post(
            f"/api/sessions/{session.session_id}/experience/distill")
        self.assertEqual(response.status_code, 409)
        self.assertIn("还在执行", response.json()["detail"])

    def test_post_without_output_is_refused(self) -> None:
        session = _session(self.root, mission="")
        response = self.build(session).post(
            f"/api/sessions/{session.session_id}/experience/distill")
        self.assertEqual(response.status_code, 409)
        self.assertIn("没有可提炼", response.json()["detail"])

    def test_post_without_models_explains_instead_of_faking_success(self) -> None:
        session = _session(self.root, flags=[_flag("flag{a}", accepted=True)])
        response = self.build(session).post(
            f"/api/sessions/{session.session_id}/experience/distill")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["result"], "error")
        self.assertIn("没有可用模型", payload["error"])


class WiringTests(unittest.TestCase):
    """前端接线是结构性的：页签、面板、脚本顺序都在 HTML/JS 里钉住。"""

    def setUp(self) -> None:
        self.html = (Path(__file__).resolve().parents[1] / "src" / "spiritscout"
                     / "web" / "static" / "index.html").read_text(encoding="utf-8")
        self.views = (Path(__file__).resolve().parents[1] / "src" / "spiritscout"
                      / "web" / "static" / "js" / "views.js").read_text(encoding="utf-8")

    def test_tab_panel_and_dispatch_exist(self) -> None:
        self.assertIn('<button data-tab="experience">', self.html)
        self.assertIn('<div id="tab-experience" hidden></div>', self.html)
        self.assertIn('"experience"', self.views)
        self.assertIn("SessionExperience.load(S.cur)", self.views)
        self.assertIn("SessionExperience.reset()", self.views)
        self.assertIn("SessionExperience.refreshIfStale()", self.views)


if __name__ == "__main__":
    unittest.main()
