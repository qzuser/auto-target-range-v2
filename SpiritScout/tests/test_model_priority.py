"""模型优先级与子 Agent 模型展示：改完立刻生效，面板不空着。"""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from spiritscout.config.agent_models import read_naming_chain
from spiritscout.config.settings import ModelEntry
from spiritscout.gateway.registry import ModelRegistry, registry_for
from spiritscout.web.events import agent_models


def _entry(model: str, *, provider: str = "zerohh", key: str = "k") -> ModelEntry:
    return ModelEntry(model=model, provider="openai_compatible",
                      provider_ref=provider, api_key=key)


class PriorityRoutingTests(unittest.TestCase):
    """优先级链就是首选顺序：以前 route() 只认 models.yaml 的行顺序。"""

    def test_priority_chain_wins_over_file_order(self) -> None:
        entries = [_entry("deepseek-v4.1"), _entry("glm-5.3"), _entry("bonsai")]
        plain = ModelRegistry(entries)
        self.assertEqual(plain.route("execution").model, "deepseek-v4.1")
        ranked = ModelRegistry(entries, priority=["glm-5.3", "bonsai"])
        self.assertEqual(ranked.route("execution").model, "glm-5.3")
        self.assertEqual([e.model for e in ranked.top_models(3)],
                         ["glm-5.3", "bonsai", "deepseek-v4.1"])
        self.assertEqual(ranked.cheapest_for("execution").model, "glm-5.3")

    def test_priority_entries_missing_from_registry_are_ignored(self) -> None:
        entries = [_entry("a"), _entry("b")]
        registry = ModelRegistry(entries, priority=["gone", "b"])
        self.assertEqual(registry.route().model, "b")
        self.assertEqual(registry.priority, ["b"])   # 链外的旧条目直接忽略

    def test_explicit_assignment_still_beats_priority(self) -> None:
        entries = [_entry("a"), _entry("b")]
        registry = ModelRegistry(entries, priority=["a", "b"])
        self.assertEqual(registry.route(prefer_model="b").model, "b")

    def test_capability_filter_runs_inside_priority_order(self) -> None:
        plain = _entry("text-only")
        vision = _entry("vision", provider="local").model_copy(
            update={"capabilities": ["text", "image"]})
        registry = ModelRegistry([plain, vision], priority=["text-only", "vision"])
        self.assertEqual(registry.route(required_capability="image").model, "vision")

    def test_registry_for_reads_naming_chain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent_models.yaml"
            path.write_text("assignments: {}\nnaming:\n- b\n- a\n",
                            encoding="utf-8")
            self.assertEqual(read_naming_chain(path), ["b", "a"])
            cfg = SimpleNamespace(agent_models_path=str(path))
            registry = registry_for([_entry("a"), _entry("b")], cfg)
            self.assertEqual(registry.route().model, "b")

    def test_registry_for_survives_broken_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent_models.yaml"
            path.write_text("naming: not-a-list\n", encoding="utf-8")
            cfg = SimpleNamespace(agent_models_path=str(path))
            registry = registry_for([_entry("a"), _entry("b")], cfg)
            self.assertEqual(registry.route().model, "a")   # 退回注册表顺序


class HotReloadTests(unittest.TestCase):
    """停用/调优先级不该逼用户重启服务。"""

    def _manager(self, tmp: Path, models_path: Path):
        from spiritscout.web.sessions import SessionManager

        cfg = SimpleNamespace(
            workspace=SimpleNamespace(root=str(tmp / "ws")),
            models_config_path=str(models_path),
            agent_models_path=str(tmp / "agent_models.yaml"),
            audit_log_path=str(tmp / "audit.jsonl"),
            web=SimpleNamespace(), experience=SimpleNamespace(),
        )
        Path(cfg.workspace.root).mkdir(parents=True, exist_ok=True)
        return SessionManager(cfg, [_entry("a")]), cfg

    def _write_models(self, path: Path, models: list[str]) -> None:
        body = "\n".join(
            f"- model: {m}\n  provider_ref: zerohh\n  api_key: ''\n"
            f"  provider: openai_compatible\n  base_url: ''\n  api_format: auto\n"
            for m in models)
        path.write_text("providers:\n- name: zerohh\n  provider: openai_compatible\n"
                        "  base_url: http://127.0.0.1:1/v1\n  api_key: ''\n"
                        "models:\n" + body, encoding="utf-8")

    def test_reload_when_models_file_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            models_path = root / "models.yaml"
            self._write_models(models_path, ["a"])
            manager, _cfg = self._manager(root, models_path)
            self.assertEqual([m.model for m in manager.models], ["a"])
            time.sleep(0.01)
            self._write_models(models_path, ["a", "b"])
            os.utime(models_path, (time.time() + 5, time.time() + 5))
            self.assertEqual([m.model for m in manager.models], ["a", "b"])

    def test_reload_keeps_last_good_list_when_file_is_broken(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            models_path = root / "models.yaml"
            self._write_models(models_path, ["a"])
            manager, _cfg = self._manager(root, models_path)
            models_path.write_text("models: [", encoding="utf-8")
            os.utime(models_path, (time.time() + 5, time.time() + 5))
            self.assertEqual([m.model for m in manager.models], ["a"])

    def test_empty_registry_does_not_replace_working_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            models_path = root / "models.yaml"
            self._write_models(models_path, ["a"])
            manager, _cfg = self._manager(root, models_path)
            self._write_models(models_path, [])      # 全停用
            os.utime(models_path, (time.time() + 5, time.time() + 5))
            self.assertEqual([m.model for m in manager.models], ["a"])


class AgentModelPanelTests(unittest.TestCase):
    """子 Agent 面板读得到的模型：按实例取审计里最近一次真实调用。"""

    def _audit(self, tmp: Path, records: list[dict]) -> Path:
        path = tmp / "audit.jsonl"
        path.write_text("\n".join(json.dumps(r, ensure_ascii=False)
                                  for r in records) + "\n", encoding="utf-8")
        return path

    def test_picks_latest_model_per_worker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._audit(Path(tmp), [
                {"ts": "t1", "actor": "ctf-web-1", "type": "model.started",
                 "detail": {"model": "deepseek-v4.1", "task_type": "execution"}},
                {"ts": "t2", "actor": "ctf-web-1", "type": "model.started",
                 "detail": {"model": "glm-5.3", "provider_ref": "zerohh-glm",
                            "base_url": "https://newapi.zerohh.cn/v1/"}},
                {"ts": "t3", "actor": "ctf-misc-2", "type": "model.started",
                 "detail": {"model": "glm-5.3", "provider_ref": "zerohh-glm"}},
                {"ts": "t4", "actor": "gateway", "type": "model.started",
                 "detail": {"model": "glm-5.3"}},
                {"ts": "t5", "actor": "master", "type": "model.started",
                 "detail": {"model": "glm-5.3"}},
            ])
            rows = agent_models(path)["agents"]
        self.assertEqual([r["actor"] for r in rows], ["ctf-misc-2", "ctf-web-1"])
        web = next(r for r in rows if r["actor"] == "ctf-web-1")
        self.assertEqual(web["model"], "glm-5.3")      # 最近一次赢
        self.assertEqual(web["calls"], 2)
        self.assertEqual(web["provider_ref"], "zerohh-glm")
        self.assertEqual(web["base_url"], "https://newapi.zerohh.cn/v1/")

    def test_missing_or_truncated_audit_is_harmless(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nope.jsonl"
            self.assertEqual(agent_models(missing)["agents"], [])
            path = Path(tmp) / "half.jsonl"
            path.write_bytes(b'{"ts":"t1","actor":"ctf-web-1","type":"model.st')
            self.assertEqual(agent_models(path)["agents"], [])


class SessionRouteTests(unittest.TestCase):
    def test_route_is_registered(self) -> None:
        from fastapi import FastAPI

        from spiritscout.web.routes.session_detail import mount_session_detail

        app = FastAPI()
        mount_session_detail(app, manager=SimpleNamespace(), cfg=SimpleNamespace(),
                             require=lambda _sid: None)
        paths = {getattr(r, "path", "") for r in app.routes}
        self.assertIn("/api/sessions/{session_id}/agents/models", paths)


if __name__ == "__main__":   # pragma: no cover
    unittest.main()
