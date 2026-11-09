"""经验合并（absorb）：交给模型判断能否并入已有条目，且**一条都不许删**。

硬约束（对应用户要求「强制要求不能删除任何经验」）：

1. 只更新目标条目，任何路径都不出现 DELETE；
2. 目标必须落在本次候选集内，模型编的 id 一律作废；
3. 落库前后行数必须一致，少一行就整体失败；
4. 模型给不出分组时什么都不写，如实回「没有可合并的内容」。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from spiritscout.core.exceptions import SpiritScoutError
from spiritscout.knowledge import absorb as ab
from spiritscout.knowledge import experience as exp


class _Resp:
    def __init__(self, content: str) -> None:
        self.content = content


def _seed(path: Path, texts: list[str]) -> list[str]:
    """造库：按顺序写入若干条，返回 insight_id 列表。"""
    store = exp.ExperienceStore(path, duplicate_threshold=0)
    try:
        return [store.add(text, context=f"场景{index}", tags=["web", f"t{index}"],
                          source_session="sess-a", source_model="m")
                for index, text in enumerate(texts)]
    finally:
        store.close()


def _rows(path: Path) -> list[dict[str, Any]]:
    import sqlite3 as sq

    conn = sq.connect(str(path))
    conn.row_factory = sq.Row
    try:
        return [dict(row) for row in conn.execute("SELECT * FROM insights")]
    finally:
        conn.close()


class CollectTests(unittest.TestCase):
    def test_collect_splits_selected_and_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "experience.db"
            ids = _seed(path, ["甲经验讲登录枚举", "乙经验讲上传绕过", "丙经验讲口令喷洒"])
            selected, candidates = ab.collect(path, [ids[0]])
            self.assertEqual([row["insight_id"] for row in selected], [ids[0]])
            self.assertEqual({row["insight_id"] for row in candidates},
                             {ids[1], ids[2]})

    def test_collect_rejects_unknown_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "experience.db"
            _seed(path, ["甲"])
            with self.assertRaises(SpiritScoutError):
                ab.collect(path, ["exp-not-exist"])

    def test_collect_requires_at_least_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "experience.db"
            _seed(path, ["甲"])
            with self.assertRaises(SpiritScoutError):
                ab.collect(path, [])

    def test_collect_missing_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SpiritScoutError):
                ab.collect(Path(tmp) / "nope.db", ["exp-1"])


class ValidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.selected = [{"insight_id": "exp-a", "insight": "甲", "tags": []},
                         {"insight_id": "exp-b", "insight": "乙", "tags": []}]
        self.candidates = [{"insight_id": "exp-t", "insight": "目标",
                            "tags": ["web"], "context": "场景"}]

    def test_drops_unknown_target(self) -> None:
        groups = ab.validate_groups(
            [{"target_id": "exp-made-up", "insight": "合并后", "sources": ["exp-a"]}],
            selected=self.selected, candidates=self.candidates)
        self.assertEqual(groups, [], "模型编的 id 必须整组作废")

    def test_drops_empty_insight_or_sources(self) -> None:
        for bad in ({"target_id": "exp-t", "insight": "", "sources": ["exp-a"]},
                    {"target_id": "exp-t", "insight": "合并后", "sources": []},
                    {"target_id": "exp-t", "insight": "合并后", "sources": ["exp-zzz"]}):
            self.assertEqual(ab.validate_groups([bad], selected=self.selected,
                                                candidates=self.candidates), [])

    def test_groups_one_entry_per_target_and_union_sources(self) -> None:
        groups = ab.validate_groups([
            {"target_id": "exp-t", "insight": "第一版", "sources": ["exp-a"]},
            {"target_id": "exp-t", "insight": "第二版", "sources": ["exp-b"]},
        ], selected=self.selected, candidates=self.candidates)
        self.assertEqual(len(groups), 1, "同一条目标只保留一个分组")
        self.assertEqual(groups[0]["sources"], ["exp-a", "exp-b"])
        self.assertEqual(groups[0]["insight"], "第一版", "先到的版本为准")

    def test_tags_are_unioned_not_replaced(self) -> None:
        groups = ab.validate_groups(
            [{"target_id": "exp-t", "insight": "合并后", "sources": ["exp-a"],
              "tags": ["ctf"]}],
            selected=self.selected, candidates=self.candidates)
        self.assertIn("web", groups[0]["tags"], "目标原有标签不能被丢掉")
        self.assertIn("ctf", groups[0]["tags"])

    def test_insight_is_truncated(self) -> None:
        groups = ab.validate_groups(
            [{"target_id": "exp-t", "insight": "字" * 5000, "sources": ["exp-a"]}],
            selected=self.selected, candidates=self.candidates)
        self.assertEqual(len(groups[0]["insight"]), ab.MAX_INSIGHT)


class ApplyTests(unittest.TestCase):
    def test_apply_updates_target_and_deletes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "experience.db"
            ids = _seed(path, ["甲经验讲登录枚举", "乙经验讲上传绕过", "丙经验讲口令喷洒"])
            before = _rows(path)
            result = ab.apply_absorb(path, [{
                "target_id": ids[1], "insight": "上传绕过在文件名过滤不全时生效",
                "context": "上传点", "sources": [ids[2]], "tags": ["upload"]}])
            after = _rows(path)
            self.assertEqual(result["deleted"], 0)
            self.assertEqual(len(after), len(before), "合并绝不能少一行")
            self.assertEqual({row["insight_id"] for row in after},
                             {row["insight_id"] for row in before})
            target = next(row for row in after if row["insight_id"] == ids[1])
            self.assertEqual(target["insight"], "上传绕过在文件名过滤不全时生效")
            self.assertEqual(json.loads(target["absorbed_from"]), [ids[2]],
                             "溯源要记下吸收了谁")
            self.assertIn("upload", target["tags"])

    def test_apply_rejects_missing_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "experience.db"
            ids = _seed(path, ["甲", "乙"])
            with self.assertRaises(SpiritScoutError):
                ab.apply_absorb(path, [{"target_id": "exp-nope",
                                        "insight": "合并后", "sources": [ids[0]]}])

    def test_apply_rejects_no_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "experience.db"
            ids = _seed(path, ["甲", "乙"])
            with self.assertRaises(SpiritScoutError):
                ab.apply_absorb(path, [{"target_id": ids[0], "insight": "合并后",
                                        "sources": ["exp-nope"]}])

    def test_apply_rejects_empty_groups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "experience.db"
            _seed(path, ["甲"])
            with self.assertRaises(SpiritScoutError):
                ab.apply_absorb(path, [])

    def test_apply_keeps_previous_absorbed_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "experience.db"
            ids = _seed(path, ["甲", "乙", "丙"])
            ab.apply_absorb(path, [{"target_id": ids[0], "insight": "第一版",
                                    "sources": [ids[1]]}])
            ab.apply_absorb(path, [{"target_id": ids[0], "insight": "第二版",
                                    "sources": [ids[2]]}])
            row = next(r for r in _rows(path) if r["insight_id"] == ids[0])
            self.assertEqual(json.loads(row["absorbed_from"]), [ids[1], ids[2]],
                             "多次合并的溯源要累积，不能覆盖")

    def test_module_never_deletes(self) -> None:
        """代码级兜底：这个模块里根本不该出现删除语句。"""
        source = Path(ab.__file__).read_text(encoding="utf-8").upper()
        self.assertNotIn("DELETE FROM", source)
        self.assertNotIn("DROP TABLE", source)

    def test_repeated_apply_never_shrinks_library(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "experience.db"
            ids = _seed(path, ["甲", "乙", "丙", "丁"])
            total = len(_rows(path))
            for target, source in ((ids[0], ids[1]), (ids[0], ids[2]), (ids[3], ids[0])):
                ab.apply_absorb(path, [{"target_id": target, "insight": f"并{target}",
                                        "sources": [source]}])
                self.assertEqual(len(_rows(path)), total)


class PlanTests(unittest.TestCase):
    def _plan(self, path: Path, ids: list[str], content: str) -> dict[str, Any]:
        async def fake_chat(*args: Any, **kwargs: Any) -> _Resp:
            return _Resp(content)

        with patch("spiritscout.gateway.gateway.chat_decision", fake_chat):
            return __import__("asyncio").run(
                ab.plan_absorb(object(), path, ids))

    def test_plan_returns_validated_groups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "experience.db"
            ids = _seed(path, ["甲经验讲登录枚举", "乙经验讲上传绕过", "丙经验讲口令喷洒"])
            content = json.dumps({"groups": [{
                "target_id": ids[0], "insight": "登录枚举与口令喷洒都在认证口",
                "context": "认证接口", "sources": [ids[2]]}]}, ensure_ascii=False)
            data = self._plan(path, [ids[2]], content)
            self.assertEqual(data["candidates"], 2, "候选＝库里其它条目")
            self.assertEqual(len(data["groups"]), 1)
            self.assertEqual(data["groups"][0]["target_id"], ids[0])
            self.assertIn("可以并入", data["note"])

    def test_plan_with_no_groups_says_so(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "experience.db"
            ids = _seed(path, ["甲", "乙"])
            data = self._plan(path, [ids[0]], json.dumps({"groups": []}))
            self.assertEqual(data["groups"], [])
            self.assertIn("没有可以并入", data["note"])

    def test_plan_rejects_unparseable_reply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "experience.db"
            ids = _seed(path, ["甲", "乙"])
            with self.assertRaises(SpiritScoutError):
                self._plan(path, [ids[0]], "我觉得这两条挺像的，可以合并")

    def test_plan_when_nothing_else_in_library(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "experience.db"
            ids = _seed(path, ["只有一条"])
            data = self._plan(path, [ids[0]], "{}")
            self.assertEqual(data["groups"], [])
            self.assertEqual(data["candidates"], 0)
            self.assertIn("没有别的经验", data["note"])


if __name__ == "__main__":
    unittest.main()
