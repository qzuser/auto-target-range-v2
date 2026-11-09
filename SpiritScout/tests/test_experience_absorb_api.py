"""合并（absorb）的接口层回归，以及「提炼/合并不再有 20 条上限」。

页面真正调的是这两个端点：

- ``POST /api/experience/absorb/preview``：交给模型出方案，不动库；
- ``POST /api/experience/absorb/apply``：只更新目标条目，**一行都不删**。

另外钉住两件事：``/api/experience`` 一次能拉 500 条（页面靠它拉全量再全选），
``/api/experience/merge/preview`` 不再拒绝超过 20 条的选择。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from spiritscout.config.settings import SystemConfig, WorkspaceConfig
from spiritscout.knowledge.experience import ExperienceStore


def _cfg(root: Path) -> SystemConfig:
    return SystemConfig(workspace=WorkspaceConfig(root=str(root)),
                        models_config_path=str(root / "models.yaml"))


def _seed(root: Path, count: int = 3) -> list[str]:
    store = ExperienceStore(root / "experience.db", duplicate_threshold=0)
    ids: list[str] = []
    try:
        ids.append(store.add("登录接口错误文案不一致说明存在用户名枚举",
                             context="登录接口", tags=["web"], source_session="sess-k"))
        ids.append(store.add("Shiro 默认密钥可以反序列化拿回显",
                             tags=["java"], source_session="sess-k"))
        for index in range(max(0, count - 2)):
            ids.append(store.add(f"口令喷洒在登录接口会触发锁定策略第 {index} 例",
                                 tags=["web"], source_session="sess-k"))
    finally:
        store.close()
    return ids


def _seed_similar(root: Path, count: int) -> list[str]:
    """造一串「极相似」条目：用来验证一次能选多少条不再被 20 截断。"""
    store = ExperienceStore(root / "experience.db", duplicate_threshold=0)
    try:
        return [store.add(f"登录接口错误文案不一致说明存在用户名枚举（第 {index} 次记录）",
                          context="登录接口", tags=["web"], source_session="sess-k")
                for index in range(count)]
    finally:
        store.close()


class ExperienceAbsorbApiTests(unittest.TestCase):
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

    def _total(self) -> int:
        return self.client.get("/api/experience").json()["total"]

    def test_apply_updates_target_without_deleting(self) -> None:
        before = self._total()
        resp = self.client.post("/api/experience/absorb/apply", json={"groups": [{
            "target_id": self.ids[0], "insight": "认证口的枚举与锁定策略在此合并",
            "context": "登录接口", "sources": [self.ids[1]], "tags": ["auth"]}]})
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["applied"], 1)
        self.assertEqual(body["deleted"], 0, "合并永远不删任何经验")
        self.assertEqual(self._total(), before, "库里条数不能变")
        listed = self.client.get("/api/experience").json()["items"]
        target = next(it for it in listed if it["insight_id"] == self.ids[0])
        self.assertEqual(target["insight"], "认证口的枚举与锁定策略在此合并")
        self.assertEqual(target["absorbed_from"], [self.ids[1]])

    def test_apply_rejects_unknown_target(self) -> None:
        resp = self.client.post("/api/experience/absorb/apply", json={"groups": [{
            "target_id": "exp-nope", "insight": "改", "sources": [self.ids[0]]}]})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self._total(), 3, "被拒的请求不能动库")

    def test_apply_rejects_empty_groups(self) -> None:
        resp = self.client.post("/api/experience/absorb/apply", json={"groups": []})
        self.assertEqual(resp.status_code, 400)

    def test_preview_needs_a_keyed_model(self) -> None:
        """没有配 API Key 的渠道时直接说清楚，而不是让模型调用炸在后面。"""
        resp = self.client.post("/api/experience/absorb/preview",
                                json={"ids": [self.ids[0]]})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("API Key", resp.text)

    def test_preview_requires_at_least_one_id(self) -> None:
        resp = self.client.post("/api/experience/absorb/preview", json={"ids": []})
        self.assertEqual(resp.status_code, 422, "空选择由请求体校验挡掉")

    def test_page_can_load_five_hundred(self) -> None:
        resp = self.client.get("/api/experience", params={"limit": 500})
        self.assertEqual(resp.status_code, 200, resp.text)


class BatchLimitRemovedTests(unittest.TestCase):
    """「只有 40 条可以提炼」的另一半：一次能选多少条不再被截断。"""

    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        from spiritscout.web.app import create_app

        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.ids = _seed_similar(self.root, 25)
        app = create_app(_cfg(self.root), [])
        self.client = TestClient(app, base_url="http://127.0.0.1")
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def test_preview_accepts_more_than_twenty(self) -> None:
        ids = self.ids[:21]
        resp = self.client.post("/api/experience/merge/preview", json={"ids": ids})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(sorted(resp.json()["absorbed"]), sorted(ids))

    def test_page_lists_everything_it_has(self) -> None:
        data = self.client.get("/api/experience", params={"limit": 500}).json()
        self.assertEqual(data["total"], 25)
        self.assertEqual(len(data["items"]), 25)


if __name__ == "__main__":
    unittest.main()
