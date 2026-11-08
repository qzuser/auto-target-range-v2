"""模型注册表写回前留备份：手滑清空或被异常路径写空时还能捡回来。

2026-11-08 现场：`configs/models.yaml` 被写成了 ``providers: [] / models: []``，
八条渠道全没了，服务起来了却一个模型都调不动（「用量」页因此长年是 0）。
写入前留一份 ``.bak-<时间戳>`` 是最小代价的兜底。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from spiritscout.web import modelcfg

PROVIDERS = [{"name": "local", "provider": "openai_compatible",
              "base_url": "http://127.0.0.1:18923/v1", "api_format": "auto"}]
MODELS = [{"model": "big-pickle", "provider_ref": "local"}]


class WriteConfigBackupTests(unittest.TestCase):
    def test_overwrite_leaves_previous_version_on_disk(self) -> None:
        """第二次写入前，磁盘上要留下一份上一次的完整内容。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "models.yaml"
            modelcfg.write_config(path, PROVIDERS, MODELS)
            original = path.read_text(encoding="utf-8")
            modelcfg.write_config(path, [], [])

            backups = sorted(path.parent.glob("models.yaml.bak-*"))
            self.assertEqual(len(backups), 1, "覆盖时没留备份")
            self.assertEqual(backups[0].read_text(encoding="utf-8"), original)
            # 空清单确实写进去了——备份是兜底，不是拦截
            self.assertIn("models: []", path.read_text(encoding="utf-8"))

    def test_first_write_has_nothing_to_back_up(self) -> None:
        """文件还不存在时不该凭空造出 .bak。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "models.yaml"
            modelcfg.write_config(path, PROVIDERS, MODELS)
            self.assertEqual(list(path.parent.glob("models.yaml.bak-*")), [])


if __name__ == "__main__":
    unittest.main()
