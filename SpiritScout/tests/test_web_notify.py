"""控制台提醒：解出的题与待答问题的计算口径。

提醒是「别让用户错过」的功能，最容易坏在两处：把没解出的题算成解出（判错/未判
的平台应答），或者一条坏记录把整轮提醒打断。这里把两个口径钉住：

* 只有 ``accepted is True`` 才算解出；
* 读盘/读队列一律容错，坏数据等于没有这条。

前端接线（设置分类、脚本、调度器）也在本文件里做结构性断言，免得改版时悄悄
把提醒弄丢。
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from spiritscout.web import notify
from spiritscout.web.routes.notify import mount_notify

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "spiritscout" / "web" / "static"


class _FakeQuestions:
    """够用的提问队列替身：真 Broker 要事件循环才能挂起一条待答。"""

    def __init__(self, records: list[dict[str, Any]] | None = None,
                 *, boom: bool = False) -> None:
        self.records = list(records or [])
        self.boom = boom

    def view(self) -> list[dict[str, Any]]:
        if self.boom:
            raise RuntimeError("队列正在重建")
        return [dict(record) for record in self.records]


def _flag(value: str, *, accepted: bool | None, challenge: str = "web-1",
          flag_id: str = "", found_by: str = "agent-1") -> dict[str, Any]:
    return {"flag_id": flag_id, "challenge_id": challenge, "value": value,
            "format_ok": True, "submitted": True, "accepted": accepted,
            "submit_response": "", "found_by": found_by}


def _session(root: Path, *, session_id: str = "sess-a", flags: list[dict] | None = None,
             questions: list[dict] | None = None, title: str = "打一台 Web",
             mode: str = "ctf", broker: Any = None) -> SimpleNamespace:
    workspace = root / session_id
    workspace.mkdir(parents=True, exist_ok=True)
    if flags is not None:
        (workspace / "flags.json").write_text(
            json.dumps(flags, ensure_ascii=False), encoding="utf-8")
    session = SimpleNamespace(
        session_id=session_id, workspace=workspace, mode=mode,
        flags_path=workspace / "flags.json",
        questions=broker if broker is not None else _FakeQuestions(questions),
    )
    session.display_title = lambda: title
    return session


class SolvedFlagTests(unittest.TestCase):
    def setUp(self) -> None:
        notify._CACHE.clear()
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        notify._CACHE.clear()
        self._tmp.cleanup()

    def test_only_accepted_flags_count_as_solved(self) -> None:
        session = _session(self.root, flags=[
            _flag("flag{good}", accepted=True, challenge="web-1"),
            _flag("flag{wrong}", accepted=False, challenge="web-2"),
            _flag("flag{unknown}", accepted=None, challenge="web-3"),
        ])
        items = notify.solved_items(session)
        self.assertEqual(len(items), 1, "未判定与判错都不是解出")
        self.assertEqual(items[0]["detail"]["challenge_id"], "web-1")

    def test_item_carries_session_context_and_preview(self) -> None:
        value = "flag{" + "a" * 80 + "}"
        session = _session(self.root, flags=[_flag(value, accepted=True,
                                                     challenge="crypto-7")],
                           title="赛题复盘")
        item = notify.solved_items(session)[0]
        self.assertEqual(item["kind"], notify.KIND_SOLVED)
        self.assertEqual(item["session_id"], "sess-a")
        self.assertEqual(item["session_title"], "赛题复盘")
        self.assertEqual(item["mode"], "ctf")
        self.assertEqual(item["title"], "解出一道题")
        self.assertIn("crypto-7", item["body"])
        self.assertTrue(item["detail"]["value_preview"].endswith("…"))
        self.assertLessEqual(len(item["detail"]["value_preview"]), notify.VALUE_PREVIEW)

    def test_ids_are_stable_between_polls(self) -> None:
        session = _session(self.root, flags=[_flag("flag{x}", accepted=True)])
        first = [item["id"] for item in notify.solved_items(session)]
        second = [item["id"] for item in notify.solved_items(session)]
        self.assertEqual(first, second, "同一面 Flag 每轮都必须给出同一个 id，否则会重复弹")

    def test_missing_flag_id_falls_back_to_value_digest(self) -> None:
        session = _session(self.root, flags=[_flag("flag{y}", accepted=True, flag_id="")])
        item = notify.solved_items(session)[0]
        self.assertTrue(item["id"].startswith("flag:sess-a:"))
        self.assertNotIn("flag{y}", item["id"], "id 里不该出现 flag 原文")

    def test_cache_follows_file_mtime(self) -> None:
        session = _session(self.root, flags=[_flag("flag{one}", accepted=True)])
        self.assertEqual(len(notify.solved_items(session)), 1)
        path = session.flags_path
        path.write_text(json.dumps([
            _flag("flag{one}", accepted=True),
            _flag("flag{two}", accepted=True, challenge="web-2"),
        ]), encoding="utf-8")
        stamp = path.stat().st_mtime + 5
        os.utime(path, (stamp, stamp))       # 明确的 mtime 变化，不赌文件系统精度
        self.assertEqual(len(notify.solved_items(session)), 2, "文件变了缓存要跟着失效")

    def test_cache_stamp_includes_size_so_same_tick_rewrites_are_seen(self) -> None:
        session = _session(self.root, flags=[_flag("flag{one}", accepted=True)])
        self.assertEqual(len(notify.solved_items(session)), 1)
        path = session.flags_path
        stamp = path.stat().st_mtime
        path.write_text(json.dumps([
            _flag("flag{one}", accepted=True),
            _flag("flag{two}", accepted=True, challenge="web-2"),
        ]), encoding="utf-8")
        os.utime(path, (stamp, stamp))       # mtime 故意压回原值，只剩大小能区分
        self.assertEqual(len(notify.solved_items(session)), 2,
                         "同一 mtime 下文件大小变了也要重读")

    def test_cache_is_bounded_and_drops_the_oldest(self) -> None:
        original = notify._CACHE_MAX
        notify._CACHE_MAX = 3
        try:
            for index in range(6):
                session = _session(self.root, session_id=f"sess-{index}",
                                   flags=[_flag(f"flag{{{index}}}", accepted=True)])
                self.assertEqual(len(notify.solved_items(session)), 1)
            self.assertLessEqual(len(notify._CACHE), 3, "缓存必须有界")
            self.assertIn(str(self.root / "sess-5" / "flags.json"), notify._CACHE,
                          "最近用到的条目不能被淘汰")
        finally:
            notify._CACHE_MAX = original
            notify._CACHE.clear()

    def test_broken_or_missing_files_are_ignored(self) -> None:
        broken = _session(self.root, session_id="sess-broken")
        broken.flags_path.write_text("{ not json", encoding="utf-8")
        self.assertEqual(notify.solved_items(broken), [])
        wrong_shape = _session(self.root, session_id="sess-shape")
        wrong_shape.flags_path.write_text('{"value": "flag{x}"}', encoding="utf-8")
        self.assertEqual(notify.solved_items(wrong_shape), [])
        missing = _session(self.root, session_id="sess-missing")
        self.assertEqual(notify.solved_items(missing), [])


class QuestionTests(unittest.TestCase):
    def setUp(self) -> None:
        notify._CACHE.clear()
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        notify._CACHE.clear()
        self._tmp.cleanup()

    def test_pending_question_becomes_an_item(self) -> None:
        session = _session(self.root, questions=[{
            "question_id": "ask-1", "agent": "ctf-web", "question": "要不要把 example.com 加进范围？",
            "options": ["加入", "跳过"], "multiple": False,
            "targets": [{"target": "example.com", "why": "横向"}], "requested_at": 1700000000.0,
        }], title="授权确认")
        item = notify.question_items(session)[0]
        self.assertEqual(item["kind"], notify.KIND_QUESTION)
        self.assertEqual(item["id"], "ask:sess-a:ask-1")
        self.assertEqual(item["title"], "灵枢在等你回答")
        self.assertIn("example.com", item["body"])
        self.assertEqual(item["detail"]["agent"], "ctf-web")
        self.assertEqual(item["detail"]["options"], ["加入", "跳过"])
        self.assertEqual(item["at"], 1700000000.0)

    def test_long_question_is_truncated(self) -> None:
        session = _session(self.root, questions=[{
            "question_id": "ask-2", "agent": "master", "question": "长" * 500,
            "options": [], "requested_at": 1.0}])
        body = notify.question_items(session)[0]["body"]
        self.assertTrue(body.endswith("…"))
        self.assertLessEqual(len(body), notify.QUESTION_PREVIEW)

    def test_broken_queue_does_not_break_the_round(self) -> None:
        session = _session(self.root, broker=_FakeQuestions(boom=True))
        self.assertEqual(notify.question_items(session), [])

    def test_placeholder_question_without_id_is_skipped(self) -> None:
        session = _session(self.root, questions=[{"question": "没有 id"}])
        self.assertEqual(notify.question_items(session), [])


class SnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        notify._CACHE.clear()
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        notify._CACHE.clear()
        self._tmp.cleanup()

    def test_items_sorted_newest_first_with_counts(self) -> None:
        old = _session(self.root, session_id="sess-old",
                       flags=[_flag("flag{old}", accepted=True)])
        stamp = time.time() - 600
        os.utime(old.flags_path, (stamp, stamp))
        new = _session(self.root, session_id="sess-new", questions=[{
            "question_id": "ask-new", "agent": "master", "question": "选哪个入口？",
            "options": ["A", "B"], "requested_at": time.time()}])
        data = notify.snapshot([old, new])
        self.assertEqual([item["kind"] for item in data["items"]],
                         [notify.KIND_QUESTION, notify.KIND_SOLVED])
        self.assertEqual(data["counts"], {"solved": 1, "question": 1})

    def test_items_are_capped_but_counts_stay_honest(self) -> None:
        flags = [_flag(f"flag{{{index}}}", accepted=True, flag_id=f"flag-{index}")
                 for index in range(notify.MAX_ITEMS + 12)]
        session = _session(self.root, flags=flags)
        data = notify.snapshot([session])
        self.assertEqual(len(data["items"]), notify.MAX_ITEMS)
        self.assertEqual(data["counts"]["solved"], notify.MAX_ITEMS + 12)
        self.assertTrue(data["truncated"], "被截断要明说，客户端才知道还有没列出来的")

    def test_small_snapshot_is_not_truncated(self) -> None:
        session = _session(self.root, flags=[_flag("flag{x}", accepted=True)])
        self.assertFalse(notify.snapshot([session])["truncated"])
        self.assertFalse(notify.snapshot([])["truncated"])

    def test_revision_changes_only_with_ids(self) -> None:
        session = _session(self.root, flags=[_flag("flag{x}", accepted=True)])
        first = notify.snapshot([session])["revision"]
        self.assertEqual(first, notify.snapshot([session])["revision"])
        session.flags_path.write_text(json.dumps(
            [_flag("flag{x}", accepted=True), _flag("flag{y}", accepted=True,
                                                    challenge="web-2")]),
            encoding="utf-8")
        stamp = session.flags_path.stat().st_mtime + 60
        os.utime(session.flags_path, (stamp, stamp))
        self.assertNotEqual(first, notify.snapshot([session])["revision"])

    def test_empty_console_is_quiet(self) -> None:
        data = notify.snapshot([])
        self.assertEqual(data["items"], [])
        self.assertEqual(data["counts"], {"solved": 0, "question": 0})


class RouteTests(unittest.TestCase):
    def test_endpoint_returns_snapshot(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            session = _session(root, flags=[_flag("flag{ok}", accepted=True)])
            manager = SimpleNamespace(list=lambda: [session])
            app = FastAPI()
            mount_notify(app, manager=manager)
            with TestClient(app) as client:
                response = client.get("/api/notifications")
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["counts"]["solved"], 1)
            self.assertEqual(payload["items"][0]["session_id"], "sess-a")
            self.assertIn("revision", payload)
            self.assertIs(payload["truncated"], False, "字段一个都不能少，客户端按它判断要不要提示还有")


class AppSmokeTests(unittest.TestCase):
    """真的挂进控制台：接口、首页结构、静态资源三者一起验。"""

    def test_console_serves_notifications_endpoint_and_asset(self) -> None:
        from spiritscout.config.settings import SystemConfig, WorkspaceConfig
        from spiritscout.web.app import create_app

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            app = create_app(SystemConfig(workspace=WorkspaceConfig(root=temporary)), [])
            with TestClient(app, base_url="http://127.0.0.1") as client:
                payload = client.get("/api/notifications")
                index = client.get("/")
                asset = client.get("/static/js/notify.js")
        self.assertEqual(payload.status_code, 200)
        body = payload.json()
        self.assertEqual(body["items"], [])
        self.assertEqual(body["counts"], {"solved": 0, "question": 0})
        self.assertTrue(body["revision"], "空控制台也要给 revision，前端才知道没变化")
        self.assertEqual(index.status_code, 200)
        self.assertIn("view-notify", index.text, "首页要有通知分类面板")
        self.assertEqual(asset.status_code, 200)
        self.assertIn("ConsoleNotify", asset.text, "提醒脚本要能被前端取到")


class NotifyWiringTests(unittest.TestCase):
    """前端接线：设置分类、脚本加载、单一调度器三处都得对上。"""

    def setUp(self) -> None:
        self.html = (STATIC / "index.html").read_text(encoding="utf-8")
        self.core = (STATIC / "js" / "core.js").read_text(encoding="utf-8")
        self.console = (STATIC / "js" / "console.js").read_text(encoding="utf-8")
        self.polling = (STATIC / "js" / "polling.js").read_text(encoding="utf-8")

    def test_settings_tab_and_panel_exist(self) -> None:
        self.assertIn('data-set="notify"', self.html)
        self.assertIn('id="view-notify"', self.html)
        self.assertIn('notify: "#view-notify"', self.core)

    def test_script_is_loaded_before_boot(self) -> None:
        self.assertIn("/static/js/notify.js", self.html)
        self.assertLess(self.html.index("/static/js/notify.js"),
                        self.html.index("/static/js/console.js"),
                        "notify.js 要在 console.js 之前加载，boot 里才拿得到 ConsoleNotify")

    def test_settings_view_renders_the_panel(self) -> None:
        show_block = self.core[self.core.index("function show(view) {"):]
        self.assertIn("ConsoleNotify.open()", show_block.split("\n}")[0] + "}",
                      "切到 notify 分类时要渲染通知面板")

    def test_boot_checks_once_and_polls_through_the_single_scheduler(self) -> None:
        self.assertIn("ConsoleNotify.init()", self.console)
        self.assertIn("refreshNotify: () => ConsoleNotify.check()", self.console)
        self.assertIn("refreshNotify", self.polling)
        self.assertIn("NOTIFY_VISIBLE", self.polling)

    def test_notify_module_exposes_the_contracted_surface(self) -> None:
        source = (STATIC / "js" / "notify.js").read_text(encoding="utf-8")
        for symbol in ("function create(", "function init(", "function open(",
                       "function check("):
            self.assertIn(symbol, source, f"notify.js 缺 {symbol}")


if __name__ == "__main__":
    unittest.main()
