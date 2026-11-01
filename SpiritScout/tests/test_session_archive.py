"""会话档案的持久化、证据分层、分页与文件访问边界。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from spiritscout.blackboard import Blackboard
from spiritscout.config.settings import SystemConfig, WorkspaceConfig
from spiritscout.core.models import BlackboardLayer
from spiritscout.web.app import create_app
from spiritscout.web.deliverables import open_artifact, read_deliverables
from spiritscout.web.sessions import Session, replace_with_retry


class SessionArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.workspace = self.root / "sessions" / "sess-archive"
        self.workspace.mkdir(parents=True)
        self.bb = Blackboard(self.workspace / "bb.db")
        self.addCleanup(self.bb.close)
        self.bb.write(BlackboardLayer.TOPOLOGY, "business-context", {
            "evidence": [{"id": "E1", "kind": "page", "url": "https://archive.test/?session=hidden-value",
                          "headers": {"Authorization": "Bearer hidden-header"}}],
            "facts": [{"statement": "公开入口存在", "evidence_refs": ["E1"]},
                      {"statement": "无证据断言", "evidence_refs": ["missing"]}],
            "hypotheses": [{"statement": "权限边界待验证", "evidence_refs": ["E1"]}],
            "gaps": ["缺少多角色记录"]}, updated_by="business-agent")
        (self.workspace / "artifacts").mkdir()
        (self.workspace / "artifacts" / "证据.txt").write_text("saved output", encoding="utf-8")

    def test_supported_facts_stay_separate_from_hypotheses(self) -> None:
        result = read_deliverables(self.workspace)
        self.assertEqual(result["counts"]["fact"], 1)
        self.assertEqual(result["counts"]["hypothesis"], 3)
        fact = next(item for item in result["items"] if item["kind"] == "fact")
        self.assertEqual(fact["refs"][0]["id"], "E1")
        self.assertEqual(fact["record_id"], "business-context")
        self.assertEqual(fact["version"], 1)
        serialized = json.dumps(result)
        self.assertNotIn("hidden-value", serialized)
        self.assertNotIn("hidden-header", serialized)

    def test_pagination_filter_and_reopen_keep_saved_data(self) -> None:
        first = read_deliverables(self.workspace, limit=2)
        second = read_deliverables(self.workspace, offset=2, limit=2)
        self.assertTrue(first["has_more"])
        self.assertFalse({r["id"] for r in first["items"]} & {r["id"] for r in second["items"]})
        filtered = read_deliverables(self.workspace, kind="hypothesis", query="多角色")
        self.assertEqual(filtered["total"], 1)
        self.assertEqual(read_deliverables(self.workspace)["counts"], first["counts"])
        self.assertEqual(len(read_deliverables(self.workspace, kind="file")["items"]), 1)

    def test_file_access_rejects_traversal_and_links(self) -> None:
        secret = self.root / "private.txt"
        secret.write_text("private-marker")
        paths = ["../private.txt", str(secret), "artifacts/../meta.json", "bb.db"]
        try:
            (self.workspace / "artifacts" / "linked.txt").symlink_to(secret)
            paths.append("artifacts/linked.txt")
        except OSError:
            pass                          # Windows 无建链接特权，跳过链接逃逸这一项
        for path in paths:
            with self.subTest(path=path), self.assertRaises(OSError):
                open_artifact(self.workspace, path)
        with open_artifact(self.workspace, "artifacts/证据.txt") as file:
            self.assertEqual(file.read(), b"saved output")
        files = read_deliverables(self.workspace, kind="file")["items"]
        self.assertEqual(len(files), 1)

    def test_api_is_session_scoped_and_download_is_attachment(self) -> None:
        cfg = SystemConfig(workspace=WorkspaceConfig(root=str(self.root)),
                           models_config_path=str(self.root / "models.yaml"))
        app = create_app(cfg, [])
        session = Session(session_id="sess-archive", mode="src", target="archive.test",
                          workspace=self.workspace, status="completed")
        app.state.manager._sessions[session.session_id] = session
        with TestClient(app, base_url="http://127.0.0.1") as client:
            prefix = "/api/sessions/sess-archive"
            response = client.get(prefix + "/deliverables", params={"kind": "fact"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["total"], 1)
            self.assertEqual(client.get(prefix + "/deliverables?kind=bad").status_code, 422)
            self.assertEqual(client.get(prefix + "/deliverables?offset=-1").status_code, 422)
            self.assertEqual(client.get("/api/sessions/missing/deliverables").status_code, 404)
            response = client.get(prefix + "/artifacts/download", params={"path": "artifacts/证据.txt"})
            self.assertEqual(response.content, b"saved output")
            self.assertIn("attachment", response.headers["content-disposition"])
            self.assertEqual(client.get(prefix + "/artifacts/download", params={"path": "bb.db"}).status_code, 404)
            # NUL 字符路径抛 ValueError：按「不存在」404，不能炸成 500
            self.assertEqual(client.get(prefix + "/artifacts/download",
                                        params={"path": "artifacts/\x00.txt"}).status_code,
                             404)

    def test_empty_session_does_not_create_database(self) -> None:
        empty = self.root / "empty"
        empty.mkdir()
        self.assertEqual(read_deliverables(empty)["total"], 0)
        self.assertFalse((empty / "bb.db").exists())

class AtomicReplaceTests(unittest.TestCase):
    """meta.json 的原子替换要扛得住 Windows 上被杀软/索引短暂占用的那一下。"""

    def test_retries_through_transient_lock(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            source, target = Path(tmp) / "meta.json.tmp", Path(tmp) / "meta.json"
            source.write_text("{}", encoding="utf-8")
            real, calls = Path.replace, {"count": 0}

            def flaky(self, destination):
                calls["count"] += 1
                if calls["count"] < 3:
                    raise PermissionError(13, "拒绝访问")
                return real(self, destination)

            with patch.object(Path, "replace", flaky):
                replace_with_retry(source, target, delay=0)
            self.assertEqual(calls["count"], 3, "前两次被占用，第三次应当成功")
            self.assertEqual(target.read_text(encoding="utf-8"), "{}")

    def test_gives_up_after_last_attempt(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            source, target = Path(tmp) / "a", Path(tmp) / "b"
            source.write_text("x", encoding="utf-8")
            with patch.object(Path, "replace",
                              side_effect=PermissionError(13, "拒绝访问")) as mocked:
                with self.assertRaises(PermissionError):
                    replace_with_retry(source, target, attempts=3, delay=0)
            self.assertEqual(mocked.call_count, 3, "重试有上限，不能死循环")
