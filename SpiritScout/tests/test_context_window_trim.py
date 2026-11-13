"""小窗口模型的上下文收口：先多级节选，压不下去再整组丢最旧的工具往返。

16k 窗口跑到第 44 回合时，输入估算仍超过窗口，端点直接 400，整条路线以
「主备均不可用」收尾——这类失败不是模型不会解题，是上下文管理没兜住。
"""
from __future__ import annotations

import unittest

from spiritscout.gateway.context import (
    compact_history_tokens,
    estimate_input_tokens,
    shrink_history_to_window,
)

LIMIT_RATIO = 0.88  # 与 shrink_history_to_window 里的余量一致


def _history(turns: int, body: str = "观察" * 150) -> list[dict]:
    messages: list[dict] = [
        {"role": "system", "content": "系统契约"},
        {"role": "user", "content": "任务现场"},
    ]
    for index in range(turns):
        messages.append({"role": "assistant", "content": "",
                         "tool_calls": [{"id": f"c{index}", "type": "function",
                                         "function": {"name": "shell",
                                                      "arguments": '{"command": "ls"}'}}]})
        messages.append({"role": "tool", "tool_call_id": f"c{index}", "content": body})
    return messages


class CompactEscalationTests(unittest.TestCase):
    def test_many_observations_are_reduced_substantially(self) -> None:
        messages = _history(30, body="x" * 500)
        before = estimate_input_tokens(messages)
        compact_history_tokens(messages, 3000)
        after = estimate_input_tokens(messages)
        self.assertLess(after, before * 0.65, "几十条观察节选后应明显变小")

    def test_long_bodies_are_collapsed(self) -> None:
        messages = _history(6, body="y" * 4000)
        compact_history_tokens(messages, 2000)
        # 最后一次工具往返保持完整（模型正在用它），只检查更早的观察被折叠
        bodies = [m["content"] for m in messages[:-1] if m.get("role") == "tool"]
        self.assertTrue(all(len(body) < 1500 for body in bodies),
                        f"早期观察应被折叠: {[len(b) for b in bodies]}")
        self.assertLess(estimate_input_tokens(messages), 4000)

    def test_old_tool_arguments_are_folded_last_resort(self) -> None:
        messages = _history(40, body="短")
        compact_history_tokens(messages, 1200)
        old_calls = [call for m in messages if m.get("tool_calls")
                     for call in m["tool_calls"]]
        self.assertTrue(old_calls, "历史里应有工具调用")
        self.assertTrue(any(call["function"]["arguments"] == "{}" for call in old_calls),
                        "压不下去时应折叠旧参数")

    def test_short_history_is_left_alone(self) -> None:
        messages = _history(1, body="短")
        snapshot = [dict(m) for m in messages]
        self.assertFalse(compact_history_tokens(messages, 100000))
        self.assertEqual(messages, snapshot)


class ShrinkHistoryTests(unittest.TestCase):
    def test_compaction_plus_shrink_fits_the_window(self) -> None:
        messages = _history(60, body="z" * 800)
        window, reserve = 8192, 1024
        compact_history_tokens(messages, int(window * 0.8), tools=None)
        dropped = shrink_history_to_window(messages, window, reserve=reserve)
        limit = int((window - reserve) * LIMIT_RATIO)
        self.assertGreater(dropped, 0, "超窗时必须真的丢旧往返")
        self.assertLessEqual(estimate_input_tokens(messages), limit,
                             "两层收口后必须真的落进窗口")

    def test_drops_keep_head_and_recent_tail(self) -> None:
        messages = _history(30, body="z" * 800)
        before = estimate_input_tokens(messages)
        shrink_history_to_window(messages, 6000, reserve=1024)
        self.assertLess(estimate_input_tokens(messages), before)
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1]["role"], "user")
        self.assertGreaterEqual(len(messages), 6)

    def test_tool_pair_is_removed_together(self) -> None:
        messages = _history(20, body="w" * 800)
        shrink_history_to_window(messages, 5000, reserve=1024)
        for index, message in enumerate(messages):
            if message.get("role") == "tool":
                self.assertEqual(messages[index - 1].get("role"), "assistant",
                                 "不能留下没有 assistant 的孤儿 tool 消息")
            if message.get("role") == "assistant" and message.get("tool_calls"):
                self.assertEqual(messages[index + 1].get("role"), "tool",
                                 "带工具调用的 assistant 也要成对")

    def test_reserve_larger_than_window_does_not_wipe_history(self) -> None:
        """档案里输出上限比窗口还大时，不能把预留当成整窗，历史不许被削光。"""
        messages = _history(20, body="x" * 3000)
        dropped = shrink_history_to_window(messages, 100000, reserve=131072)
        self.assertEqual(dropped, 0, "窗口够用时不该动历史")
        self.assertEqual(len(messages), 42)

    def test_within_window_is_untouched(self) -> None:
        messages = _history(3, body="短")
        snapshot = [dict(m) for m in messages]
        self.assertEqual(shrink_history_to_window(messages, 100000), 0)
        self.assertEqual(messages, snapshot)


if __name__ == '__main__':
    unittest.main()
