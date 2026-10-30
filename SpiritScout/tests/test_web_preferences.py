"""界面偏好：默认就是 CTF、切换后能读回、重开控制台仍沿用上次的选择。

"重开服务器也延用"这条是用户明确要的，所以它不只是单测一个函数，而是真的
建一个 app、读一次、再建一个 app、再读一次。
"""
from __future__ import annotations

import json
import tempfile
import unittest

from fastapi.testclient import TestClient

from spiritscout.config.settings import SystemConfig, WorkspaceConfig
from spiritscout.web.app import create_app
from spiritscout.web.routes.preferences import (
    DEFAULT_MODE,
    VALID_MODES,
    load,
    preferences_path,
    save,
)


class PreferenceFileTests(unittest.TestCase):
    def test_missing_file_defaults_to_ctf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(DEFAULT_MODE, "ctf")
            self.assertEqual(load(tmp), {"mode": "ctf"})

    def test_save_then_load_keeps_choice(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save(tmp, {"mode": "competition"})
            self.assertEqual(load(tmp), {"mode": "competition"})
            self.assertTrue(preferences_path(tmp).is_file())

    def test_corrupt_file_falls_back_without_raising(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            preferences_path(tmp).write_text("{ 这不是 JSON", encoding="utf-8")
            self.assertEqual(load(tmp), {"mode": DEFAULT_MODE})

    def test_unknown_mode_falls_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            preferences_path(tmp).write_text(
                json.dumps({"mode": "nonsense"}), encoding="utf-8")
            self.assertEqual(load(tmp), {"mode": DEFAULT_MODE})

    def test_every_valid_mode_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for mode in VALID_MODES:
                with self.subTest(mode=mode):
                    save(tmp, {"mode": mode})
                    self.assertEqual(load(tmp)["mode"], mode)


class PreferenceApiTests(unittest.TestCase):
    def test_get_defaults_to_ctf_on_fresh_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(SystemConfig(workspace=WorkspaceConfig(root=tmp)), [])
            with TestClient(app, base_url="http://127.0.0.1") as client:
                self.assertEqual(client.get("/api/preferences").json(),
                                 {"mode": "ctf"})

    def test_put_then_get(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(SystemConfig(workspace=WorkspaceConfig(root=tmp)), [])
            with TestClient(app, base_url="http://127.0.0.1") as client:
                self.assertEqual(
                    client.put("/api/preferences", json={"mode": "src"}).status_code, 200)
                self.assertEqual(client.get("/api/preferences").json(),
                                 {"mode": "src"})

    def test_choice_survives_restart(self) -> None:
        """重开控制台：同一个工作区，新建 app 后仍是上次选的模式。"""
        with tempfile.TemporaryDirectory() as tmp:
            first = create_app(SystemConfig(workspace=WorkspaceConfig(root=tmp)), [])
            with TestClient(first, base_url="http://127.0.0.1") as client:
                client.put("/api/preferences", json={"mode": "competition"})
            second = create_app(SystemConfig(workspace=WorkspaceConfig(root=tmp)), [])
            with TestClient(second, base_url="http://127.0.0.1") as client:
                self.assertEqual(client.get("/api/preferences").json(),
                                 {"mode": "competition"})

    def test_invalid_mode_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(SystemConfig(workspace=WorkspaceConfig(root=tmp)), [])
            with TestClient(app, base_url="http://127.0.0.1") as client:
                self.assertEqual(
                    client.put("/api/preferences", json={"mode": "随便"}).status_code, 422)
                # 被拒后文件不该被写坏：仍是默认
                self.assertEqual(client.get("/api/preferences").json(),
                                 {"mode": "ctf"})

    def test_empty_body_does_not_clobber(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(SystemConfig(workspace=WorkspaceConfig(root=tmp)), [])
            with TestClient(app, base_url="http://127.0.0.1") as client:
                self.assertEqual(
                    client.put("/api/preferences", json={}).status_code, 422)
                self.assertEqual(client.get("/api/preferences").json()["mode"], "ctf")


if __name__ == "__main__":
    unittest.main()
