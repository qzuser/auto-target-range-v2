"""附件分析要给源码正文：只给 magic 和零散字符串，模型拿不到算法只能瞎猜。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from spiritscout.tools.builtin import _text_excerpt, file_analyze


class TextExcerptTests(unittest.TestCase):
    def test_source_file_yields_excerpt(self) -> None:
        code = "int main(void) {\n  return 0;\n}\n" * 40
        excerpt, text_like = _text_excerpt(code.encode("utf-8"), 0)
        self.assertTrue(text_like)
        self.assertIn("int main(void)", excerpt)
        self.assertTrue(excerpt.startswith("int main"))

    def test_binary_is_refused(self) -> None:
        excerpt, text_like = _text_excerpt(b"\x7fELF\x00\x01\x02" + b"\xff" * 100, 0)
        self.assertFalse(text_like)
        self.assertEqual(excerpt, "")

    def test_truncation_keeps_whole_lines_and_marks_it(self) -> None:
        text = "\n".join(f"line {i} " + "x" * 40 for i in range(400))
        excerpt, text_like = _text_excerpt(text.encode("utf-8"), 500)
        self.assertTrue(text_like)
        self.assertLessEqual(len(excerpt), 560)
        self.assertIn("截断", excerpt)
        self.assertTrue(excerpt.startswith("line 0 "))

    def test_chinese_source_is_text_like(self) -> None:
        excerpt, text_like = _text_excerpt("中文注释\n密钥在这里\n".encode(), 0)
        self.assertTrue(text_like)
        self.assertIn("中文注释", excerpt)


class FileAnalyzeExcerptTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    async def test_source_attachment_carries_content(self) -> None:
        source = self.root / "base64.c"
        source.write_text('unsigned char t[4] = "ab+/";\nint main(void){return 0;}\n',
                          encoding="utf-8")
        result = await file_analyze(str(source), allowed_dirs=[str(self.root)])
        self.assertTrue(result.ok)
        self.assertTrue(result.parsed["text_like"])
        self.assertIn("unsigned char t[4]", result.parsed["text_excerpt"])
        self.assertEqual(result.parsed["line_count"], 2)

    async def test_binary_attachment_has_no_excerpt(self) -> None:
        blob = self.root / "fw.bin"
        blob.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(range(256)))
        result = await file_analyze(str(blob), allowed_dirs=[str(self.root)])
        self.assertTrue(result.ok)
        self.assertFalse(result.parsed["text_like"])
        self.assertEqual(result.parsed["text_excerpt"], "")


if __name__ == '__main__':
    unittest.main()
