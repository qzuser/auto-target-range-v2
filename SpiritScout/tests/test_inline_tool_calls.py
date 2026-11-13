"""正文里的工具调用也要被执行：小模型不按 tool_calls 协议返回是常态。"""
from __future__ import annotations

import unittest

from spiritscout.agents.inline_calls import recover_inline_tool_calls


class RecoverInlineToolCallTests(unittest.TestCase):
    def test_fenced_json_call_is_recovered(self) -> None:
        content = ('我先看看附件。\n```json\n'
                   '{\n  "name": "analyze_attachments",\n  "arguments": {}\n}\n```\n')
        calls = recover_inline_tool_calls(content)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "analyze_attachments")
        self.assertEqual(calls[0]["arguments"], {})
        self.assertTrue(calls[0]["recovered"])

    def test_tagged_call_is_recovered(self) -> None:
        calls = recover_inline_tool_calls(
            '<tool_call>{"name": "shell", "arguments": {"command": "ls", "action": "analysis"}}'
            '</tool_call>')
        self.assertEqual([c["name"] for c in calls], ["shell"])
        self.assertEqual(calls[0]["arguments"]["command"], "ls")

    def test_bare_json_with_string_arguments(self) -> None:
        calls = recover_inline_tool_calls(
            '{"name": "python", "arguments": "{\\"code\\": \\"print(1)\\"}"}')
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["arguments"], {"code": "print(1)"})

    def test_openai_style_function_wrapper(self) -> None:
        calls = recover_inline_tool_calls(
            '{"function": {"name": "submit_flag", "arguments": {"flag": "flag{x}"}}}')
        self.assertEqual(calls[0]["name"], "submit_flag")
        self.assertEqual(calls[0]["arguments"]["flag"], "flag{x}")

    def test_plain_conclusion_is_not_a_tool_call(self) -> None:
        self.assertEqual(recover_inline_tool_calls("解出来了：flag{demo_value}"), [])
        self.assertEqual(recover_inline_tool_calls('{"result": "ok"}'), [])
        self.assertEqual(recover_inline_tool_calls(""), [])

    def test_json_with_name_but_no_arguments_key_still_counts(self) -> None:
        calls = recover_inline_tool_calls('{"name": "analyze_attachments"}')
        self.assertEqual([c["name"] for c in calls], ["analyze_attachments"])
        self.assertEqual(calls[0]["arguments"], {})

    def test_nested_arguments_are_not_cut_at_first_brace(self) -> None:
        """arguments 里带数组和嵌套对象时，非贪婪匹配会在第一个 } 处截断成半截 JSON。

        本机实测 ask_user 的调用就长这样，被整条漏掉后路线直接收尾——10 个任务
        全部「没有工具调用」，一步没走。
        """
        content = (
            '```json\n{\n  "name": "ask_user",\n  "arguments": {\n'
            '    "question": "确认附件与解题方向？",\n'
            '    "options": ["确认无误，开始解题", "先看固件二进制"]\n  }\n}\n```')
        calls = recover_inline_tool_calls(content)
        self.assertEqual([c["name"] for c in calls], ["ask_user"])
        self.assertEqual(calls[0]["arguments"]["options"],
                         ["确认无误，开始解题", "先看固件二进制"])

    def test_two_fenced_calls_in_one_reply(self) -> None:
        content = ('先读材料：\n```json\n{"name": "shell", "arguments": {"command": "cat attachments/a.c"}}\n```\n'
                   '再跑脚本：\n```json\n{"name": "python", "arguments": {"code": "print(1)"}}\n```')
        calls = recover_inline_tool_calls(content)
        self.assertEqual([c["name"] for c in calls], ["shell", "python"])

    def test_truncated_fence_is_repaired(self) -> None:
        """输出额度用完时连 ``` 都没闭上，能补的括号就补，补不出就放弃。"""
        content = '```json\n{"name": "shell", "arguments": {"command": "ls", "action": "analysis"'
        calls = recover_inline_tool_calls(content)
        self.assertEqual([c["name"] for c in calls], ["shell"])
        self.assertEqual(calls[0]["arguments"]["command"], "ls")

    def test_truncated_inside_string_is_dropped(self) -> None:
        content = '```json\n{"name": "shell", "arguments": {"command": "cat atta'
        self.assertEqual(recover_inline_tool_calls(content), [])

    def test_python_style_fence_with_prose_is_ignored(self) -> None:
        content = '说明：\n```python\nprint("hello")\n```\n结论：还没有结果。'
        self.assertEqual(recover_inline_tool_calls(content), [])


if __name__ == '__main__':
    unittest.main()
