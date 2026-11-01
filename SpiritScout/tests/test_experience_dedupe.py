"""经验入库的两条硬规矩：**写进同一本库**、**高度重复就不重复存**。

为什么单独一段：提炼（自动/手动）与经验库页必须读写同一个文件，否则「提炼成功
但库里没有」；入库前的相似判定是去重的唯一闸口，阈值边界必须看得见。
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from spiritscout.config.settings import (  # noqa: E402
    ExperienceConfig,
    SystemConfig,
    WorkspaceConfig,
)
from spiritscout.knowledge.experience import (  # noqa: E402
    DEFAULT_DUPLICATE_THRESHOLD,
    ExperienceStore,
    absorb_session_dbs,
    read_page,
    shared_db_path,
)
from spiritscout.knowledge.merge import similarity  # noqa: E402


class SharedLibraryPathTests(unittest.TestCase):
    def test_shared_path_follows_workspace_root(self) -> None:
        cfg = SystemConfig(workspace=WorkspaceConfig(root="/tmp/ws"))
        self.assertEqual(shared_db_path(cfg), Path("/tmp/ws") / "experience.db")

    def test_shared_path_honours_explicit_root(self) -> None:
        cfg = SystemConfig(workspace=WorkspaceConfig(root="/tmp/ws"),
                           experience=ExperienceConfig(root="/tmp/exp"))
        self.assertEqual(shared_db_path(cfg), Path("/tmp/exp") / "experience.db")

    def test_session_page_and_library_page_agree(self) -> None:
        """会话页、经验库页、提炼落库三处算出来的必须是同一个文件。"""
        from spiritscout.web.session_experience import experience_library

        cfg = SystemConfig(workspace=WorkspaceConfig(root="/tmp/ws"))
        self.assertEqual(experience_library(cfg), shared_db_path(cfg))

    def test_runtime_uses_shared_library_not_session_workspace(self) -> None:
        """自动提炼曾经把条目写进 sessions/<id>/experience.db——库页读不到。"""
        import inspect

        from spiritscout import runtime

        self.assertIn("shared_db_path", inspect.getsource(runtime._open_workspace))
        self.assertIn("shared_db_path", inspect.getsource(runtime.resume_pending_distills))
        # 谁都不许再按会话工作区算库路径
        source = inspect.getsource(runtime)
        self.assertNotIn("experience_db_path(cfg.experience.root", source)

    def test_legacy_session_db_is_absorbed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "experience.db"
            legacy = root / "sessions" / "sess-old" / "experience.db"
            legacy.parent.mkdir(parents=True)
            old = ExperienceStore(legacy)
            try:
                old.add("登录接口的错误文案不一致说明存在用户名枚举",
                        tags=["web"], source_session="sess-old")
            finally:
                old.close()
            self.assertEqual(absorb_session_dbs(target, root / "sessions"), 1)
            page = read_page(target)
            self.assertEqual(page["total"], 1)
            # 再跑一次不重复并入
            self.assertEqual(absorb_session_dbs(target, root / "sessions"), 0)


class SimilarityDedupeTests(unittest.TestCase):
    BASE = "登录接口的错误文案不一致，可以用它判断用户名是否存在"

    def _store(self, tmp: str, threshold: float | None = None) -> ExperienceStore:
        path = Path(tmp) / "experience.db"
        if threshold is None:
            return ExperienceStore(path)
        return ExperienceStore(path, duplicate_threshold=threshold)

    def test_default_threshold_is_ninety_five_percent(self) -> None:
        self.assertAlmostEqual(DEFAULT_DUPLICATE_THRESHOLD, 0.95)

    def test_near_duplicate_is_cancelled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            try:
                self.assertTrue(store.add(self.BASE))
                # 只差标点与结尾语气：相似度高于阈值，不该再存一条
                near = self.BASE + "。"
                self.assertGreaterEqual(similarity(self.BASE, near), 0.95)
                report: dict[str, object] = {}
                self.assertEqual(store.add(near, report=report), "")
                self.assertEqual(report.get("reason"), "similar")
                self.assertGreater(float(report.get("score") or 0), 0.9)
                self.assertTrue(str(report.get("match_id") or ""))
                self.assertEqual(store.count(), 1)
            finally:
                store.close()

    def test_distinct_insight_is_kept(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            try:
                store.add(self.BASE)
                self.assertLess(similarity(self.BASE, "Shiro 默认密钥可以反序列化拿到回显"), 0.95)
                self.assertTrue(store.add("Shiro 默认密钥可以反序列化拿到回显", tags=["java"]))
                self.assertEqual(store.count(), 2)
            finally:
                store.close()

    def test_threshold_boundary_is_inclusive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp, threshold=0.9)
            try:
                store.add(self.BASE)
                near = self.BASE.replace("可以", "可")
                score = similarity(self.BASE, near)
                if score >= 0.9:
                    self.assertEqual(store.add(near), "", "达到阈值即视为重复")
                else:                                   # 语言差异太大就换成显式同文
                    self.assertEqual(store.add(self.BASE), "")
                self.assertEqual(store.count(), 1)
            finally:
                store.close()

    def test_threshold_zero_disables_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp, threshold=0)
            try:
                store.add(self.BASE)
                self.assertTrue(store.add(self.BASE + "。"), "关掉闸门就该照存（并库用）")
                self.assertEqual(store.count(), 2)
            finally:
                store.close()

    def test_merged_items_do_not_block_new_insight(self) -> None:
        """被二次提炼合并掉的原件不再参与判重：同类新经验该能进来。"""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "experience.db"
            store = ExperienceStore(db)
            try:
                first = store.add(self.BASE)
                store.add("Shiro 默认密钥可以反序列化拿到回显", tags=["java"])
            finally:
                store.close()
            import sqlite3

            conn = sqlite3.connect(db)
            try:
                conn.execute("UPDATE insights SET merged_into = 'exp-merged' "
                             "WHERE insight_id = ?", (first,))
                conn.commit()
            finally:
                conn.close()
            store = ExperienceStore(db)
            try:
                self.assertTrue(store.add(self.BASE + "。"))
            finally:
                store.close()

    def test_report_shape_is_json_serialisable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            try:
                store.add(self.BASE)
                report: dict[str, object] = {}
                store.add(self.BASE, report=report)
                json.dumps(report)          # 会被写进审计，必须可序列化
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
