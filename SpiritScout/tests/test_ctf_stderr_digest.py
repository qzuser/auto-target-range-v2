"""stderr 摘要提炼：报错要点必须出现在回灌文本第一屏，小模型才会改代码。"""
from __future__ import annotations

import unittest

from spiritscout.ctf.agents import _stderr_digest

INDEX_CASE = """Traceback (most recent call last):
  File "C:\\ws\\run_1.py", line 17, in <module>
    base64_right[i + 1] = base64_3[k]
                          ~~~~~~~~^^^
IndexError: string index out of range
"""

NESTED_CASE = """Traceback (most recent call last):
  File "run.py", line 3, in <module>
    a = 1 / 0
ZeroDivisionError: division by zero
"""

CHAIN_CASE = """Traceback (most recent call last):
  File "run.py", line 5, in <module>
    main()
  File "run.py", line 2, in main
    return int("x")
ValueError: invalid literal for int() with base 10: 'x'
"""


class StderrDigestTests(unittest.TestCase):
    def test_extracts_error_type_message_and_source_line(self) -> None:
        digest = _stderr_digest(INDEX_CASE)
        self.assertIn("报错要点：", digest)
        self.assertIn("IndexError: string index out of range", digest)
        self.assertIn("第 17 行", digest)
        self.assertIn("base64_right[i + 1] = base64_3[k]", digest)

    def test_uses_the_last_traceback_in_mixed_output(self) -> None:
        noisy = "前一次运行的输出\n" + INDEX_CASE + "中间夹了日志\n" + NESTED_CASE
        digest = _stderr_digest(noisy)
        self.assertIn("ZeroDivisionError", digest)
        self.assertIn("第 3 行", digest)

    def test_picks_the_innermost_frame_line(self) -> None:
        digest = _stderr_digest(CHAIN_CASE)
        self.assertIn("ValueError: invalid literal", digest)
        self.assertIn('return int("x")', digest)

    def test_stderr_without_traceback_yields_empty(self) -> None:
        self.assertEqual(_stderr_digest("warning: deprecated\n"), "")
        self.assertEqual(_stderr_digest(""), "")

    def test_traceback_without_source_line_still_names_the_error(self) -> None:
        bare = "Traceback (most recent call last):\nMemoryError\n"
        digest = _stderr_digest(bare)
        self.assertIn("MemoryError", digest)


if __name__ == "__main__":
    unittest.main()
