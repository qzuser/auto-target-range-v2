"""会话模型选择的接口层：POST /api/sessions/{id}/model。

库层（SessionManager.set_model）另有一段测试，这里只验页面真正调的那个端点：
参数校验、422 拒绝、空值撤销、以及响应里带回来的当前选择。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from spiritscout.config.settings import ModelEntry, SystemConfig, WorkspaceConfig


def _models() -> list[ModelEntry]:
    return [ModelEntry(model=name, provider="local", api_key="sk-test",
                       base_url="http://127.0.0.1:11434/v1", api_format="chat_completions")
            for name in ("m-a", "m-b")]


class SessionModelApiTests(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        from spiritscout.web.app import create_app

        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        workspace = self.root / "sessions" / "sess-pick"
        workspace.mkdir(parents=True)
        (workspace / "meta.json").write_text(json.dumps({
            "session_id": "sess-pick", "mode": "src", "target": "lab",
            "status": "completed", "phase": "completed", "created_at": 1.0,
        }, ensure_ascii=False), encoding="utf-8")
        cfg = SystemConfig(workspace=WorkspaceConfig(root=str(self.root)),
                           models_config_path=str(self.root / "models.yaml"),
                           agent_models_path=str(self.root / "agents.yaml"),
                           audit_log_path=str(self.root / "audit.jsonl"))
        app = create_app(cfg, _models())
        self.client = TestClient(app, base_url="http://127.0.0.1")
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def test_select_model_returns_choice(self) -> None:
        resp = self.client.post("/api/sessions/sess-pick/model", json={"model": "m-b"})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["model"], "m-b")
        listed = self.client.get("/api/sessions").json()["sessions"]
        self.assertEqual(listed[0]["model"], "m-b")

    def test_clear_goes_back_to_global_priority(self) -> None:
        self.client.post("/api/sessions/sess-pick/model", json={"model": "m-b"})
        resp = self.client.post("/api/sessions/sess-pick/model", json={"model": ""})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["model"], "")

    def test_unknown_model_is_422(self) -> None:
        resp = self.client.post("/api/sessions/sess-pick/model", json={"model": "nope"})
        self.assertEqual(resp.status_code, 422, resp.text)
        self.assertIn("模型", resp.json()["detail"])

    def test_unknown_session_is_404(self) -> None:
        resp = self.client.post("/api/sessions/nope/model", json={"model": "m-a"})
        self.assertEqual(resp.status_code, 404, resp.text)

    def test_extra_field_is_rejected(self) -> None:
        resp = self.client.post("/api/sessions/sess-pick/model",
                                json={"model": "m-a", "force": True})
        self.assertEqual(resp.status_code, 422, resp.text)


if __name__ == "__main__":
    unittest.main()
