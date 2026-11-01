"""经验二次提炼（合并压缩）与「删会话不删经验」的回归。

两条硬要求：
1. 合并只吃「极其相似」的条目，整组两两达标才允许；
2. 合并、删除会话都不能让原始经验消失——合并只是标记，可还原。
"""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any

from spiritscout.core.exceptions import SpiritScoutError
from spiritscout.knowledge import experience as exp
from spiritscout.knowledge.merge import (
    DEFAULT_THRESHOLD,
    build_groups,
    compose,
    similarity,
)


def _store(path: Path) -> exp.ExperienceStore:
    return exp.ExperienceStore(path)


def _add(store: exp.ExperienceStore, insight: str, **kwargs: Any) -> str:
    return store.add(insight, **kwargs)


class SimilarityTests(unittest.TestCase):
    def test_identical_is_one(self) -> None:
        text = "登录接口缺少错误文案时可能存在用户名枚举"
        self.assertEqual(similarity(text, text), 1.0)
        self.assertEqual(similarity(text, text + "。"), 1.0, "标点不影响判定")

    def test_near_duplicate_is_high(self) -> None:
        a = "登录接口缺少错误文案时可能存在用户名枚举"
        b = "登录接口在错误文案不一致时可能存在用户名枚举"
        self.assertGreater(similarity(a, b), DEFAULT_THRESHOLD)

    def test_different_facts_are_far(self) -> None:
        a = "登录接口缺少错误文案时可能存在用户名枚举"
        b = "Shiro 默认密钥可以反序列化打回显"
        self.assertLess(similarity(a, b), 0.3)

    def test_empty_text_is_zero(self) -> None:
        self.assertEqual(similarity("", "任意内容"), 0.0)
        self.assertEqual(similarity("", ""), 0.0)


class ComposeTests(unittest.TestCase):
    def test_keeps_longest_as_base_and_appends_new_sentences(self) -> None:
        rows = [
            {"insight_id": "a", "insight": "错误文案不一致说明存在用户名枚举",
             "context": "登录", "tags": ["web", "枚举"], "source_session": "s1"},
            {"insight_id": "b",
             "insight": "错误文案不一致说明存在用户名枚举。另外注意限速会掩盖结果",
             "context": "登录", "tags": ["web"], "source_session": "s1"},
        ]
        merged = compose(rows)
        self.assertIn("另外注意限速会掩盖结果", merged["insight"])
        self.assertEqual(merged["tags"], ["web", "枚举"])
        self.assertEqual(merged["source_session"], "s1")
        self.assertEqual(merged["merged_from"], ["b", "a"])
        self.assertEqual(merged["absorbed"], 1)

    def test_does_not_duplicate_same_sentence(self) -> None:
        rows = [
            {"insight_id": "a", "insight": "错误文案不一致说明存在用户名枚举"},
            {"insight_id": "b", "insight": "错误文案不一致说明存在用户名枚举"},
        ]
        merged = compose(rows)
        self.assertEqual(merged["insight"], "错误文案不一致说明存在用户名枚举")

    def test_cross_session_merge_clears_source(self) -> None:
        rows = [
            {"insight_id": "a", "insight": "同一个事实的表述甲很长很长",
             "source_session": "s1"},
            {"insight_id": "b", "insight": "同一个事实的表述甲很长", "source_session": "s2"},
        ]
        self.assertEqual(compose(rows)["source_session"], "")


class GroupingTests(unittest.TestCase):
    def test_requires_complete_linkage(self) -> None:
        """A≈B、B≈C 但 A≁C 时不许成组——链式合并会卷进不相干经验。"""
        a = "登录接口缺少错误文案时可能存在用户名枚举"
        b = "登录接口缺少错误提示时可能存在用户名枚举"
        c = "登录接口缺少错误文案时可能存在账号锁定策略观察机会"
        rows = [{"insight_id": "a", "insight": a},
                {"insight_id": "b", "insight": b},
                {"insight_id": "c", "insight": c}]
        self.assertLess(similarity(a, c), DEFAULT_THRESHOLD)
        groups = build_groups(rows, threshold=DEFAULT_THRESHOLD)
        self.assertTrue(all(len(g["items"]) < 3 for g in groups),
                        "三分量不成组时不能凑成一堆")

    def test_groups_obvious_duplicates(self) -> None:
        rows = [
            {"insight_id": "a", "insight": "登录接口缺少错误文案时可能存在用户名枚举"},
            {"insight_id": "b", "insight": "登录接口缺少错误文案时可能存在用户名枚举风险"},
            {"insight_id": "c", "insight": "Shiro 默认密钥可以反序列化拿回显"},
        ]
        groups = build_groups(rows)
        self.assertEqual(len(groups), 1)
        self.assertEqual([item["insight_id"] for item in groups[0]["items"]], ["a", "b"])
        self.assertGreaterEqual(groups[0]["score"], DEFAULT_THRESHOLD)

    def test_threshold_is_enforced(self) -> None:
        rows = [
            {"insight_id": "a", "insight": "登录接口缺少错误文案时可能存在用户名枚举"},
            {"insight_id": "b", "insight": "登录接口缺少错误文案时可能存在用户枚举"},
        ]
        self.assertEqual(len(build_groups(rows, threshold=0.99)), 0)
        self.assertEqual(len(build_groups(rows, threshold=0.6)), 1)

    def test_merged_rows_never_regroup(self) -> None:
        rows = [
            {"insight_id": "a", "insight": "同一个事实", "merged_into": "m"},
            {"insight_id": "b", "insight": "同一个事实"},
        ]
        self.assertEqual(build_groups(rows), [])


class MergeStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "experience.db"
        self.store = _store(self.db)
        self.addCleanup(self.store.close)
        self.a = _add(self.store, "登录接口缺少错误文案时可能存在用户名枚举",
                      context="登录接口", tags=["web", "枚举"], source_session="s1")
        self.b = _add(self.store, "登录接口缺少错误文案时可能存在用户名枚举风险",
                      context="登录接口", tags=["web"], source_session="s1")
        self.c = _add(self.store, "Shiro 默认密钥可以反序列化拿回显",
                      tags=["java"], source_session="s2")

    def _rows(self) -> list[dict[str, Any]]:
        return exp._read_all(self.db)          # noqa: SLF001 —— 直查库核对落盘

    def test_merge_marks_children_but_keeps_them(self) -> None:
        result = exp.merge_insights(self.db, [self.a, self.b])
        self.assertTrue(result["merged_id"])
        rows = {row["insight_id"]: row for row in self._rows()}
        self.assertEqual(len(rows), 4, "原件必须都在，只多一条合并结果")
        self.assertEqual(rows[self.a]["merged_into"], result["merged_id"])
        self.assertEqual(rows[self.b]["merged_into"], result["merged_id"])
        self.assertEqual(rows[result["merged_id"]]["merged_into"], "")
        self.assertIn(self.a, rows[result["merged_id"]]["merged_from"])

    def test_merge_refuses_dissimilar_items(self) -> None:
        with self.assertRaises(SpiritScoutError) as ctx:
            exp.merge_insights(self.db, [self.a, self.c])
        self.assertIn("相似", str(ctx.exception))
        self.assertEqual(len(self._rows()), 3, "拒绝时不能动库")

    def test_merge_refuses_unknown_or_already_merged(self) -> None:
        with self.assertRaises(SpiritScoutError):
            exp.merge_insights(self.db, [self.a, "insight-does-not-exist"])
        merged_id = exp.merge_insights(self.db, [self.a, self.b])["merged_id"]
        with self.assertRaises(SpiritScoutError):
            exp.merge_insights(self.db, [self.a, self.c])   # a 已被合并
        self.assertEqual(len(self._rows()), 4)
        self.assertTrue(merged_id)

    def test_merge_needs_two_items(self) -> None:
        with self.assertRaises(SpiritScoutError):
            exp.merge_insights(self.db, [self.a])

    def test_restore_brings_children_back(self) -> None:
        merged_id = exp.merge_insights(self.db, [self.a, self.b])["merged_id"]
        restored = exp.restore_merge(self.db, merged_id)
        self.assertEqual(sorted(restored["restored"]), sorted([self.a, self.b]))
        rows = {row["insight_id"]: row for row in self._rows()}
        self.assertEqual(rows[self.a]["merged_into"], "")
        self.assertEqual(rows[self.b]["merged_into"], "")
        self.assertNotIn(merged_id, rows, "还原后派生的合并条目可以再生，不留孤儿")

    def test_restore_unknown_is_none(self) -> None:
        self.assertIsNone(exp.restore_merge(self.db, "insight-nope"))

    def test_page_hides_merged_by_default(self) -> None:
        merged_id = exp.merge_insights(self.db, [self.a, self.b])["merged_id"]
        page = exp.read_page(self.db)
        ids = [item["insight_id"] for item in page["items"]]
        self.assertIn(merged_id, ids)
        self.assertNotIn(self.a, ids)
        self.assertEqual(page["total"], 2)
        self.assertEqual(page["merged_total"], 2)

        full = exp.read_page(self.db, include_merged=True)
        full_ids = [item["insight_id"] for item in full["items"]]
        self.assertIn(self.a, full_ids)
        merged_row = next(item for item in full["items"] if item["insight_id"] == self.a)
        self.assertTrue(merged_row["merged"])

    def test_recent_excludes_merged(self) -> None:
        exp.merge_insights(self.db, [self.a, self.b])
        recent = exp.read_recent(self.db, limit=10)
        self.assertEqual(recent["total"], 2)
        self.assertTrue(all(not item.get("merged_into") for item in recent["items"]))

    def test_candidates_come_from_the_library(self) -> None:
        groups = exp.merge_candidates(self.db)
        self.assertEqual(len(groups), 1)
        self.assertEqual(sorted(item["insight_id"] for item in groups[0]["items"]),
                         sorted([self.a, self.b]))


class LegacySchemaTests(unittest.TestCase):
    """老库没有 merged_into 列：读要照常，写就顺手迁移。"""

    def test_read_works_before_migration(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
            db = Path(raw) / "experience.db"
            conn = sqlite3.connect(db)
            with conn:
                conn.execute(
                    "CREATE TABLE insights(insight_id TEXT PRIMARY KEY, insight TEXT,"
                    " context TEXT, tags TEXT, source_session TEXT,"
                    " source_model TEXT, ts REAL)")
                conn.execute("INSERT INTO insights VALUES"
                             " ('i1','旧库里的经验','','[]','s1','master',1.0)")
            conn.close()
            page = exp.read_page(db)
            self.assertEqual(page["total"], 1)
            self.assertEqual(page["items"][0]["merged_into"], "")
            self.assertEqual(page["merged_total"], 0)
            self.assertEqual(exp.merge_candidates(db), [])


class SessionDeletionTests(unittest.TestCase):
    """删会话不能带走经验：库是共享的，删的只是会话工作区目录。"""

    def test_removing_session_dir_keeps_insights(self) -> None:
        import shutil

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
            root = Path(raw)
            db = root / "experience.db"
            store = _store(db)
            try:
                store.add("删了会话也还在的一条经验",
                          source_session="sess-gone", source_model="master")
            finally:
                store.close()
            workspace = root / "sessions" / "sess-gone"
            (workspace / "artifacts").mkdir(parents=True)
            (workspace / "artifacts" / "a.txt").write_text("x", encoding="utf-8")
            shutil.rmtree(workspace)          # 与 SessionManager.delete 的动作一致

            page = exp.read_page(db)
            self.assertEqual(page["total"], 1, "经验必须留在提炼库里")
            self.assertEqual(page["items"][0]["source_session"], "sess-gone")
            recent = exp.read_recent(db)
            self.assertEqual(recent["total"], 1)

    def test_absorb_before_delete_is_idempotent(self) -> None:
        """删会话前先把会话目录里的旧库并回共享库，反复执行不多收。"""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
            root = Path(raw)
            shared = root / "experience.db"
            legacy_dir = root / "sessions" / "sess-old"
            legacy_dir.mkdir(parents=True)
            legacy = _store(legacy_dir / "experience.db")
            try:
                legacy.add("只有会话目录里的一份", source_session="sess-old")
            finally:
                legacy.close()
            self.assertEqual(exp.absorb_session_dbs(shared, root / "sessions"), 1)
            self.assertEqual(exp.absorb_session_dbs(shared, root / "sessions"), 0)
            self.assertEqual(exp.read_page(shared)["total"], 1)


if __name__ == "__main__":   # pragma: no cover
    unittest.main()
