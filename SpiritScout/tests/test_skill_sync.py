"""自定义技能的真源在版本库：同步进资源库、可从 markdown 导入、能反向导出。

技能以前只活在 `catalog.db` 的 `settings` 表里，工作区一重建就连同页面上的
条目一起消失，仓库里没有第二份——所以「重新导入」这一步必须有工具，而且
导入结果要落在一个能提交、能打包的文件上。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from spiritscout.resources import skill_sync


class FakeStore:
    """只用 settings/save 两个接口的替身，版本号语义与 ResourceStore 一致。"""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def settings(self, kind: str) -> list[dict]:
        if kind != "skill":
            return []
        return [{"id": key, "version": row["version"], "data": dict(row["data"])}
                for key, row in sorted(self.rows.items())]

    def save(self, kind: str, key: str, data: dict, expected: int) -> int:
        assert kind == "skill"
        current = self.rows.get(key)
        version = current["version"] if current else 0
        if version != expected:
            raise AssertionError(f"版本不符: {key} 期望 {expected} 实际 {version}")
        self.rows[key] = {"version": version + 1, "data": dict(data)}
        return version + 1


SKILL = {
    "skill_id": "custom-redis-unauth",
    "domain": "web",
    "description": "Redis 未授权写入公钥拿 shell",
    "severity": "high",
    "tools": ["redis-cli", "ssh-keygen"],
    "body": "## 什么时候用\n目标 6379 可直连。",
    "enabled": True,
}


class RoundTripTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "skills.yaml"

    def test_missing_file_reads_empty(self) -> None:
        self.assertEqual(skill_sync.read_skills(self.path), [])

    def test_write_then_read_keeps_fields_and_flattens_lists(self) -> None:
        skill_sync.write_skills(self.path, [SKILL])
        items = skill_sync.read_skills(self.path)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["skill_id"], "custom-redis-unauth")
        # 列表型字段落成字符串，与内置条目形态一致（匹配逻辑按字符串切词）
        self.assertEqual(items[0]["tools"], "[redis-cli, ssh-keygen]")
        self.assertIn("目标 6379", items[0]["body"])


class SyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "skills.yaml"
        self.store = FakeStore()

    def test_sync_adds_then_skips_unchanged(self) -> None:
        skill_sync.write_skills(self.path, [SKILL])
        first = skill_sync.sync_skills(self.store, self.path)
        self.assertEqual((first["added"], first["updated"]), (1, 0))
        second = skill_sync.sync_skills(self.store, self.path)
        self.assertEqual((second["added"], second["updated"], second["unchanged"]), (0, 0, 1))

    def test_sync_updates_changed_entry(self) -> None:
        skill_sync.write_skills(self.path, [SKILL])
        skill_sync.sync_skills(self.store, self.path)
        changed = {**SKILL, "description": "改过的描述"}
        skill_sync.write_skills(self.path, [changed])
        stats = skill_sync.sync_skills(self.store, self.path)
        self.assertEqual((stats["added"], stats["updated"]), (0, 1))
        self.assertEqual(self.store.rows["custom-redis-unauth"]["data"]["description"],
                         "改过的描述")

    def test_sync_does_not_delete_store_entries_missing_from_file(self) -> None:
        """清单里没有的条目留在库里——一次手滑不该把页面上的技能抹掉。"""
        skill_sync.write_skills(self.path, [SKILL])
        skill_sync.sync_skills(self.store, self.path)
        skill_sync.write_skills(self.path, [])
        skill_sync.sync_skills(self.store, self.path)
        self.assertIn("custom-redis-unauth", self.store.rows)

    def test_export_returns_only_custom_entries(self) -> None:
        skill_sync.write_skills(self.path, [SKILL])
        skill_sync.sync_skills(self.store, self.path)
        exported = skill_sync.export_skills(self.store)
        self.assertEqual([i["skill_id"] for i in exported], ["custom-redis-unauth"])


class MarkdownImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.target = self.root / "configs" / "skills.yaml"

    def test_import_reads_frontmatter_and_body(self) -> None:
        skill_dir = self.root / "src-skills" / "web" / "redis-unauth"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "skill_id: custom-redis-unauth\n"
            "domain: web\n"
            "description: Redis 未授权\n"
            "---\n"
            "## 步骤\n1. redis-cli -h TARGET\n",
            encoding="utf-8")
        stats = skill_sync.import_markdown(self.root / "src-skills", self.target)
        self.assertEqual((stats["parsed"], stats["added"]), (1, 1))
        items = skill_sync.read_skills(self.target)
        self.assertEqual(items[0]["skill_id"], "custom-redis-unauth")
        self.assertIn("redis-cli", items[0]["body"])

    def test_id_falls_back_to_parent_directory(self) -> None:
        """没有 frontmatter 时用父目录名当 id（skills/<domain>/<id>/SKILL.md 结构）。"""
        skill_dir = self.root / "in" / "pwn-stack-rop"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("## 用法\n先看保护。", encoding="utf-8")
        skill_sync.import_markdown(skill_dir, self.target)
        self.assertEqual(skill_sync.read_skills(self.target)[0]["skill_id"], "pwn-stack-rop")

    def test_import_merges_with_existing_file(self) -> None:
        skill_sync.write_skills(self.target, [SKILL])
        skill_dir = self.root / "in" / "second"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("---\nskill_id: second-one\n---\n正文", encoding="utf-8")
        skill_sync.import_markdown(skill_dir, self.target)
        ids = {i["skill_id"] for i in skill_sync.read_skills(self.target)}
        self.assertEqual(ids, {"custom-redis-unauth", "second-one"})


if __name__ == "__main__":
    unittest.main()
