"""会话级模型选择 + 优先级链热重读。

这两条是同一个诉求的两面：**这一轮到底谁答**。会话页选了就用它，没选就按
设置页排的顺序——而且顺序是运行期读的，改完不必重启进程。
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from spiritscout.config.agent_models import read_naming_chain  # noqa: E402
from spiritscout.config.settings import (  # noqa: E402
    ModelEntry,
    SystemConfig,
    WorkspaceConfig,
)
from spiritscout.core.exceptions import SpiritScoutError  # noqa: E402
from spiritscout.gateway import AgentBoundGateway, ModelGateway, registry_for  # noqa: E402
from spiritscout.gateway.backends import MockBackend  # noqa: E402
from spiritscout.gateway.registry import ModelRegistry  # noqa: E402
from spiritscout.web.sessions import SessionManager  # noqa: E402


def _models(*names: str) -> list[ModelEntry]:
    return [ModelEntry(model=name, provider="local", api_key="sk-test",
                       base_url="http://127.0.0.1:11434/v1", api_format="chat_completions")
            for name in names]


class _Cfg:
    """只带 registry_for 需要的那两个字段（agent_models_path / gateway）。"""

    def __init__(self, path: Path) -> None:
        self.agent_models_path = str(path)
        self.gateway = type("G", (), {"priority_refresh_seconds": 30})()


def _write_chain(path: Path, chain: list[str]) -> None:
    path.write_text(json.dumps({"naming": chain}, ensure_ascii=False), encoding="utf-8")


class PriorityRefreshTests(unittest.TestCase):
    def test_chain_is_reread_while_running(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent_models.yaml"
            _write_chain(path, ["m-b", "m-a"])
            registry = registry_for(_models("m-a", "m-b"), _Cfg(path), refresh_seconds=0)
            self.assertEqual(registry.route("execution").model, "m-b")
            self.assertEqual(registry.priority, ["m-b", "m-a"])

            _write_chain(path, ["m-a"])          # 用户在前端把 a 拖到第一位
            self.assertEqual(registry.route("execution").model, "m-a")
            self.assertEqual(registry.priority, ["m-a"])

    def test_refresh_respects_interval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent_models.yaml"
            _write_chain(path, ["m-a"])
            registry = registry_for(_models("m-a", "m-b"), _Cfg(path), refresh_seconds=600)
            self.assertEqual(registry.route("execution").model, "m-a")
            _write_chain(path, ["m-b"])
            # 还没到重读间隔：仍按旧链（不为每次调用读一遍文件）
            self.assertEqual(registry.route("execution").model, "m-a")

    def test_broken_file_keeps_previous_chain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent_models.yaml"
            _write_chain(path, ["m-b"])
            registry = ModelRegistry(
                _models("m-a", "m-b"), priority=["m-b"],
                priority_source=lambda: read_naming_chain(path), refresh_seconds=0)
            self.assertEqual(registry.route("execution").model, "m-b")
            path.write_text("{ half", encoding="utf-8")   # 保存到一半/手改坏了
            self.assertEqual(registry.route("execution").model, "m-b")

    def test_chain_entries_missing_from_registry_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent_models.yaml"
            _write_chain(path, ["gone", "m-b"])
            registry = registry_for(_models("m-a", "m-b"), _Cfg(path), refresh_seconds=0)
            self.assertEqual(registry.priority, ["m-b"])
            self.assertEqual(registry.route("execution").model, "m-b")


class SessionModelTests(unittest.TestCase):
    def test_session_model_wins_over_priority_chain(self) -> None:
        gateway = ModelGateway(
            ModelRegistry(_models("m-a", "m-b", "m-c"), priority=["m-a"]),
            mock_backend=MockBackend())
        self.assertEqual(gateway.resolve_model(), "m-a")
        gateway.set_session_model("m-c")
        self.assertEqual(gateway.resolve_model(), "m-c")

    def test_explicit_binding_still_wins(self) -> None:
        gateway = ModelGateway(ModelRegistry(_models("m-a", "m-b")), mock_backend=MockBackend())
        gateway.set_session_model("m-b")
        self.assertEqual(gateway.resolve_model(model="m-a"), "m-a")

    def test_callable_override_is_read_per_call(self) -> None:
        state = {"model": ""}
        gateway = ModelGateway(ModelRegistry(_models("m-a", "m-b"), priority=["m-a"]),
                               mock_backend=MockBackend())
        gateway.set_session_model(lambda: state["model"])
        self.assertEqual(gateway.resolve_model(), "m-a")
        state["model"] = "m-b"                 # 会话页当场改选择
        self.assertEqual(gateway.resolve_model(), "m-b")

    def test_removed_model_falls_back_to_chain(self) -> None:
        gateway = ModelGateway(ModelRegistry(_models("m-a", "m-b"), priority=["m-a"]),
                               mock_backend=MockBackend())
        gateway.set_session_model("gone")
        self.assertEqual(gateway.resolve_model(), "m-a")

    def test_master_lane_prefers_session_over_assignment(self) -> None:
        gateway = ModelGateway(ModelRegistry(_models("m-a", "m-b")), mock_backend=MockBackend())
        gateway.set_session_model("m-b")
        bound = AgentBoundGateway(gateway, "m-a", session_first=True)
        self.assertEqual(bound.resolve_model(), "m-b")
        # 没选会话模型时回到编队页给灵枢的指派
        gateway.set_session_model("")
        self.assertEqual(bound.resolve_model(), "m-a")

    def test_sub_agent_assignment_is_not_overridden(self) -> None:
        gateway = ModelGateway(ModelRegistry(_models("m-a", "m-b")), mock_backend=MockBackend())
        sub = AgentBoundGateway(gateway, "m-a")
        gateway.set_session_model("m-b")
        self.assertEqual(sub.resolve_model(), "m-a")


class SessionStoreTests(unittest.TestCase):
    def _root(self, tmp: str) -> Path:
        return Path(tmp) / "workspace"

    def _cfg(self, root: Path) -> SystemConfig:
        return SystemConfig(
            workspace=WorkspaceConfig(root=str(root)),
            models_config_path=str(root / "models.yaml"),
            agent_models_path=str(root / "agents.yaml"),
            audit_log_path=str(root / "audit.jsonl"))

    def _seed_session(self, root: Path, model: str = "") -> None:
        """按磁盘格式造一个会话（meta.json 是唯一事实源，manager 启动时扫进来）。"""
        workspace = root / "sessions" / "sess-model-1"
        workspace.mkdir(parents=True, exist_ok=True)
        payload = {"session_id": "sess-model-1", "mode": "src", "target": "lab",
                   "status": "completed", "phase": "completed", "created_at": 1.0}
        if model:
            payload["model"] = model
        (workspace / "meta.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def test_set_model_persists_and_reloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            self._seed_session(root)
            manager = SessionManager(self._cfg(root), _models("m-a", "m-b"))
            session = manager.get("sess-model-1")
            self.assertIsNotNone(session)
            manager.set_model(session.session_id, "m-b")
            self.assertEqual(session.model, "m-b")
            self.assertEqual(session.brief()["model"], "m-b")
            meta = json.loads((session.workspace / "meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["model"], "m-b")

            fresh = SessionManager(self._cfg(root), _models("m-a", "m-b"))
            self.assertEqual(fresh.get("sess-model-1").model, "m-b")

    def test_unknown_model_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            self._seed_session(root)
            manager = SessionManager(self._cfg(root), _models("m-a"))
            session = manager.get("sess-model-1")
            with self.assertRaises(SpiritScoutError):
                manager.set_model(session.session_id, "not-in-registry")
            self.assertEqual(session.model, "")

    def test_clear_returns_to_global_priority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            self._seed_session(root)
            manager = SessionManager(self._cfg(root), _models("m-a"))
            session = manager.get("sess-model-1")
            manager.set_model(session.session_id, "m-a")
            manager.set_model(session.session_id, "")
            self.assertEqual(session.model, "")
            self.assertEqual(session.brief()["model"], "")

    def test_missing_session_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            self._seed_session(root)
            manager = SessionManager(self._cfg(root), _models("m-a"))
            self.assertIsNone(manager.set_model("nope", "m-a"))


if __name__ == "__main__":
    unittest.main()
