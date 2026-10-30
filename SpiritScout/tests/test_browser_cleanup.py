"""浏览器临时档案清理的契约：够大才清、只清 tmp、清完报实数。

这里的重点是**边界**——清错目录会把截图和下载一起删掉，所以「只动 tmp」
要单独钉住；阈值存在的意义是别每次退出都去遍历几千个文件，所以「没到就
一个字节都不动」也要钉住。
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from spiritscout.tools.browser_cleanup import (
    DEFAULT_THRESHOLD_MB,
    prune_browser_tmp,
    threshold_mb,
)


class ThresholdTests(unittest.TestCase):
    def test_default_when_nothing_is_configured(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SPIRITSCOUT_BROWSER_TMP_PRUNE_MB", None)
            self.assertEqual(threshold_mb(), DEFAULT_THRESHOLD_MB)

    def test_explicit_wins_over_environment(self) -> None:
        with patch.dict(os.environ, {"SPIRITSCOUT_BROWSER_TMP_PRUNE_MB": "8"}):
            self.assertEqual(threshold_mb(64), 64)

    def test_environment_overrides_default(self) -> None:
        with patch.dict(os.environ, {"SPIRITSCOUT_BROWSER_TMP_PRUNE_MB": "8"}):
            self.assertEqual(threshold_mb(), 8)

    def test_garbage_value_falls_back_instead_of_raising(self) -> None:
        """配置写错了不该让会话收尾炸掉——退回默认值继续走。"""
        with patch.dict(os.environ, {"SPIRITSCOUT_BROWSER_TMP_PRUNE_MB": "不是数字"}):
            self.assertEqual(threshold_mb(), DEFAULT_THRESHOLD_MB)

    def test_negative_is_clamped_to_zero(self) -> None:
        self.assertEqual(threshold_mb(-5), 0)


class PruneTests(unittest.TestCase):
    def _profile(self, root: Path, name: str, size: int) -> Path:
        """造一份像样的 Chromium 档案：目录里套一个 4 MB 级的缓存文件。"""
        profile = root / "tmp" / name
        (profile / "GrShaderCache").mkdir(parents=True)
        (profile / "GrShaderCache" / "data_3").write_bytes(b"x" * size)
        return profile

    def test_missing_tmp_is_a_noop(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(prune_browser_tmp(Path(temporary)), 0)

    def test_empty_tmp_is_a_noop(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            (Path(temporary) / "tmp").mkdir()
            self.assertEqual(prune_browser_tmp(Path(temporary)), 0)

    def test_below_threshold_keeps_everything(self) -> None:
        """单份档案留着不碍事，别每次退出都去遍历一遍。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = self._profile(root, "playwright_chromiumdev_profile-aaa", 1000)
            self.assertEqual(prune_browser_tmp(root, threshold=1), 0)
            self.assertTrue(profile.exists(), "没到阈值不该动手")

    def test_above_threshold_removes_profiles_and_reports_freed_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = self._profile(root, "playwright_chromiumdev_profile-aaa", 700_000)
            second = self._profile(root, "playwright_chromiumdev_profile-bbb", 700_000)
            self.assertGreaterEqual(prune_browser_tmp(root, threshold=1), 1_400_000,
                                    "报的应是实际释放量")
            self.assertFalse(first.exists())
            self.assertFalse(second.exists())
            self.assertTrue((root / "tmp").is_dir(), "tmp 目录本身留着，Playwright 还要用")

    def test_artifacts_next_to_tmp_are_untouched(self) -> None:
        """同级是截图、console 日志和下载——那些是产物，清错了就丢东西。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = self._profile(root, "playwright_chromiumdev_profile-aaa", 1_500_000)
            console = root / "console-2026-10-29T11-47-37-991Z.log"
            shot = root / "screenshot.png"
            console.write_text("日志", encoding="utf-8")
            shot.write_bytes(b"png")
            self.assertGreater(prune_browser_tmp(root, threshold=1), 0)
            self.assertFalse(profile.exists(), "临时档案该走")
            self.assertTrue(console.exists(), "console 日志不能被清")
            self.assertTrue(shot.exists(), "截图不能被清")

    def test_stray_files_inside_tmp_are_cleaned_too(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "tmp").mkdir()
            (root / "tmp" / "loose.tmp").write_bytes(b"y" * 1_500_000)
            self.assertGreater(prune_browser_tmp(root, threshold=1), 0)
            self.assertFalse((root / "tmp" / "loose.tmp").exists())

    def test_zero_threshold_always_cleans(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = self._profile(root, "playwright_chromiumdev_profile-aaa", 10)
            self.assertGreater(prune_browser_tmp(root, threshold=0), 0)
            self.assertFalse(profile.exists())

    def test_twice_is_idempotent(self) -> None:
        """第二次没有东西可清，要老实返回 0 而不是编个数字。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._profile(root, "playwright_chromiumdev_profile-aaa", 1_500_000)
            self.assertGreater(prune_browser_tmp(root, threshold=1), 0)
            self.assertEqual(prune_browser_tmp(root, threshold=1), 0)


if __name__ == "__main__":
    unittest.main()
