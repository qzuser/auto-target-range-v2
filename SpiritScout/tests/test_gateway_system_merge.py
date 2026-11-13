"""非首位 system 消息并入第一条：LM Studio 的 Qwen 模板强制 system 只能在开头。"""
from __future__ import annotations

import unittest

from spiritscout.gateway.backends import _merge_stray_system_messages


class MergeStraySystemMessagesTests(unittest.TestCase):
    def test_materials_block_is_merged_into_first_system(self) -> None:
        """求解器把常驻材料块作为第二条 system 插进消息列表，必须并进主 system。"""
        messages = [
            {"role": "system", "content": "主 system"},
            {"role": "system", "content": "【题目材料】附件 base64.c……"},
            {"role": "user", "content": "开始分析"},
        ]
        _merge_stray_system_messages(messages)
        self.assertEqual([m["role"] for m in messages], ["system", "user"])
        self.assertIn("【题目材料】", messages[0]["content"])
        self.assertTrue(messages[0]["content"].startswith("主 system"))

    def test_no_system_leaves_everything_alone(self) -> None:
        messages = [{"role": "user", "content": "hi"},
                    {"role": "system", "content": "孤儿 system"}]
        _merge_stray_system_messages(messages)
        # 没有第一条 system 可并：保持原样，交给上层（聊天模板自己报错也语义清楚）
        self.assertEqual(len(messages), 2)

    def test_alternation_is_untouched(self) -> None:
        messages = [
            {"role": "system", "content": "主"},
            {"role": "user", "content": "一"},
            {"role": "assistant", "content": "答"},
            {"role": "user", "content": "二"},
        ]
        snapshot = [dict(m) for m in messages]
        _merge_stray_system_messages(messages)
        self.assertEqual(messages, snapshot)

    def test_empty_stray_system_is_dropped_not_merged(self) -> None:
        messages = [
            {"role": "system", "content": "主"},
            {"role": "system", "content": ""},
            {"role": "user", "content": "开始"},
        ]
        _merge_stray_system_messages(messages)
        self.assertEqual([m["role"] for m in messages], ["system", "user"])
        self.assertEqual(messages[0]["content"], "主")


if __name__ == "__main__":
    unittest.main()
