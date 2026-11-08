"""本地 MCP 的接入模板：接口能取到、字段能直接并进配置、缺工具能看出来。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from spiritscout.config.settings import McpServerConfig, SystemConfig, WorkspaceConfig
from spiritscout.web.app import create_app
from spiritscout.web.mcp_presets import (
    LOCAL_PRESETS,
    list_presets,
    placeholders,
    preset_config,
)


def cfg_at(root: Path) -> SystemConfig:
    return SystemConfig(
        workspace=WorkspaceConfig(root=str(root)),
        models_config_path=str(root / "models.yaml"),
        agent_models_path=str(root / "agents.yaml"),
        audit_log_path=str(root / "audit.jsonl"),
    )


class PresetModelTests(unittest.TestCase):
    def test_every_preset_has_the_fields_the_form_needs(self) -> None:
        self.assertGreaterEqual(len(LOCAL_PRESETS), 8)
        for item in list_presets():
            for key in ("id", "label", "transport", "command", "args",
                        "default_risk", "available", "missing"):
                self.assertIn(key, item, f"{item.get('id')} 缺 {key}")
            self.assertEqual(item["transport"], "stdio", "本地模板都是 stdio 子进程")
            self.assertEqual(item["available"], not item["missing"])

    def test_config_only_carries_connect_fields(self) -> None:
        config = preset_config("filesystem")
        self.assertEqual(config["command"], "npx")
        self.assertEqual(config["transport"], "stdio")
        self.assertIn("{ROOT}", config["args"][-1])
        for absent in ("id", "label", "requires", "placeholder_hint"):
            self.assertNotIn(absent, config, f"{absent} 不该写进配置")

    def test_unknown_id_falls_back_to_custom(self) -> None:
        self.assertEqual(preset_config("nope")["command"], "")
        self.assertEqual(preset_config("")["args"], [])

    def test_placeholders_are_listed_once(self) -> None:
        self.assertEqual(placeholders("git"), ["{REPO}"])
        self.assertEqual(placeholders("venv-stdio"), ["{PYTHON}", "{MODULE}"])
        self.assertEqual(placeholders("custom"), [])

    def test_presets_never_carry_secrets(self) -> None:
        for item in list_presets():
            self.assertEqual(item.get("env", {}), {})
            blob = str(item)
            for word in ("api_key", "API_KEY", "token"):
                self.assertNotIn(word, blob, f"{item['id']} 里不该有密钥占位")


class PresetApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = cfg_at(Path(self.tmp.name))
        self.cfg.mcp_servers = [
            McpServerConfig(name="local-demo", transport="stdio", command="npx",
                            args=["-y", "@modelcontextprotocol/server-memory"])
        ]

    def test_presets_endpoint_lists_local_options(self) -> None:
        app = create_app(self.cfg, [])
        with TestClient(app, base_url="http://127.0.0.1") as client:
            payload = client.get("/api/resources/mcp/presets").json()
        ids = [item["id"] for item in payload["items"]]
        self.assertIn("filesystem", ids)
        self.assertIn("custom", ids)
        self.assertIn("stdio", payload["note"])

    def test_preset_list_is_not_shadowed_by_server_name_route(self) -> None:
        """`mcp/presets` 不能被 `/api/resources/mcp/{name}` 那条吃成服务器名。"""
        app = create_app(self.cfg, [])
        with TestClient(app, base_url="http://127.0.0.1") as client:
            self.assertEqual(client.get("/api/resources/mcp/presets").status_code, 200)
            self.assertEqual(client.get("/api/resources/mcp").status_code, 200)


if __name__ == "__main__":
    unittest.main()
