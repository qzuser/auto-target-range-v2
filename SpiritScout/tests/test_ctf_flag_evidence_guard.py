"""submit_flag 的出处校验：编出来的 Flag 不许登记。"""
from __future__ import annotations

import unittest

from spiritscout.ctf.agents import _EVIDENCE_POOL_CHARS, CTFBaseAgent


def _agent() -> CTFBaseAgent:
    """只借两个不依赖上下文的方法，绕开完整构造。"""
    obj = CTFBaseAgent.__new__(CTFBaseAgent)
    return obj


class FlagEvidenceGuardTests(unittest.TestCase):
    def test_flag_seen_in_tool_output_is_accepted(self) -> None:
        agent = _agent()
        state: dict = {}
        agent._record_evidence(state, "GET /flag → 200\n这里是答案 flag{n0_m0r3_gu3ss}")
        self.assertTrue(agent._flag_seen_in_evidence(state, "flag{n0_m0r3_gu3ss}"))

    def test_invented_flag_is_rejected(self) -> None:
        """实测幻觉：hint 只说『flag in ffffllllaaaagggg』，模型把文件名拼成 flag。"""
        agent = _agent()
        state: dict = {}
        agent._record_evidence(state, "flag not here, and flag in ffffllllaaaagggg")
        self.assertFalse(agent._flag_seen_in_evidence(state, "flag{ffffllllaaaagggg}"))

    def test_empty_pool_rejects(self) -> None:
        agent = _agent()
        self.assertFalse(agent._flag_seen_in_evidence({}, "flag{anything}"))

    def test_no_execution_skips_the_check(self) -> None:
        """一次工具都没跑就提交：可能是纯推理题，不该被证据池挡住。"""
        self.assertFalse({"executions": 0}.get("executions"))
        self.assertTrue({"executions": 3}.get("executions"))

    def test_partial_print_does_not_count(self) -> None:
        """只出现过内层、整体没打印过 —— 不算拿到（模型必须自己拼完整再 print）。"""
        agent = _agent()
        state: dict = {}
        agent._record_evidence(state, "prefix=flag{ then 5up3r_s3cr3t")
        self.assertFalse(agent._flag_seen_in_evidence(state, "flag{5up3r_s3cr3t}"))

    def test_pool_is_capped(self) -> None:
        agent = _agent()
        state: dict = {}
        for i in range(40):
            agent._record_evidence(state, f"chunk-{i} " + "x" * 2000)
        self.assertLessEqual(len(state["evidence_pool"]), _EVIDENCE_POOL_CHARS)
        # 最新的一定在，最早的一定被挤掉
        self.assertIn("chunk-39", state["evidence_pool"])
        self.assertNotIn("chunk-0 ", state["evidence_pool"])


if __name__ == "__main__":
    unittest.main()
