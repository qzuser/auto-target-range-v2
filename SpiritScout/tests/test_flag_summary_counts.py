"""摘要里的 flag 计数必须按提交后的实况覆盖。

真机现场：三题全过（flags.json 三条 accepted、判题器 3/3），但 e2e 摘要写
`extracted: 2 / submitted: 2 / accepted: 2`——最后一枚 flag 落在 master 汇总
与 `submit_all()` 之间的收尾里，摘要沿用旧快照就少算一条，看摘要的人会
以为还有一题没解。
"""
from __future__ import annotations

import unittest

from spiritscout.runtime import _apply_flag_stats


class ApplyFlagStatsTests(unittest.TestCase):
    def test_late_flag_is_counted(self) -> None:
        summary = {"extracted": 2, "submitted": 2, "accepted": 2}
        _apply_flag_stats(summary, {"extracted": 3, "submitted": 3,
                                    "accepted": 3, "rejected": 0})
        self.assertEqual(summary["extracted"], 3)
        self.assertEqual(summary["submitted"], 3)
        self.assertEqual(summary["accepted"], 3)
        self.assertEqual(summary["rejected"], 0)

    def test_other_summary_fields_untouched(self) -> None:
        summary = {"extracted": 1, "rounds_executed": 2, "mode_notes": ["a"]}
        _apply_flag_stats(summary, {"extracted": 1, "submitted": 1})
        self.assertEqual(summary["rounds_executed"], 2)
        self.assertEqual(summary["mode_notes"], ["a"])
        self.assertNotIn("accepted", summary)

    def test_empty_stats_keeps_summary(self) -> None:
        summary = {"extracted": 1, "submitted": 0}
        _apply_flag_stats(summary, {})
        self.assertEqual(summary, {"extracted": 1, "submitted": 0})


if __name__ == "__main__":
    unittest.main()
