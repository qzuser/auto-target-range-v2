"""模型的启用 / 停用：停用只翻状态位，配置和画像一个字段都不动。

停用之后，编队候选、路由挑选、会话启动、命名链校验都拿不到它——这些入口共用
`load_model_config()` 的默认过滤，所以「停用」是全局一致的，不靠在每个调用点
各写一遍过滤条件。只有「模型」页展示与连通性测试需要看到全部：
停用之后还得能测通，再决定要不要启用。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from spiritscout.config.settings import (
    ModelEntry,
    SystemConfig,
    WorkspaceConfig,
    load_model_config,
)
from spiritscout.core.exceptions import SpiritScoutError
from spiritscout.web import agentcfg, modelcfg
from spiritscout.web.app import create_app

PROVIDERS = [
    {"name": "cloud", "provider": "openai_compatible",
     "base_url": "https://api.example.com/v1", "api_key": ""},
    {"name": "local", "provider": "openai_compatible",
     "base_url": "http://127.0.0.1:1234/v1", "api_key": ""},
]

MODELS = [
    {"model": "cloud-big", "provider_ref": "cloud",
     "capabilities": ["reasoning", "code"], "context_window": 131072,
     "reasoning_effort_levels": ["low", "high"], "quality_score": 0.95},
    {"model": "local-small", "provider_ref": "local",
     "capabilities": ["text"], "context_window": 16384},
]


def _make_cfg(tmp: Path) -> SystemConfig:
    cfg = SystemConfig(
        workspace=WorkspaceConfig(root=str(tmp)),
        models_config_path=str(tmp / "models.yaml"),
        agent_models_path=str(tmp / "agents.yaml"),
        audit_log_path=str(tmp / "audit.jsonl"),
    )
    modelcfg.write_config(cfg.models_config_path, PROVIDERS, MODELS)
    return cfg


class EnabledFieldTests(unittest.TestCase):
    """字段本身：默认启用，显式 false 才停用。"""

    def test_defaults_to_enabled(self) -> None:
        self.assertIs(ModelEntry(model="x").enabled, True)

    def test_explicit_false_is_kept(self) -> None:
        self.assertIs(ModelEntry(model="x", enabled=False).enabled, False)


class LoaderFilterTests(unittest.TestCase):
    """装载过滤：默认剔除停用项，需要时能要全量。"""

    def test_disabled_model_is_dropped_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_cfg(Path(tmp))
            modelcfg.set_enabled(cfg.models_config_path, "local-small", False)
            self.assertEqual([m.model for m in load_model_config(cfg.models_config_path)],
                             ["cloud-big"])

    def test_include_disabled_returns_everything(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_cfg(Path(tmp))
            modelcfg.set_enabled(cfg.models_config_path, "local-small", False)
            every = load_model_config(cfg.models_config_path, include_disabled=True)
            self.assertEqual([m.model for m in every], ["cloud-big", "local-small"])
            self.assertEqual({m.model: m.enabled for m in every},
                             {"cloud-big": True, "local-small": False})

    def test_everything_enabled_is_the_old_behaviour(self) -> None:
        """没人动过开关时，装载结果与加字段前完全一致。"""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_cfg(Path(tmp))
            self.assertEqual([m.model for m in load_model_config(cfg.models_config_path)],
                             ["cloud-big", "local-small"])

    def test_provider_info_still_merges_for_disabled(self) -> None:
        """停用的模型也要能显示它属于哪个供应商（模型页要画出来）。"""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_cfg(Path(tmp))
            modelcfg.set_enabled(cfg.models_config_path, "local-small", False)
            entry = next(m for m in load_model_config(
                cfg.models_config_path, include_disabled=True)
                if m.model == "local-small")
            self.assertEqual(entry.provider_ref, "local")
            self.assertEqual(entry.base_url, "http://127.0.0.1:1234/v1")


class SetEnabledTests(unittest.TestCase):
    """翻转状态位：YAML 只多一行，画像整段不动。"""

    def test_disable_writes_a_single_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_cfg(Path(tmp))
            modelcfg.set_enabled(cfg.models_config_path, "local-small", False)
            entry = next(e for e in modelcfg.read_entries(cfg.models_config_path)
                         if e["model"] == "local-small")
            self.assertIs(entry["enabled"], False)

    def test_enable_removes_the_flag(self) -> None:
        """启用是默认状态，不必在 YAML 里留一行 enabled: true。"""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_cfg(Path(tmp))
            modelcfg.set_enabled(cfg.models_config_path, "local-small", False)
            modelcfg.set_enabled(cfg.models_config_path, "local-small", True)
            raw = Path(cfg.models_config_path).read_text(encoding="utf-8")
            self.assertNotIn("enabled", raw)
            self.assertEqual(
                [m.model for m in load_model_config(cfg.models_config_path)],
                ["cloud-big", "local-small"])

    def test_other_profile_fields_survive(self) -> None:
        """停用不该顺手重写画像——这正是绕开 canonical_entry 的原因。"""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_cfg(Path(tmp))
            before = next(e for e in modelcfg.read_entries(cfg.models_config_path)
                          if e["model"] == "cloud-big")
            modelcfg.set_enabled(cfg.models_config_path, "cloud-big", False)
            after = next(e for e in modelcfg.read_entries(cfg.models_config_path)
                         if e["model"] == "cloud-big")
            for key, value in before.items():
                if key == "enabled":
                    continue
                self.assertEqual(after[key], value, f"字段 {key} 被改写了")

    def test_unknown_model_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_cfg(Path(tmp))
            with self.assertRaises(SpiritScoutError):
                modelcfg.set_enabled(cfg.models_config_path, "nope", False)

    def test_toggle_is_idempotent(self) -> None:
        """连点两次停用不该写出两份 enabled。"""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_cfg(Path(tmp))
            modelcfg.set_enabled(cfg.models_config_path, "local-small", False)
            modelcfg.set_enabled(cfg.models_config_path, "local-small", False)
            raw = Path(cfg.models_config_path).read_text(encoding="utf-8")
            self.assertEqual(raw.count("enabled"), 1)


class DisabledModelIsNotSelectableTests(unittest.TestCase):
    """下游一致性：停用的模型指派不进去、也进不了命名链。"""

    def test_assignment_rejects_disabled_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_cfg(Path(tmp))
            modelcfg.set_enabled(cfg.models_config_path, "local-small", False)
            valid = {m.model for m in load_model_config(cfg.models_config_path)}
            with self.assertRaises(SpiritScoutError):
                agentcfg.set_assignment(
                    cfg.agent_models_path, "secretary", "local-small", valid)

    def test_assignment_accepts_enabled_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_cfg(Path(tmp))
            valid = {m.model for m in load_model_config(cfg.models_config_path)}
            table = agentcfg.set_assignment(
                cfg.agent_models_path, "secretary", "cloud-big", valid)
            self.assertEqual(table.get("secretary"), "cloud-big")

    def test_naming_chain_rejects_disabled_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_cfg(Path(tmp))
            modelcfg.set_enabled(cfg.models_config_path, "local-small", False)
            valid = {m.model for m in load_model_config(cfg.models_config_path)}
            with self.assertRaises(SpiritScoutError):
                agentcfg.set_naming_chain(
                    cfg.agent_models_path, ["local-small"], valid)


class ToggleApiTests(unittest.TestCase):
    """PATCH /api/models/{model}：只认 enabled 字段，改画像仍走 PUT。"""

    def test_patch_disables_and_reenables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_cfg(Path(tmp))
            app = create_app(cfg, [])
            with TestClient(app, base_url="http://127.0.0.1") as client:
                resp = client.patch("/api/models/local-small", json={"enabled": False})
                self.assertEqual(resp.status_code, 200, resp.text)
                rows = {m["model"]: m["enabled"] for m in resp.json()["models"]}
                self.assertIs(rows["local-small"], False)

                resp = client.patch("/api/models/local-small", json={"enabled": True})
                self.assertEqual(resp.status_code, 200, resp.text)
                rows = {m["model"]: m["enabled"] for m in resp.json()["models"]}
                self.assertIs(rows["local-small"], True)

    def test_patch_shows_disabled_models_in_listing(self) -> None:
        """模型页要能看到停用项，否则没法再启用回来。"""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_cfg(Path(tmp))
            app = create_app(cfg, [])
            with TestClient(app, base_url="http://127.0.0.1") as client:
                client.patch("/api/models/local-small", json={"enabled": False})
                listed = client.get("/api/models").json()["models"]
                self.assertEqual({m["model"] for m in listed},
                                 {"cloud-big", "local-small"})

    def test_patch_rejects_profile_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_cfg(Path(tmp))
            app = create_app(cfg, [])
            with TestClient(app, base_url="http://127.0.0.1") as client:
                resp = client.patch("/api/models/cloud-big",
                                    json={"context_window": 4096})
                self.assertEqual(resp.status_code, 422)
                # 被拒之后画像不能已经被改
                self.assertEqual(
                    client.get("/api/models").json()["models"][0]["context_window"],
                    131072)

    def test_patch_unknown_model_is_404(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_cfg(Path(tmp))
            app = create_app(cfg, [])
            with TestClient(app, base_url="http://127.0.0.1") as client:
                resp = client.patch("/api/models/nope", json={"enabled": False})
                self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
