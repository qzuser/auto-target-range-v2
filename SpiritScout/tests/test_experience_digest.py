"""经验摘要（`knowledge/digest.py`）的测试：随包发布的 SUMMARY 得真的能读、能解析。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from spiritscout.knowledge import digest
from spiritscout.knowledge.sync import FORMAT, read_export


def _payload(count: int = 3) -> dict:
    items = []
    for index in range(count):
        items.append({
            "insight_id": f"exp-{index}",
            "insight": f"第 {index} 条经验：退出码为 0 不代表绕过成功。",
            "context": f"场景 {index}",
            "tags": ["ctf", "web"] if index % 2 == 0 else ["crypto"],
            "source_model": "master",
            "ts": 1762310400 + index,
        })
    return {"format": FORMAT, "exported_at": 1762310400, "count": len(items), "items": items}


class DigestMarkdownTests(unittest.TestCase):
    def test_header_reports_total_and_limit(self):
        text = digest.digest_markdown(_payload(5), limit=3)
        self.assertIn("共 **5 条**", text)
        self.assertIn("最近 3 条", text)
        self.assertIn("其余 2 条", text)

    def test_tag_table_sorted_by_count_then_name(self):
        payload = _payload(4)
        for item in payload["items"]:
            item["tags"] = ["ctf"]
        payload["items"][0]["tags"] = ["ctf", "web"]
        text = digest.digest_markdown(payload)
        self.assertIn("| `ctf` | 4 |", text)
        self.assertIn("| `web` | 1 |", text)
        # 条数多的在前
        self.assertLess(text.index("`ctf` | 4"), text.index("`web` | 1"))
        # 同数按字母序（crypto < ctf）
        tie = digest.digest_markdown(_payload(4))
        self.assertIn("| `crypto` | 2 |", tie)
        self.assertLess(tie.index("`crypto`"), tie.index("`ctf`"))

    def test_entries_carry_context_tags_and_model(self):
        text = digest.digest_markdown(_payload(2))
        self.assertIn("### 1. 第 0 条经验", text)
        self.assertIn("- 场景：场景 0", text)
        self.assertIn("- 标签：ctf · web", text)
        self.assertIn("来源模型 `master`", text)

    def test_empty_payload_is_still_readable(self):
        text = digest.digest_markdown({"format": FORMAT, "count": 0, "items": []})
        self.assertIn("共 **0 条**", text)
        self.assertIn("还没有标签", text)

    def test_inbox_note_only_when_files_exist(self):
        self.assertNotIn("投稿", digest.digest_markdown(_payload(1)))
        self.assertIn("投稿 2 份", digest.digest_markdown(_payload(1), inbox_files=2))

    def test_long_insight_is_truncated(self):
        payload = _payload(1)
        payload["items"][0]["insight"] = "很长的经验" * 60
        text = digest.digest_markdown(payload)
        heading = [line for line in text.splitlines() if line.startswith("### 1.")][0]
        self.assertLess(len(heading), 140)
        self.assertIn("…", heading)


class DigestBundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.package = self.repo / "SpiritScout"
        (self.package / "src" / "spiritscout" / "knowledge" / "data").mkdir(parents=True)
        (self.package / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
        export = self.repo / "experience-export"
        (export / "inbox").mkdir(parents=True)
        (export / "experience-insights.json").write_text(
            json.dumps(_payload(4), ensure_ascii=False), encoding="utf-8")
        (export / "inbox" / "a.json").write_text(
            json.dumps(_payload(1), ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_writes_four_files_and_json_round_trips(self):
        written = digest.write_bundle(self.repo, self.package, limit=2)
        self.assertEqual(set(written), {"repo", "package", "json", "md"})
        for path in written.values():
            self.assertTrue(path.is_file(), path)
        self.assertIn("投稿 1 份", written["repo"].read_text(encoding="utf-8"))
        self.assertIn("其余 2 条", written["package"].read_text(encoding="utf-8"))
        reloaded = read_export(written["json"])
        self.assertEqual(len(reloaded["items"]), 4)

    def test_missing_snapshot_still_writes_markdown(self):
        (self.repo / "experience-export" / "experience-insights.json").unlink()
        written = digest.write_bundle(self.repo, self.package)
        self.assertIn("repo", written)
        self.assertNotIn("json", written)
        self.assertIn("共 **0 条**", written["repo"].read_text(encoding="utf-8"))

    def test_legacy_repo_format_is_understood(self):
        legacy = {
            "schema": 1,
            "kind": "spiritscout-experience-insights",
            "generated_at": "2026-11-10T10:46:26+00:00",
            "total": 1,
            "tag_frequency": {"web": 1},
            "insights": [{
                "id": "exp-old", "insight": "老清单里的经验", "context": "Web",
                "tags": ["web"], "source_model": "master",
                "captured_at": "2026-10-29T00:42:51+00:00",
            }],
        }
        (self.repo / "experience-export" / "experience-insights.json").write_text(
            json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
        written = digest.write_bundle(self.repo, self.package)
        text = written["repo"].read_text(encoding="utf-8")
        self.assertIn("共 **1 条**", text)
        self.assertIn("老清单里的经验", text)
        self.assertIn("`web`", text)


class DigestCliTests(unittest.TestCase):
    def test_rejects_directory_without_pyproject(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(digest.main(["--repo", tmp, "--package", tmp]), 2)

    def test_writes_into_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            package = repo / "pkg"
            (package / "src" / "spiritscout" / "knowledge" / "data").mkdir(parents=True)
            (package / "pyproject.toml").write_text("", encoding="utf-8")
            self.assertEqual(digest.main(["--repo", tmp, "--package", str(package)]), 0)
            self.assertTrue((repo / digest.DIGEST_NAME).is_file())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
