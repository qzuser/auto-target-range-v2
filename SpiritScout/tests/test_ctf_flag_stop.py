"""CTF 会话的收手条件：解出 Flag 就停，没解出就一直解。

这两个方向都要管住——只做前者会让人误以为「拿到就停」等于「早停」，只做后者
就会空手收场。异步题（离线题）没有裁决方，提取到候选即算解出；有提交接口时
必须等平台点头。
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from spiritscout.agents.master.agent import MasterAgent
from spiritscout.agents.master.dag import TaskDAG


class FakePlatform:
    def __init__(self, completion: bool = True, done: bool = False) -> None:
        self._completion = completion
        self._done = done

    def has_completion_signal(self) -> bool:
        return self._completion

    def all_completed(self) -> bool:
        return self._done


def make_master(run_mode: str = "ctf", platform=None) -> MasterAgent:
    master = object.__new__(MasterAgent)
    master.agent_id = "master-test"
    master.ctx = SimpleNamespace(
        extra={"run_mode": run_mode, "platform": platform})
    return master


def view(*, extracted=0, accepted=0, submitted=0, submit_enabled=False) -> dict:
    return {"flags": {"extracted": extracted, "submitted": submitted,
                      "accepted": accepted, "rejected": 0,
                      "submit_enabled": submit_enabled}}


class SolvedFlagCountingTests(unittest.TestCase):
    def test_offline_challenge_counts_extracted_candidates(self) -> None:
        """离线题没有提交接口，accepted 永远是 0——只能以提取到候选为准。"""
        m = make_master()
        self.assertEqual(m._solved_flags(view(extracted=1)), 1)
        self.assertEqual(m._solved_flags(view(extracted=0)), 0)

    def test_online_challenge_needs_platform_acceptance(self) -> None:
        """有接口时自己说了不算：提取到但没被接受，仍是没解出。"""
        m = make_master()
        self.assertEqual(m._solved_flags(view(submit_enabled=True, extracted=3)), 0)
        self.assertEqual(
            m._solved_flags(view(submit_enabled=True, extracted=3, accepted=1)), 1)


class FlagHardStopTests(unittest.TestCase):
    def test_stops_as_soon_as_flag_is_accepted(self) -> None:
        """解出即停：不要求剩余节点跑完。"""
        dag = TaskDAG()
        dag.upsert_from_plan([{"tactic": "CTF-WEB", "title": "还没跑完的方向"}], 0)
        self.assertTrue(dag.has_unfinished(), "前提：确实还有未完成节点")
        m = make_master()
        self.assertTrue(m._flag_hard_stop(view(submit_enabled=True, accepted=1), dag))

    def test_offline_flag_also_stops(self) -> None:
        m = make_master()
        self.assertTrue(m._flag_hard_stop(view(extracted=1), TaskDAG()))

    def test_keeps_going_when_nothing_solved(self) -> None:
        m = make_master()
        self.assertFalse(m._flag_hard_stop(view(), TaskDAG()))

    def test_online_unaccepted_flag_does_not_stop(self) -> None:
        m = make_master()
        self.assertFalse(
            m._flag_hard_stop(view(submit_enabled=True, extracted=2), TaskDAG()))

    def test_src_mode_never_takes_this_shortcut(self) -> None:
        """漏洞挖掘没有「一盘到底」的完成信号，交给复盘判断。"""
        m = make_master(run_mode="src")
        self.assertFalse(m._flag_hard_stop(view(submit_enabled=True, accepted=1), TaskDAG()))

    def test_platform_multi_challenge_keeps_going_until_all_done(self) -> None:
        m = make_master(platform=FakePlatform(completion=True, done=False))
        self.assertFalse(m._flag_hard_stop(
            view(submit_enabled=True, accepted=1), TaskDAG()),
            "平台还有未完成题，一题得分不算收手")
        m_done = make_master(platform=FakePlatform(completion=True, done=True))
        self.assertTrue(m_done._flag_hard_stop(
            view(submit_enabled=True, accepted=1), TaskDAG()))

    def test_platform_without_completion_signal_uses_flag(self) -> None:
        m = make_master(platform=FakePlatform(completion=False))
        self.assertTrue(m._flag_hard_stop(view(submit_enabled=True, accepted=1), TaskDAG()))


class UnsolvedKeepsSolvingTests(unittest.TestCase):
    def test_unsolved_is_true_while_no_flag(self) -> None:
        m = make_master()
        self.assertTrue(m._ctf_unsolved(view()))
        self.assertFalse(m._ctf_unsolved(view(extracted=1)))

    def test_unsolved_is_false_outside_ctf(self) -> None:
        m = make_master(run_mode="src")
        self.assertFalse(m._ctf_unsolved(view()))


if __name__ == "__main__":
    unittest.main()
