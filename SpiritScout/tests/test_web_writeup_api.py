"""WP 页签的后端：模式闸门、无题闸门、落盘位置，以及没模型时的兜底。

用户要的是"选中 WP 点生成，就按模板出一份"。所以这里重点验证三条：
非 CTF 会话不给生成、没有题目不给瞎编、模型不可用也照样出文档。
外加一条容易被忽略的：WP 不能落进 reports/，否则会顶掉"报告"页签读到的文件。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from spiritscout.config.settings import SystemConfig, WorkspaceConfig
from spiritscout.core.models import FlagCandidate, RunMode
from spiritscout.launch import LaunchRequest, prepare_launch
from spiritscout.web.app import create_app
from spiritscout.web.sessions import Session

CHALLENGES = [
    {"id": "web-01", "title": "登录绕过", "category": "web",
     "url": "http://a.test/", "description": "后台登录校验可绕过"},
    {"id": "pwn-01", "title": "栈溢出", "category": "pwn",
     "url": "http://b.test/", "description": "格式化字符串"},
]


def _ctf_plan(challenges=CHALLENGES):
    return prepare_launch(LaunchRequest(
        mode=RunMode.CTF, mission="一份 ctf 任务，拿 flag",
        challenges_yaml=json.dumps(challenges) if challenges else None))


class WriteUpApiTests(unittest.TestCase):
    def _client(self, tmp: str, *, mode: str = "ctf", challenges=CHALLENGES):
        root = Path(tmp)
        app = create_app(SystemConfig(workspace=WorkspaceConfig(root=tmp)), [])
        manager = app.state.manager
        session = Session(session_id="sess-wp", mode=mode, target="http://a.test",
                          workspace=root / "sess-wp")
        session.workspace.mkdir(parents=True)
        session.plan = (_ctf_plan(challenges) if challenges
                        else SimpleNamespace(challenges=[]))
        session.launch_request = {"mode": mode, "target": "http://a.test"}
        manager._sessions[session.session_id] = session
        return app, session

    def test_non_ctf_session_is_refused(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            app, _ = self._client(tmp, mode="src")
            with TestClient(app, base_url="http://127.0.0.1") as client:
                r = client.post("/api/sessions/sess-wp/writeup")
                self.assertEqual(r.status_code, 409)
                self.assertIn("CTF", r.json()["detail"])

    def test_session_without_challenges_is_refused(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            app, _ = self._client(tmp, challenges=[])
            with TestClient(app, base_url="http://127.0.0.1") as client:
                r = client.post("/api/sessions/sess-wp/writeup")
                self.assertEqual(r.status_code, 409)
                self.assertIn("题目", r.json()["detail"])

    def test_get_before_generating_returns_empty_slots(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            app, _ = self._client(tmp)
            with TestClient(app, base_url="http://127.0.0.1") as client:
                self.assertEqual(client.get("/api/sessions/sess-wp/writeup").json(),
                                 {"path": None, "markdown": None, "updated_at": None})

    def test_generate_without_models_falls_back_to_skeleton(self) -> None:
        """模型清单为空（没配模型）时也要出文档，而不是报错。"""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            app, session = self._client(tmp)
            (session.workspace / "flags.json").write_text(json.dumps([
                FlagCandidate(flag_id="f1", value="flag{a}", challenge_id="web-01",
                              accepted=True).model_dump(mode="json"),
            ], ensure_ascii=False), encoding="utf-8")
            with TestClient(app, base_url="http://127.0.0.1") as client:
                r = client.post("/api/sessions/sess-wp/writeup")
                self.assertEqual(r.status_code, 200)
                body = r.json()["markdown"]
                for heading in ("## 团队信息", "## 解题情况", "## 具体WP", "### WEB"):
                    with self.subTest(heading=heading):
                        self.assertIn(heading, body)
                self.assertIn("flag{a}", body)
                # 没解出的题必须写成未完成，不许编
                self.assertIn("未完成", body)

    def test_generated_file_lives_in_its_own_folder(self) -> None:
        """WP 落 writeup/，不落 reports/——否则报告页签会读到 WP。"""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            app, session = self._client(tmp)
            with TestClient(app, base_url="http://127.0.0.1") as client:
                self.assertEqual(
                    client.post("/api/sessions/sess-wp/writeup").status_code, 200)
            files = list((session.workspace / "writeup").glob("wp-*.md"))
            self.assertEqual(len(files), 1)
            self.assertIsNone(session.report_path())

    def test_get_reads_back_what_was_generated(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            app, _ = self._client(tmp)
            with TestClient(app, base_url="http://127.0.0.1") as client:
                made = client.post("/api/sessions/sess-wp/writeup").json()
                again = client.get("/api/sessions/sess-wp/writeup").json()
                self.assertEqual(again["markdown"], made["markdown"])
                self.assertIsNotNone(again["updated_at"])

    def test_download_serves_markdown(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            app, _ = self._client(tmp)
            with TestClient(app, base_url="http://127.0.0.1") as client:
                self.assertEqual(
                    client.get("/api/sessions/sess-wp/writeup/download").status_code, 404)
                client.post("/api/sessions/sess-wp/writeup")
                r = client.get("/api/sessions/sess-wp/writeup/download")
                self.assertEqual(r.status_code, 200)
                self.assertIn("markdown", r.headers["content-type"])

    def test_challenges_recovered_from_launch_request_after_restart(self) -> None:
        """控制台重启后 plan 为空，仍要能从落盘的题面 YAML 里把题捞回来。"""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            app, session = self._client(tmp)
            session.plan = None
            session.launch_request["challenges_yaml"] = json.dumps(CHALLENGES)
            with TestClient(app, base_url="http://127.0.0.1") as client:
                self.assertEqual(
                    client.post("/api/sessions/sess-wp/writeup").status_code, 200)


    def test_challenges_synthesized_from_flags_when_no_yaml(self) -> None:
        """单题会话：没有结构化题面，但解出过 flag，也要能写 WP。

        真实场景就是这种——任务原文里一道题，解完 flags.json 里只有 mission-1。
        """
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            app, session = self._client(tmp, challenges=[])
            session.request = {"mode": "ctf", "mission": "CTF 日志文件包含漏洞测试"}
            session.launch_request = {"mode": "ctf",
                                      "mission": "CTF 日志文件包含漏洞测试"}
            (session.workspace / "flags.json").write_text(json.dumps([
                FlagCandidate(flag_id="f1", value="CTF{ok}", challenge_id="mission-1",
                              accepted=True).model_dump(mode="json"),
            ], ensure_ascii=False), encoding="utf-8")
            with TestClient(app, base_url="http://127.0.0.1") as client:
                r = client.post("/api/sessions/sess-wp/writeup")
                self.assertEqual(r.status_code, 200)
                body = r.json()["markdown"]
                self.assertIn("CTF 日志文件包含漏洞测试", body)
                self.assertIn("CTF{ok}", body)


if __name__ == "__main__":
    unittest.main()
