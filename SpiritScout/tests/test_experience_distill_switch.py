"""经验提炼开关：关掉后解出 Flag / 收尾都不提炼，经验库原样不动。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from spiritscout.config.settings import ExperienceConfig
from spiritscout.runtime import _distill_allowed
from spiritscout.web.app import _set_yaml_bool


class DistillSwitchTests(unittest.TestCase):
    def test_default_is_on(self) -> None:
        self.assertTrue(ExperienceConfig().distill_enabled)

    def test_can_be_turned_off_in_config(self) -> None:
        self.assertFalse(ExperienceConfig(distill_enabled=False).distill_enabled)

    def test_runtime_reads_the_switch(self) -> None:
        """提炼入口拿到的判定必须跟配置一致；配置缺失时按「开」处理。"""
        on = SimpleNamespace(cfg=SimpleNamespace(experience=ExperienceConfig()))
        off = SimpleNamespace(cfg=SimpleNamespace(experience=ExperienceConfig(distill_enabled=False)))
        bare = SimpleNamespace(cfg=SimpleNamespace(experience=None))
        none_cfg = SimpleNamespace(cfg=None)
        self.assertTrue(_distill_allowed(on))
        self.assertFalse(_distill_allowed(off))
        self.assertTrue(_distill_allowed(bare))
        self.assertTrue(_distill_allowed(none_cfg))


class YamlWriteBackTests(unittest.TestCase):
    SAMPLE = (
        "# 顶部注释\n"
        "model:\n"
        "  temperature: 0.2   # 保留这个注释\n"
        "\n"
        "experience:              # 经验库（跨会话自我进化）\n"
        '  root: ""               # 空=跟随工作区\n'
        "  recall_limit: 6        # 召回条数\n"
        "\n"
        "web:\n"
        "  port: 8010\n"
    )

    def _write(self, text: str) -> Path:
        d = Path(tempfile.mkdtemp())
        p = d / "system.yaml"
        p.write_text(text, encoding="utf-8")
        return p

    def test_appends_key_when_missing(self) -> None:
        p = self._write(self.SAMPLE)
        _set_yaml_bool(p, "experience", "distill_enabled", False)
        body = p.read_text(encoding="utf-8")
        self.assertIn("distill_enabled: false", body)
        self.assertLess(body.index("distill_enabled"), body.index("web:"))

    def test_flips_existing_value_and_keeps_comments(self) -> None:
        p = self._write(self.SAMPLE.replace(
            '  recall_limit: 6        # 召回条数\n',
            '  recall_limit: 6        # 召回条数\n  distill_enabled: true  # 提炼开关\n'))
        before = p.read_text(encoding="utf-8").count("#")
        _set_yaml_bool(p, "experience", "distill_enabled", False)
        body = p.read_text(encoding="utf-8")
        self.assertIn("distill_enabled: false  # 提炼开关", body)
        self.assertEqual(body.count("#"), before, "行尾注释不能在写回时丢")
        self.assertNotIn("distill_enabled: true", body)

    def test_other_sections_untouched(self) -> None:
        p = self._write(self.SAMPLE)
        _set_yaml_bool(p, "experience", "distill_enabled", False)
        body = p.read_text(encoding="utf-8")
        self.assertIn("  temperature: 0.2   # 保留这个注释", body)
        self.assertIn("  port: 8010", body)

    def test_missing_section_is_an_error(self) -> None:
        p = self._write("web:\n  port: 8010\n")
        with self.assertRaises(ValueError):
            _set_yaml_bool(p, "experience", "distill_enabled", False)


if __name__ == "__main__":
    unittest.main()
