"""二次提炼的接口层回归：候选 / 预览 / 确认保留 / 拒绝 / 还原，以及删会话不删经验。

为什么单独一段：库层函数（knowledge/experience.py）自己已经测过，这里验证的是
「页面真正调的那几个接口」——参数校验、状态码、默认阈值、预览不写库、
确认后原件被删除，以及 include_merged 开关还留给旧数据。
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

    def _total(self, **params) -> int:
        return self.client.get("/api/experience", params=params).json()["total"]

    def test_candidates_only_offer_very_similar(self) -> None:
        data = self.client.get("/api/experience/merge/candidates").json()
        self.assertEqual(data["threshold"], 0.90, "默认阈值就是 90%")
        self.assertEqual(data["count"], 1)
        group = data["groups"][0]
        self.assertEqual(sorted(group["ids"]), sorted([self.ids["a"], self.ids["b"]]))
        self.assertNotIn(self.ids["c"], group["ids"])
        self.assertGreaterEqual(group["score"], 0.90)

    def test_candidates_threshold_is_customizable(self) -> None:
        """页面把相似度改成别的值，后端就得按那个值筛。"""
        strict = self.client.get("/api/experience/merge/candidates",
                                 params={"threshold": 0.99}).json()
        loose = self.client.get("/api/experience/merge/candidates",
                                params={"threshold": 0.6}).json()
        self.assertEqual(strict["threshold"], 0.99)
        self.assertEqual(strict["count"], 0, "0.97 的相似度过不了 0.99")
        self.assertGreaterEqual(loose["count"], 1)

    def test_preview_does_not_touch_the_library(self) -> None:
        resp = self.client.post("/api/experience/merge/preview", json={
            "ids": [self.ids["a"], self.ids["b"]]})
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertFalse(body["applied"], "预览不是落库")
        self.assertIn("insight", body)
        self.assertEqual(sorted(body["absorbed"]), sorted([self.ids["a"], self.ids["b"]]))
        self.assertEqual(self._total(), 3, "预览之后一条都不能少")

    def test_confirm_writes_result_and_deletes_originals(self) -> None:
        preview = self.client.post("/api/experience/merge/preview", json={
            "ids": [self.ids["a"], self.ids["b"]]}).json()
        resp = self.client.post("/api/experience/merge", json={
            "ids": [self.ids["a"], self.ids["b"]], "threshold": 0.9})
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertTrue(body["applied"])
        merged_id = body["merged_id"]
        self.assertEqual(sorted(body["removed"]), sorted([self.ids["a"], self.ids["b"]]))
        self.assertEqual(body["insight"], preview["insight"], "确认的是看过的那份稿子")

        page = self.client.get("/api/experience").json()
        ids = [item["insight_id"] for item in page["items"]]
        self.assertIn(merged_id, ids)
        self.assertNotIn(self.ids["a"], ids, "确认保留后原件应当被删除")
        self.assertNotIn(self.ids["b"], ids)
        self.assertEqual(page["total"], 2)
        self.assertEqual(page["merged_total"], 0, "新口径不在库里留「已合并」原件")

        full = self.client.get("/api/experience",
                               params={"include_merged": "true"}).json()
        full_ids = [item["insight_id"] for item in full["items"]]
        self.assertNotIn(self.ids["a"], full_ids, "include_merged 也找不回已删的原件")

    def test_confirm_refuses_dissimilar(self) -> None:
        resp = self.client.post("/api/experience/merge", json={
            "ids": [self.ids["a"], self.ids["c"]]})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("相似", resp.json()["detail"])
        self.assertEqual(self._total(), 3, "被拒绝时不能动库")

    def test_merge_requires_two_ids(self) -> None:
        resp = self.client.post("/api/experience/merge", json={"ids": [self.ids["a"]]})
        self.assertEqual(resp.status_code, 422, "单条不该被接受")

    def test_too_many_ids_are_rejected(self) -> None:
        """「全选」一次勾太多也不行：上限 20 条，前端同一口径。"""
        resp = self.client.post("/api/experience/merge/preview",
                                json={"ids": [f"exp-{i}" for i in range(21)]})
        self.assertEqual(resp.status_code, 422)

    def test_restore_keeps_new_style_result(self) -> None:
        merged = self.client.post("/api/experience/merge", json={
            "ids": [self.ids["a"], self.ids["b"]]}).json()
        resp = self.client.post("/api/experience/merge/restore",
                                json={"merged_id": merged["merged_id"]})
        self.assertEqual(resp.status_code, 404, "原件已删，没有可还原的东西")
        self.assertEqual(self._total(), 2, "合并结果不能被还原误删")

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
