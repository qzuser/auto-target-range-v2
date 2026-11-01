"""二次提炼的接口层回归：合并 / 拒绝 / 还原，以及删会话不删经验。

为什么单独一段：库层函数（knowledge/experience.py）自己已经测过，这里验证的是
「页面真正调的那三个接口」——参数校验、状态码、默认过滤和 include_merged 开关。
"""
from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from spiritscout.config.settings import SystemConfig, WorkspaceConfig
from spiritscout.knowledge.experience import ExperienceStore


def _cfg(root: Path) -> SystemConfig:
    return SystemConfig(workspace=WorkspaceConfig(root=str(root)),
                        models_config_path=str(root / "models.yaml"))


def _seed(root: Path) -> dict[str, str]:
    """造一组「极相似但都已经进库」的条目。

    入库判重（0.95）会挡掉新写入的同义句，所以这里显式关掉那道闸门——二次提炼
    面对的是**历史数据**（旧版本写进来的同义句、外部导入的库），两组能力各测各的。
    """
    store = ExperienceStore(root / "experience.db", duplicate_threshold=0)
    try:
        a = store.add("登录接口错误文案不一致说明存在用户名枚举",
                      context="登录接口", tags=["web"], source_session="sess-known")
        b = store.add("登录接口错误文案不一致说明存在用户名枚举风险",
                      context="登录接口", tags=["web"], source_session="sess-known")
        c = store.add("Shiro 默认密钥可以反序列化拿回显", tags=["java"],
                      source_session="sess-known")
    finally:
        store.close()
    return {"a": a, "b": b, "c": c}


class ExperienceMergeApiTests(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        from spiritscout.web.app import create_app

        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.ids = _seed(self.root)
        app = create_app(_cfg(self.root), [])
        self.client = TestClient(app, base_url="http://127.0.0.1")
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def test_candidates_only_offer_very_similar(self) -> None:
        data = self.client.get("/api/experience/merge/candidates").json()
        self.assertEqual(data["count"], 1)
        group = data["groups"][0]
        self.assertEqual(sorted(group["ids"]), sorted([self.ids["a"], self.ids["b"]]))
        self.assertNotIn(self.ids["c"], group["ids"])
        self.assertGreaterEqual(group["score"], 0.85)
        self.assertIn("insight", group["preview"])

    def test_merge_hides_originals_but_keeps_them(self) -> None:
        resp = self.client.post("/api/experience/merge", json={
            "ids": [self.ids["a"], self.ids["b"]]})
        self.assertEqual(resp.status_code, 200, resp.text)
        merged_id = resp.json()["merged_id"]

        page = self.client.get("/api/experience").json()
        ids = [item["insight_id"] for item in page["items"]]
        self.assertIn(merged_id, ids)
        self.assertNotIn(self.ids["a"], ids, "被合并的原件默认不再列出")
        self.assertEqual(page["total"], 2)
        self.assertEqual(page["merged_total"], 2, "但要在统计里如实报告条数")

        full = self.client.get("/api/experience",
                               params={"include_merged": "true"}).json()
        full_ids = [item["insight_id"] for item in full["items"]]
        self.assertIn(self.ids["a"], full_ids, "原件必须还能查回来")
        self.assertIn(self.ids["b"], full_ids)

    def test_merge_refuses_dissimilar(self) -> None:
        resp = self.client.post("/api/experience/merge", json={
            "ids": [self.ids["a"], self.ids["c"]]})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("相似", resp.json()["detail"])
        self.assertEqual(self.client.get("/api/experience").json()["total"], 3,
                         "被拒绝时不能动库")

    def test_merge_requires_two_ids(self) -> None:
        resp = self.client.post("/api/experience/merge", json={"ids": [self.ids["a"]]})
        self.assertEqual(resp.status_code, 422, "单条不该被接受")

    def test_restore_returns_originals(self) -> None:
        merged = self.client.post("/api/experience/merge", json={
            "ids": [self.ids["a"], self.ids["b"]]}).json()
        resp = self.client.post("/api/experience/merge/restore",
                                json={"merged_id": merged["merged_id"]})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(sorted(resp.json()["restored"]),
                         sorted([self.ids["a"], self.ids["b"]]))
        page = self.client.get("/api/experience").json()
        self.assertEqual(page["total"], 3, "还原后三条都在")
        self.assertEqual(page["merged_total"], 0)

    def test_restore_unknown_is_404(self) -> None:
        resp = self.client.post("/api/experience/merge/restore",
                                json={"merged_id": "exp-nope"})
        self.assertEqual(resp.status_code, 404)


class DeleteSessionKeepsExperienceTests(unittest.TestCase):
    """删会话只删工作区，经验必须留在提炼库里（用户明确要求）。"""

    def test_delete_session_keeps_its_insights(self) -> None:
        from fastapi.testclient import TestClient

        from spiritscout.web.app import create_app
        from spiritscout.web.sessions import Session

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
            root = Path(raw)
            app = create_app(_cfg(root), [])
            workspace = root / "sessions" / "sess-doomed"
            workspace.mkdir(parents=True)
            (workspace / "note.txt").write_text("临时", encoding="utf-8")
            store = ExperienceStore(root / "experience.db")
            try:
                store.add("删了会话也要留下的一条经验",
                          tags=["web"], source_session="sess-doomed")
            finally:
                store.close()
            session = Session(session_id="sess-doomed", mode="src", target="local",
                              workspace=workspace, status="completed", title="待删会话")
            app.state.manager._sessions["sess-doomed"] = session

            with TestClient(app, base_url="http://127.0.0.1") as client:
                before = client.get("/api/experience").json()
                self.assertEqual(before["total"], 1)
                asyncio.run(app.state.manager.delete("sess-doomed", confirm=True))
                self.assertFalse(workspace.exists(), "工作区目录应被清掉")
                after = client.get("/api/experience").json()
                self.assertEqual(after["total"], 1, "经验不能被连带删除")
                self.assertEqual(after["items"][0]["source_session"], "sess-doomed")

    def test_delete_session_absorbs_legacy_session_db(self) -> None:
        """老版本把经验写进会话目录：删会话前必须先并回共享库。"""
        from fastapi.testclient import TestClient

        from spiritscout.web.app import create_app
        from spiritscout.web.sessions import Session

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
            root = Path(raw)
            app = create_app(_cfg(root), [])
            workspace = root / "sessions" / "sess-legacy"
            workspace.mkdir(parents=True)
            legacy = ExperienceStore(workspace / "experience.db")
            try:
                legacy.add("只存在于会话目录里的经验", source_session="sess-legacy")
            finally:
                legacy.close()
            session = Session(session_id="sess-legacy", mode="src", target="local",
                              workspace=workspace, status="completed", title="旧会话")
            app.state.manager._sessions["sess-legacy"] = session

            with TestClient(app, base_url="http://127.0.0.1") as client:
                asyncio.run(app.state.manager.delete("sess-legacy", confirm=True))
                after = client.get("/api/experience").json()
                self.assertEqual(after["total"], 1,
                                 "会话目录里的旧经验要先并库，不能随目录消失")


if __name__ == "__main__":   # pragma: no cover
    unittest.main()
