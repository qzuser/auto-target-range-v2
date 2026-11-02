"""经验二次提炼（合并压缩）与「删会话不删经验」的回归。

三条硬要求：
1. 提炼只吃「极其相似」的条目，整组两两达标才允许，阈值默认 90% 且可自定义；
2. **先提炼、后确认**：预览一步一个字都不写库；用户确认保留才把结果入库，
   并在同一个事务里删掉被提炼的原件；
3. 删除会话不能让经验消失（库是共享的，删的只是工作区目录）。
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

from spiritscout.core.exceptions import SpiritScoutError
from spiritscout.knowledge import experience as exp
from spiritscout.knowledge.merge import (
    DEFAULT_THRESHOLD,
    build_groups,
    clamp_threshold,
    compose,
    similarity,
)


def _store(path: Path) -> exp.ExperienceStore:
    """测试用的库：关掉入库判重，好造出「已经进库的同义句」。

    入库判重（0.95）是新加的一道闸门，会挡掉这里刻意准备的两条近义条目；
    二次提炼处理的是**已经在库里的**历史数据，所以这里按 0 阈值造样本。
    """
    return exp.ExperienceStore(path, duplicate_threshold=0)


def _add(store: exp.ExperienceStore, insight: str, **kwargs: Any) -> str:
    return store.add(insight, **kwargs)


class SimilarityTests(unittest.TestCase):
    def test_identical_is_one(self) -> None:
        text = "登录接口缺少错误文案时可能存在用户名枚举"
        self.assertEqual(similarity(text, text), 1.0)
        self.assertEqual(similarity(text, text + "。"), 1.0, "标点不影响判定")

    def test_default_threshold_is_ninety_percent(self) -> None:
        """默认 90%：页面上不填就是这个值，改成别的必须显式传。"""
        self.assertEqual(DEFAULT_THRESHOLD, 0.90)

    def test_threshold_is_clamped(self) -> None:
        self.assertEqual(clamp_threshold(1.5), 1.0)
        self.assertEqual(clamp_threshold(0.1), 0.5)
        self.assertEqual(clamp_threshold("0.93"), 0.93)
        self.assertEqual(clamp_threshold(None), DEFAULT_THRESHOLD)
        self.assertEqual(clamp_threshold(float("nan")), DEFAULT_THRESHOLD)

    def test_near_duplicate_is_high(self) -> None:
        a = "登录接口缺少错误文案时可能存在用户名枚举"
        b = "登录接口缺少错误文案时可能存在用户名枚举风险"
        self.assertGreater(similarity(a, b), DEFAULT_THRESHOLD)

    def test_reworded_sentence_falls_below_default(self) -> None:
        """换成同义改写（0.857）就过不了 90% 的闸门：宁可少合，也不猜。"""
        a = "登录接口缺少错误文案时可能存在用户名枚举"
        b = "登录接口在错误文案不一致时可能存在用户名枚举"
        self.assertLess(similarity(a, b), DEFAULT_THRESHOLD)
        self.assertGreater(similarity(a, b), 0.6, "调低阈值仍能把它捞回来")

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

    def _legacy_merge(self, parent_ids: list[str]) -> str:
        """造一条「旧口径」合并：原件还在库里、只标记 merged_into。"""
        merged_id = "exp-legacy"
        conn = sqlite3.connect(self.db)
        try:
            with conn:
                conn.execute(
                    "INSERT INTO insights (insight_id, insight, context, tags,"
                    " source_session, source_model, ts, merged_from)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (merged_id, "旧口径的合并稿", "", json.dumps(["web"]),
                     "", "merge", time.time(), json.dumps(parent_ids)))
                conn.executemany(
                    "UPDATE insights SET merged_into = ? WHERE insight_id = ?",
                    [(merged_id, key) for key in parent_ids])
        finally:
            conn.close()
        return merged_id

    def test_preview_writes_nothing(self) -> None:
        """第一步只出稿子：库里一条都不能变，用户还没确认。"""
        preview = exp.merge_preview(self.db, [self.a, self.b])
        self.assertFalse(preview["applied"])
        self.assertIn("insight", preview)
        self.assertEqual(len(preview["merged_from"]), 2)
        self.assertGreaterEqual(preview["score"], DEFAULT_THRESHOLD)
        rows = {row["insight_id"]: row for row in self._rows()}
        self.assertEqual(len(rows), 3, "预览不许写库")
        self.assertEqual(rows[self.a]["merged_into"], "")

    def test_preview_refuses_dissimilar(self) -> None:
        with self.assertRaises(SpiritScoutError) as ctx:
            exp.merge_preview(self.db, [self.a, self.c])
        self.assertIn("相似", str(ctx.exception))
        self.assertEqual(len(self._rows()), 3)

    def test_confirm_removes_originals_and_writes_result(self) -> None:
        """确认保留：结果入库、被提炼的原件删除，只留结果这一条。"""
        result = exp.merge_insights(self.db, [self.a, self.b], confirm=True)
        self.assertTrue(result["applied"])
        self.assertTrue(result["merged_id"])
        self.assertEqual(sorted(result["removed"]), sorted([self.a, self.b]))
        rows = {row["insight_id"]: row for row in self._rows()}
        self.assertEqual(sorted(rows), sorted([result["merged_id"], self.c]),
                         "被提炼的原件应当已经不在了")
        self.assertIn(self.a, rows[result["merged_id"]]["merged_from"],
                      "溯源信息要留在结果上")
        self.assertEqual(rows[result["merged_id"]]["merged_into"], "")

    def test_merge_refuses_dissimilar_items(self) -> None:
        with self.assertRaises(SpiritScoutError) as ctx:
            exp.merge_insights(self.db, [self.a, self.c], confirm=True)
        self.assertIn("相似", str(ctx.exception))
        self.assertEqual(len(self._rows()), 3, "拒绝时不能动库")

    def test_merge_refuses_unknown_or_already_merged(self) -> None:
        with self.assertRaises(SpiritScoutError):
            exp.merge_insights(self.db, [self.a, "insight-does-not-exist"], confirm=True)
        merged_id = exp.merge_insights(self.db, [self.a, self.b], confirm=True)["merged_id"]
        with self.assertRaises(SpiritScoutError):
            # a、b 已随确认一起删除，再提炼就是「经验不存在」
            exp.merge_insights(self.db, [self.a, self.c], confirm=True)
        ids = [row["insight_id"] for row in self._rows()]
        self.assertEqual(sorted(ids), sorted([merged_id, self.c]))

    def test_merge_needs_two_items(self) -> None:
        with self.assertRaises(SpiritScoutError):
            exp.merge_insights(self.db, [self.a], confirm=True)

    def test_restore_still_works_for_legacy_marks(self) -> None:
        """旧库里的「标记式」合并还能还原：原件一直在，合并稿移除。"""
        merged_id = self._legacy_merge([self.a, self.b])
        restored = exp.restore_merge(self.db, merged_id)
        self.assertEqual(sorted(restored["restored"]), sorted([self.a, self.b]))
        rows = {row["insight_id"]: row for row in self._rows()}
        self.assertEqual(rows[self.a]["merged_into"], "")
        self.assertEqual(rows[self.b]["merged_into"], "")
        self.assertNotIn(merged_id, rows, "还原后派生的合并条目可以再生，不留孤儿")

    def test_restore_never_deletes_new_style_result(self) -> None:
        """新口径没有可还原的原件：还原必须无动于衷，不能把结果删了。"""
        merged_id = exp.merge_insights(self.db, [self.a, self.b], confirm=True)["merged_id"]
        self.assertIsNone(exp.restore_merge(self.db, merged_id))
        ids = [row["insight_id"] for row in self._rows()]
        self.assertIn(merged_id, ids, "合并结果不能被还原误删")

    def test_restore_unknown_is_none(self) -> None:
        self.assertIsNone(exp.restore_merge(self.db, "insight-nope"))

    def test_page_hides_legacy_merged_by_default(self) -> None:
        merged_id = self._legacy_merge([self.a, self.b])
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

    def test_after_confirm_only_the_result_is_listed(self) -> None:
        merged_id = exp.merge_insights(self.db, [self.a, self.b], confirm=True)["merged_id"]
        page = exp.read_page(self.db)
        self.assertEqual(sorted(item["insight_id"] for item in page["items"]),
                         sorted([merged_id, self.c]))
        self.assertEqual(page["merged_total"], 0, "新口径没有留在库里的「已合并」原件")

    def test_recent_excludes_legacy_merged(self) -> None:
        self._legacy_merge([self.a, self.b])
        recent = exp.read_recent(self.db, limit=10)
        self.assertEqual(recent["total"], 2)
        self.assertTrue(all(not item.get("merged_into") for item in recent["items"]))

    def test_candidates_come_from_the_library(self) -> None:
        groups = exp.merge_candidates(self.db)
        self.assertEqual(len(groups), 1)
        self.assertEqual(sorted(item["insight_id"] for item in groups[0]["items"]),
                         sorted([self.a, self.b]))

    def test_custom_threshold_filters_candidates(self) -> None:
        """阈值走参数：调到 1.0 这两条近义句就不再成组。"""
        self.assertEqual(len(exp.merge_candidates(self.db, threshold=1.0)), 0)
        self.assertEqual(len(exp.merge_candidates(self.db, threshold=0.6)), 1)


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
