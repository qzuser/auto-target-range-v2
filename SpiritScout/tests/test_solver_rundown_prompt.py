"""解题提示里的推进顺序：先读材料、分段核对、别拿空探针充数。

这一批措辞不是文风偏好。本机 7B 模型的实测行为是：不看附件先写脚本、
用 `python -c 'import base64'` 当进展、把上一段算出的字母表重推一遍。
提示里少了这几句，路线就会在这三个坑里原地打转。
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from spiritscout.core.models import RunMode
from spiritscout.ctf.agents import CTFCryptoAgent, CTFMiscAgent, CTFReverseAgent


def _prompt(cls, *, mode=RunMode.CTF, shared_prefix: bool = False) -> str:
    agent = object.__new__(cls)
    agent.ctx = SimpleNamespace(mode=mode, search_enabled=False)
    return agent._solver_system_prompt(shared_prefix=shared_prefix)


class SolverRundownTests(unittest.TestCase):
    def test_reading_material_comes_before_writing_scripts(self) -> None:
        for cls in (CTFCryptoAgent, CTFMiscAgent, CTFReverseAgent):
            text = _prompt(cls)
            self.assertIn("第一次工具调用只能是「读」", text)
            self.assertIn("attachments/<文件名>", text)

    def test_empty_probes_are_called_out(self) -> None:
        text = _prompt(CTFMiscAgent)
        self.assertIn("空探针", text)
        self.assertIn("原地打转", text)

    def test_printed_intermediate_value_feeds_the_next_stage(self) -> None:
        text = _prompt(CTFCryptoAgent)
        self.assertIn("就是下一段的输入", text)
        self.assertIn("以打印出来的那份为准", text)

    def test_branching_needs_two_distinct_hypotheses(self) -> None:
        text = _prompt(CTFMiscAgent)
        self.assertIn("两个", text)
        self.assertIn("互不相同的具体假设", text)

    def test_shared_prefix_keeps_no_relative_artifact_path(self) -> None:
        text = _prompt(CTFMiscAgent, shared_prefix=True)
        self.assertNotIn("../artifacts/", text)
        self.assertIn("environment.artifacts", text)
        self.assertIn("第一次工具调用只能是「读」", text)


if __name__ == "__main__":
    unittest.main()
