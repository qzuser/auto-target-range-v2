"""`process_budget` 的契约：机器快时保持原预算，机器慢时按实测放大。

这个模块本身是测试基础设施，但它决定了那几个进程树用例到底在测「收口」还是
在测「启动速度」，所以边界值得单独钉住。用 patch 改基线，不依赖本机真实快慢。
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

try:                              # discover 把 tests/ 直接挂在 sys.path 上
    from tests import process_budget
except ImportError:               # 直接跑 `-m unittest test_process_budget` 时
    import process_budget


class BudgetTests(unittest.TestCase):
    def test_fast_machine_keeps_the_original_short_budget(self) -> None:
        """0.05 秒的启动不该让 0.7 秒的意图被放宽——测试强度原样保留。"""
        with patch.object(process_budget, "spawn_seconds", return_value=0.05):
            self.assertEqual(process_budget.budget(0.7), 0.7)
            self.assertEqual(process_budget.budget(2, 3), 2)
            self.assertEqual(process_budget.budget(3, 3), 3)

    def test_slow_machine_widens_to_the_measured_spawn_cost(self) -> None:
        """机器被占满（启动 4 秒）时按倍数放宽，否则「还没起来」会被当成「挂死」。"""
        with patch.object(process_budget, "spawn_seconds", return_value=4.0):
            self.assertAlmostEqual(process_budget.budget(0.7), 8.0)
            self.assertAlmostEqual(process_budget.budget(2, 3), 12.0)
            self.assertAlmostEqual(process_budget.budget(3, 3), 12.0)

    def test_factor_never_shrinks_below_base(self) -> None:
        with patch.object(process_budget, "spawn_seconds", return_value=0.0):
            self.assertEqual(process_budget.budget(3, 3), 3)

    def test_spawn_seconds_is_cached(self) -> None:
        """基线只量一次：每个用例重复付几百毫秒，全量会白等十几秒。"""
        process_budget.spawn_seconds.cache_clear()
        with patch.object(process_budget.subprocess, "run") as run:
            run.return_value = None
            first = process_budget.spawn_seconds()
            second = process_budget.spawn_seconds()
        self.assertEqual(run.call_count, 3, "默认采三次取中位数")
        self.assertEqual(first, second, "第二次命中缓存，不重新采样")
        process_budget.spawn_seconds.cache_clear()


class ReapWindowTests(unittest.TestCase):
    """观察窗口要盖住后代「启动 + 自己的 sleep」，否则慢机器上会假通过。

    这几个用例断言的是「后代已被收口，所以不该有写入」。窗口贴着后代的
    sleep 走（历史上是 sleep(.6) 对 time.sleep(.5)，只留 0.1 秒）时，机器一忙
    后代还没轮到写，测试就绿了——而其实什么都没验证到。
    """

    def test_fast_machine_window_covers_child_sleep_plus_margin(self) -> None:
        with patch.object(process_budget, "spawn_seconds", return_value=0.056):
            self.assertAlmostEqual(process_budget.reap_window(0.5), 0.884)
            self.assertGreater(process_budget.reap_window(0.5), 0.5, "至少得等过后代自己的 sleep")

    def test_slow_machine_window_widens_with_spawn_cost(self) -> None:
        with patch.object(process_budget, "spawn_seconds", return_value=4.0):
            self.assertAlmostEqual(process_budget.reap_window(0.5), 6.8)
            self.assertAlmostEqual(process_budget.reap_window(2.0), 8.3)

    def test_window_never_ends_before_child_sleep(self) -> None:
        with patch.object(process_budget, "spawn_seconds", return_value=0.0):
            self.assertGreater(process_budget.reap_window(0.4), 0.4)


if __name__ == "__main__":
    unittest.main()
