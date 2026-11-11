"""参考知识库的数据文件与加载器。

背景：``seed.py`` 原来把 6 万字的 ATT&CK / SRC 原始资料写成内联字面量，
安装到 ``%LOCALAPPDATA%`` 之后整份模块被本机的安全策略按内容删掉（实测导入报
``OSError: Bad file descriptor``，随后文件消失），于是 ``/api/dashboard`` 与
``/api/experience`` 直接 500。现在数据在 ``data/seed.json``、代码只剩加载逻辑，
这些测试守住三件事：

1. 数据还在（表和行数不许悄悄变少）；
2. 数据文件缺失/损坏时返回空表而不是抛异常；
3. ``.py`` 里不许再把那堆资料塞回来（否则那个 bug 会原样复现）。
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

from spiritscout.knowledge import seed as seed_module

PACKAGE = Path(__file__).resolve().parents[1]
KNOWLEDGE = PACKAGE / "src" / "spiritscout" / "knowledge"

#: 数据文件里的行数快照（改数据时一起改这里，改漏了测试会提醒）
EXPECTED_ROWS = {
    "base_assets": 4,
    "base_vuln_standards": 26,
    "base_fp_signatures": 7,
    "base_poc_templates": 4,
    "base_competition_rules": 3,
    "exp_attack_map": 27,
    "exp_redteam_entries": 17,
    "exp_attack_paths": 6,
    "exp_vuln_priority": 26,
    "exp_hunt_templates": 10,
    "exp_report_templates": 9,
}


class SeedDataTests(unittest.TestCase):
    def test_data_file_is_present_and_valid_json(self) -> None:
        path = KNOWLEDGE / "data" / "seed.json"
        self.assertTrue(path.is_file(), "参考数据文件不见了")
        raw = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(sorted(raw), sorted(EXPECTED_ROWS))

    def test_seed_rows_matches_the_snapshot(self) -> None:
        rows = seed_module.seed_rows()
        self.assertEqual({name: len(items) for name, items in rows.items()}, EXPECTED_ROWS)

    def test_rows_keep_the_documented_columns(self) -> None:
        # 每行至少要能说出「哪来的、什么时候核过」，否则知识库就成了无源之说
        rows = seed_module.seed_rows()
        for name in ("base_assets", "exp_attack_map", "exp_vuln_priority"):
            for row in rows[name]:
                self.assertIsInstance(row, dict, name)
                self.assertTrue(row, name)

    def test_missing_data_file_degrades_to_empty_tables(self) -> None:
        ghost = Path(self._tmp()) / "nope.json"
        with mock.patch.object(seed_module, "data_file", return_value=ghost):
            rows = seed_module.seed_rows()
        self.assertEqual(sorted(rows), sorted(EXPECTED_ROWS))
        self.assertTrue(all(items == [] for items in rows.values()))

    def test_corrupt_data_file_degrades_to_empty_tables(self) -> None:
        broken = Path(self._tmp()) / "broken.json"
        broken.write_text("{ 这不是 JSON", encoding="utf-8")
        with mock.patch.object(seed_module, "data_file", return_value=broken):
            rows = seed_module.seed_rows()
        self.assertTrue(all(items == [] for items in rows.values()))

    def test_partial_data_file_fills_the_gaps(self) -> None:
        partial = Path(self._tmp()) / "partial.json"
        partial.write_text(json.dumps({"base_assets": [{"a": 1}]}), encoding="utf-8")
        with mock.patch.object(seed_module, "data_file", return_value=partial):
            rows = seed_module.seed_rows()
        self.assertEqual(rows["base_assets"], [{"a": 1}])
        self.assertEqual(rows["exp_hunt_templates"], [])

    def _tmp(self) -> str:
        import tempfile

        path = tempfile.mkdtemp(prefix="seedtest-")
        self.addCleanup(lambda: __import__("shutil").rmtree(path, ignore_errors=True))
        return path


class SeedModuleShapeTests(unittest.TestCase):
    """代码与数据分家，别再合回去。"""

    def test_seed_module_is_a_thin_loader(self) -> None:
        text = (KNOWLEDGE / "seed.py").read_text(encoding="utf-8")
        self.assertLess(len(text), 6000, "seed.py 又变厚了：把资料搬回 data/seed.json")
        self.assertIn("data_file()", text)
        self.assertNotIn('"TA0043"', text, "技术点又写回代码了")

    def test_data_file_is_smaller_than_a_startup_budget(self) -> None:
        size = (KNOWLEDGE / "data" / "seed.json").stat().st_size
        self.assertLess(size, 400 * 1024, "参考数据不该长成这样，检查是不是误塞了大文件")

    def test_package_data_ships_the_json(self) -> None:
        text = (PACKAGE / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("knowledge/data/*.json", text)

    def test_seed_version_is_lazy(self) -> None:
        # knowledge/__init__ 不许在模块顶层 import seed：那一层挂了会连带
        # 整个包 import 失败（控制台首页就是 500）
        text = (KNOWLEDGE / "__init__.py").read_text(encoding="utf-8")
        headers = [line for line in text.splitlines() if line.startswith(("from ", "import "))]
        self.assertFalse(
            [line for line in headers if "knowledge.seed" in line],
            "顶层又直接 import seed 了",
        )

    def test_accessing_seed_version_after_seed_breaks_raises_import_error(self) -> None:
        import importlib

        import spiritscout.knowledge as knowledge

        saved = sys.modules.get("spiritscout.knowledge.seed")
        try:
            sys.modules["spiritscout.knowledge.seed"] = None  # type: ignore[assignment]
            importlib.reload(knowledge)
            with self.assertRaises(ImportError):
                _ = knowledge.SEED_VERSION
        finally:
            if saved is None:
                sys.modules.pop("spiritscout.knowledge.seed", None)
            else:
                sys.modules["spiritscout.knowledge.seed"] = saved
            importlib.reload(knowledge)

    def test_accessing_unknown_attribute_raises_attribute_error(self) -> None:
        import spiritscout.knowledge as knowledge

        with self.assertRaises(AttributeError):
            _ = knowledge.definitely_not_here


if __name__ == "__main__":
    unittest.main()
