# -*- coding: utf-8 -*-
"""多行 Python 硬塞进 shell 的 python -c：要在执行前拦下来并说明原因。

现场（Qwen2.5-Coder-7B，西湖论剑 2021 IoT base64）：模型把整段循环塞进
``python -c "..."``，换行和引号被 shell 吃掉，退出码 2 / SyntaxError，
它据此判断「算法写错了」，转头回去重读源码。真正的问题是调用方式。
"""
from __future__ import annotations

import unittest

from spiritscout.ctf.agents import _inline_multiline_python


class InlineMultilinePythonTests(unittest.TestCase):
    def test_single_line_python_is_allowed(self) -> None:
        self.assertFalse(_inline_multiline_python('python -c "print(1+1)"'))
        self.assertFalse(_inline_multiline_python('python3 -c "import os; print(1)"'))

    def test_literal_newline_escape_is_rejected(self) -> None:
        self.assertTrue(_inline_multiline_python(r'python -c "a=1\nprint(a)"'))

    def test_real_newline_is_rejected(self) -> None:
        self.assertTrue(_inline_multiline_python('python -c "a=1\nprint(a)"'))

    def test_unbalanced_quotes_are_rejected(self) -> None:
        self.assertTrue(_inline_multiline_python('python -c "base64_right = ["" for _ in range(65)]'))

    def test_other_shell_commands_are_untouched(self) -> None:
        self.assertFalse(_inline_multiline_python("cat attachments/base64.c"))
        self.assertFalse(_inline_multiline_python("grep -n 'for (' attachments/base64.c"))
        self.assertFalse(_inline_multiline_python(""))


if __name__ == "__main__":
    unittest.main()
