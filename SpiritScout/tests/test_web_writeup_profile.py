"""WP 信息页：生成前那套团队信息怎么存、怎么带出来、改了方向算不算数。

用户的原话是「在编写 WP 前询问是否延用这套信息或修改，不填写也不影响生成」。
这三件事各有各的坑：信息要能记住（不然每次重填）、要能改（改了得真生效）、
要允许全空（空着也得写得出文档）。所以这一组测试一条条盯住。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from spiritscout.config.settings import SystemConfig, WorkspaceConfig
from spiritscout.core.models import RunMode
from spiritscout.launch import LaunchRequest, prepare_launch
from spiritscout.web import wp_profile
from spiritscout.web.app import create_app
from spiritscout.web.sessions import Session

CHALLENGES = [
    {"id": "web-01", "title": "登录绕过", "category": "web",
     "url": "http://a.test/", "description": "后台登录校验可绕过"},
    {"id": "pwn-01", "title": "栈溢出", "category": "pwn",
     "url": "http://b.test/", "description": "格式化字符串"},
]

TEAM = {
    "name": "灵枢战队", "members": ["张三", "李四"],
    "affiliation": "某某大学", "contest": "2026 练习赛", "notes": "只用题面给的入口",
}


def _plan():
    return prepare_launch(LaunchRequest(
        mode=RunMode.CTF, mission="一份 ctf 任务，拿 flag",
        challenges_yaml=json.dumps(CHALLENGES)))


class ProfileStoreTests(unittest.TestCase):
    def test_missing_file_reads_as_blank(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(wp_profile.load(tmp),
                             {"name": "", "members": [], "affiliation": "",
                              "contest": "", "notes": ""})
            self.assertTrue(wp_profile.is_empty(wp_profile.load(tmp)))

    def test_round_trip_keeps_the_fields_it_knows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            saved = wp_profile.save(tmp, TEAM)
            self.assertEqual(saved["name"], "灵枢战队")
            self.assertEqual(wp_profile.load(tmp), saved)
            self.assertFalse(wp_profile.is_empty(saved))

    def test_normalize_throws_away_junk(self) -> None:
        """前端送来的东西不可信：多出的键、重复队员、超长文本都不该进模板。"""
        cleaned = wp_profile.normalize({
            "name": "  " + "甲" * 200 + "  ",
            "members": ["张三", " 张三 ", "", "李四", None] + [f"队员{i}" for i in range(40)],
            "affiliation": None, "contest": "比赛", "notes": "说" * 2000,
            "unexpected": "丢掉",
        })
        self.assertEqual(len(cleaned["name"]), 120)
        self.assertEqual(cleaned["members"][:2], ["张三", "李四"])
        self.assertLessEqual(len(cleaned["members"]), wp_profile.MAX_MEMBERS)
        self.assertEqual(len(cleaned["notes"]), 1000)
        self.assertEqual(cleaned["affiliation"], "")
        self.assertNotIn("unexpected", cleaned)

    def test_corrupt_file_reads_as_blank(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wp_profile.profile_path(tmp).write_text("{ 不是 json", encoding="utf-8")
            self.assertEqual(wp_profile.load(tmp)["name"], "")


class OptionsEndpointTests(unittest.TestCase):
    def _client(self, tmp: str, *, mode: str = "ctf"):
        root = Path(tmp)
        app = create_app(SystemConfig(workspace=WorkspaceConfig(root=tmp),
                              # 模型清单指到空文件：这些用例盯的是「没有可用模型时
                              # 也要出文档」的骨架行为，别让本机跑着的模型改变结果
                              models_config_path=str(Path(tmp) / "no-models.yaml")), [])
        session = Session(session_id="sess-wp", mode=mode, target="http://a.test",
                          workspace=root / "sess-wp")
        session.workspace.mkdir(parents=True)
        session.plan = _plan()
        session.launch_request = {"mode": mode, "target": "http://a.test"}
        app.state.manager._sessions[session.session_id] = session
        return app, session

    def test_options_list_challenges_with_guessed_directions(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            app, _ = self._client(tmp)
            with TestClient(app, base_url="http://127.0.0.1") as client:
                data = client.get("/api/sessions/sess-wp/writeup/options").json()
        self.assertTrue(data["first_time"])
        self.assertEqual(data["directions"],
                         ["WEB", "PWN", "REVERSE", "MISC", "CRYPTO", "DS", "IOT"])
        self.assertEqual([c["chapter"] for c in data["challenges"]], ["WEB", "PWN"])
        self.assertEqual(data["challenges"][0]["raw"], "web")
        self.assertIsNone(data["profile"]["name"] or None)

    def test_options_refused_outside_ctf(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            app, _ = self._client(tmp, mode="src")
            with TestClient(app, base_url="http://127.0.0.1") as client:
                r = client.get("/api/sessions/sess-wp/writeup/options")
        self.assertEqual(r.status_code, 409)


class TeamMemoryTests(unittest.TestCase):
    def _client(self, tmp: str):
        root = Path(tmp)
        app = create_app(SystemConfig(workspace=WorkspaceConfig(root=tmp),
                              # 模型清单指到空文件：这些用例盯的是「没有可用模型时
                              # 也要出文档」的骨架行为，别让本机跑着的模型改变结果
                              models_config_path=str(Path(tmp) / "no-models.yaml")), [])
        session = Session(session_id="sess-wp", mode="ctf", target="http://a.test",
                          workspace=root / "sess-wp")
        session.workspace.mkdir(parents=True)
        session.plan = _plan()
        session.launch_request = {"mode": "ctf", "target": "http://a.test"}
        app.state.manager._sessions[session.session_id] = session
        return app, session

    def test_team_is_saved_and_shown_next_time(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            app, _ = self._client(tmp)
            with TestClient(app, base_url="http://127.0.0.1") as client:
                first = client.post("/api/sessions/sess-wp/writeup",
                                    json={"team": TEAM}).json()
                again = client.get("/api/sessions/sess-wp/writeup/options").json()
            self.assertIn("# 灵枢战队-解题思路", first["markdown"])
            self.assertIn("某某大学", first["markdown"])
            self.assertIn("只用题面给的入口", first["markdown"])
            self.assertEqual(again["profile"]["name"], "灵枢战队")
            self.assertEqual(again["profile"]["members"], ["张三", "李四"])
            self.assertFalse(again["first_time"])
            # 落在工作区根目录，和界面偏好分开两个文件
            self.assertTrue((Path(tmp) / "wp-profile.json").exists())

    def test_generate_without_body_reuses_last_team(self) -> None:
        """第二次点生成不该丢掉上次填的信息——这是「延用」的含义。"""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            app, _ = self._client(tmp)
            with TestClient(app, base_url="http://127.0.0.1") as client:
                client.post("/api/sessions/sess-wp/writeup", json={"team": TEAM})
                second = client.post("/api/sessions/sess-wp/writeup").json()
        self.assertIn("# 灵枢战队-解题思路", second["markdown"])
        self.assertIn("张三、李四", second["markdown"])

    def test_blank_team_falls_back_to_session_title(self) -> None:
        """全空也要出文档：标题回到会话自己的名字，模板里写「（待填写）」。"""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            app, session = self._client(tmp)
            with TestClient(app, base_url="http://127.0.0.1") as client:
                data = client.post("/api/sessions/sess-wp/writeup",
                                   json={"team": {}}).json()
        self.assertIn(f"# {session.display_title()}-解题思路", data["markdown"])
        self.assertIn("（待填写）", data["markdown"])

    def test_clearing_the_team_forgets_it(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            app, _ = self._client(tmp)
            with TestClient(app, base_url="http://127.0.0.1") as client:
                client.post("/api/sessions/sess-wp/writeup", json={"team": TEAM})
                client.post("/api/sessions/sess-wp/writeup", json={"team": {}})
                again = client.get("/api/sessions/sess-wp/writeup/options").json()
        self.assertEqual(again["profile"]["name"], "")
        self.assertTrue(again["first_time"])

    def test_direction_override_moves_the_chapter(self) -> None:
        """用户把 WEB 题改判成 PWN，正文的分章就要跟着走。"""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            app, _ = self._client(tmp)
            with TestClient(app, base_url="http://127.0.0.1") as client:
                plain = client.post("/api/sessions/sess-wp/writeup", json={}).json()
                moved = client.post("/api/sessions/sess-wp/writeup",
                                    json={"directions": {"web-01": "PWN"}}).json()
        self.assertLess(plain["markdown"].index("### WEB"),
                        plain["markdown"].index("### PWN"))
        # 改判后两题都在 PWN 章下，WEB 章消失
        self.assertNotIn("### WEB", moved["markdown"])
        self.assertEqual(moved["markdown"].count("### PWN"), 1)
        self.assertLess(moved["markdown"].index("#### 登录绕过"),
                        moved["markdown"].index("#### 栈溢出"))

    def test_unknown_direction_falls_back_instead_of_failing(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            app, _ = self._client(tmp)
            with TestClient(app, base_url="http://127.0.0.1") as client:
                r = client.post("/api/sessions/sess-wp/writeup",
                                json={"directions": {"web-01": "外星文"}})
        self.assertEqual(r.status_code, 200)
        self.assertIn("### MISC", r.json()["markdown"])

    def test_overlong_field_is_refused(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            app, _ = self._client(tmp)
            with TestClient(app, base_url="http://127.0.0.1") as client:
                r = client.post("/api/sessions/sess-wp/writeup",
                                json={"team": {"name": "甲" * 500}})
        self.assertEqual(r.status_code, 422)
        self.assertFalse((Path(tmp) / "wp-profile.json").exists())

    def test_unknown_team_key_is_refused(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            app, _ = self._client(tmp)
            with TestClient(app, base_url="http://127.0.0.1") as client:
                r = client.post("/api/sessions/sess-wp/writeup",
                                json={"team": {"nickname": "别名"}})
        self.assertEqual(r.status_code, 422)


if __name__ == "__main__":
    unittest.main()
