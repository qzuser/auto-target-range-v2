"""回灌管线：把脱敏快照写回运行库。

运行期经验库（``SpiritScout/.spiritscout/experience.db``）在 .gitignore 里，
仓库里只有脱敏快照 ``experience-export/experience-insights.json``。换机器、
重建工作区、库被清空之后，两份数据就会脱节——快照有 173 条、库里 0 条，
「经验库」页自然是空的。``--import`` 负责把留档灌回去，这组测试盯住它的判重口径。
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPORTER = REPO_ROOT / "experience-export" / "export_experience.py"


def _load_exporter() -> ModuleType:
    """按路径加载导出脚本——它不属于安装包，只能动态导入。"""
    spec = importlib.util.spec_from_file_location("experience_export_cli", EXPORTER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _snapshot(entries: list[dict[str, object]]) -> dict[str, object]:
    """拼一份最小快照：字段口径与真实留档一致。"""
    return {
        "schema": 1,
        "kind": "spiritscout-experience-insights",
        "generated_at": "2026-11-01T00:00:00+00:00",
        "source": "test",
        "redaction": [],
        "total": len(entries),
        "tag_frequency": {},
        "insights": entries,
    }


class ImportSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_exporter()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / "experience.db"
        self.out = self.root / "experience-insights.json"
        self.entries: list[dict[str, object]] = [
            {
                "id": "exp-000000000001",
                "insight": "退出码 0 只说明命令被执行，不能证明过滤绕过生效。",
                "context": "Web 命令注入",
                "tags": ["ctf", "web"],
                "source_model": "master",
                "captured_at": "2026-10-29T00:42:51+00:00",
            },
            {
                "id": "exp-000000000002",
                "insight": "flag 被提取与被平台接受是两个独立信号。",
                "context": "判读",
                "tags": ["flag", "判读"],
                "source_model": "master",
                "captured_at": "2026-11-01T12:15:28+00:00",
            },
        ]

    def _write_snapshot(self, entries: list[dict[str, object]] | None = None) -> None:
        self.out.write_text(
            json.dumps(_snapshot(self.entries if entries is None else entries),
                       ensure_ascii=False),
            encoding="utf-8",
        )

    def _rows(self) -> list[tuple[str, str, float]]:
        conn = sqlite3.connect(str(self.db))
        try:
            return [(str(r[0]), str(r[1]), float(r[2])) for r in conn.execute(
                "SELECT insight_id, insight, ts FROM insights ORDER BY ts")]
        finally:
            conn.close()

    def test_import_fills_empty_database_and_keeps_captured_at(self) -> None:
        """空库回灌：条数对得上，原始 captured_at 转成 ts 保留（时间线不乱）。"""
        self._write_snapshot()
        self.assertEqual(self.module.import_snapshot(self.db, self.out), 0)

        rows = self._rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][0], "exp-000000000001")
        # 按 ISO 比而不是硬编码 epoch：时间戳只要被写歪就能看出来
        self.assertEqual(
            datetime.fromtimestamp(rows[0][2], tz=UTC).isoformat(),
            "2026-10-29T00:42:51+00:00")

    def test_import_is_idempotent(self) -> None:
        """重复回灌不该长出新条目——哈希钩子和手动同步会各跑一次。"""
        self._write_snapshot()
        self.module.import_snapshot(self.db, self.out)
        self.module.import_snapshot(self.db, self.out)
        self.assertEqual(len(self._rows()), 2)

    def test_import_keeps_rows_already_in_database(self) -> None:
        """库里有快照没有的条目（新会话刚沉淀的）必须原样留着：只增不减。"""
        self._write_snapshot()
        self.module.import_snapshot(self.db, self.out)

        conn = sqlite3.connect(str(self.db))
        try:
            conn.execute(
                "INSERT INTO insights (insight_id, insight, context, tags,"
                " source_session, source_model, ts) VALUES (?,?,?,?,?,?,?)",
                ("exp-live", "本机新跑出来的经验。", "", "[]", "", "master", 1800000000.0))
            conn.commit()
        finally:
            conn.close()

        self.module.import_snapshot(self.db, self.out)
        ids = {row[0] for row in self._rows()}
        self.assertEqual(ids, {"exp-000000000001", "exp-000000000002", "exp-live"})

    def test_same_text_under_another_id_is_skipped(self) -> None:
        """同一句话换了 id 也不该进第二行——判重同时看原文。"""
        self._write_snapshot([self.entries[0]])
        self.module.import_snapshot(self.db, self.out)

        clone = dict(self.entries[0])
        clone["id"] = "exp-000000000099"
        self._write_snapshot([clone])
        self.module.import_snapshot(self.db, self.out)
        self.assertEqual(len(self._rows()), 1)

    def test_dry_run_reports_without_writing(self) -> None:
        """预演只报数，库文件都不该被建出来。"""
        self._write_snapshot()
        self.assertEqual(
            self.module.import_snapshot(self.db, self.out, dry_run=True), 0)
        self.assertFalse(self.db.exists())


if __name__ == "__main__":
    unittest.main()
