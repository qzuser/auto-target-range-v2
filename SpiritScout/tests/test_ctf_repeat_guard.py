"""同一条调用别重复执行、同一份输出别重复回灌。

本机实测：`cat attachments/base64.c` 连做 19 遍，一次没写脚本。每读一遍都把同一份
源码再塞一次上下文，压掉别的观察，下一轮更觉得没读到——典型的自我强化死循环。
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from spiritscout.core.models import AgentType, Task, TaskStatus
from spiritscout.ctf.agents import _DEDUPE_MIN_CHARS, CTFCryptoAgent, _ToolOutcome


def _task() -> Task:
    return Task(task_id="t-1", task_type="ctf_solve", target="local",
                agent_type=AgentType.CTF_CRYPTO, status=TaskStatus.RUNNING)


def _agent() -> CTFCryptoAgent:
    agent = object.__new__(CTFCryptoAgent)
    agent.agent_id = "ctf_crypto-1"
    agent.ctx = SimpleNamespace(audit=SimpleNamespace(log=lambda *a, **k: None))
    return agent


class _Route:
    name = "solve"
    route_id = "r-1"


class RepeatGuardTests(unittest.TestCase):
    def test_first_two_runs_execute_then_stop(self) -> None:
        agent, state = _agent(), {"turn": 3}
        args = {"command": "cat attachments/base64.c"}
        self.assertIsNone(agent._repeat_guard(_task(), _Route(), state, "shell", args))
        self.assertIsNone(agent._repeat_guard(_task(), _Route(), state, "shell", args))
        blocked = agent._repeat_guard(_task(), _Route(), state, "shell", args)
        self.assertIsNotNone(blocked)
        self.assertIn("已经执行过 2 次", blocked.text)
        self.assertIn("换动作", blocked.text)
        self.assertTrue(blocked.empty)

    def test_different_arguments_count_separately(self) -> None:
        agent, state = _agent(), {}
        for _ in range(3):
            agent._repeat_guard(_task(), _Route(), state, "shell",
                                {"command": "cat attachments/a.c"})
        self.assertIsNone(agent._repeat_guard(_task(), _Route(), state, "shell",
                                              {"command": "cat attachments/b.c"}))

    def test_python_and_shell_are_separate(self) -> None:
        agent, state = _agent(), {}
        for _ in range(3):
            agent._repeat_guard(_task(), _Route(), state, "shell", {"command": "ls"})
        self.assertIsNone(agent._repeat_guard(_task(), _Route(), state, "python",
                                              {"code": "print(1)"}))

    def test_other_tools_are_not_guarded(self) -> None:
        agent, state = _agent(), {}
        for _ in range(5):
            self.assertIsNone(agent._repeat_guard(_task(), _Route(), state,
                                                  "http_request", {"url": "http://a/"}))

    def test_counter_is_kept_in_state_so_it_survives_resume(self) -> None:
        agent, state = _agent(), {}
        agent._repeat_guard(_task(), _Route(), state, "shell", {"command": "ls"})
        self.assertEqual(state["call_counts"]["shell|" + '{"command": "ls"}'], 1)


class OutputDedupeTests(unittest.TestCase):
    def test_identical_long_output_is_replaced_by_a_note(self) -> None:
        agent, state = _agent(), {"turn": 4}
        body = "源码" * (_DEDUPE_MIN_CHARS // 2 + 50)
        first = agent._dedupe_output(state, "shell", _ToolOutcome(ok=True, text=body))
        self.assertEqual(first.text, body)
        second = agent._dedupe_output(state, "shell", _ToolOutcome(ok=True, text=body))
        self.assertIn("逐字相同", second.text)
        self.assertLess(len(second.text), len(body))

    def test_different_output_passes_through(self) -> None:
        agent, state = _agent(), {}
        a = "甲" * (_DEDUPE_MIN_CHARS + 10)
        b = "乙" * (_DEDUPE_MIN_CHARS + 10)
        agent._dedupe_output(state, "shell", _ToolOutcome(ok=True, text=a))
        second = agent._dedupe_output(state, "shell", _ToolOutcome(ok=True, text=b))
        self.assertEqual(second.text, b)

    def test_short_output_is_never_deduped(self) -> None:
        agent, state = _agent(), {}
        short = "ok"
        agent._dedupe_output(state, "shell", _ToolOutcome(ok=True, text=short))
        again = agent._dedupe_output(state, "shell", _ToolOutcome(ok=True, text=short))
        self.assertEqual(again.text, short)

    def test_flags_in_metadata_survive_dedupe(self) -> None:
        agent, state = _agent(), {}
        body = "x" * (_DEDUPE_MIN_CHARS + 10)
        out = _ToolOutcome(ok=True, text=body,
                           findings=[{"type": "flag", "value": "flag{a}"}])
        agent._dedupe_output(state, "shell", out)
        again = agent._dedupe_output(state, "shell", out)
        self.assertEqual(again.findings, [{"type": "flag", "value": "flag{a}"}])


if __name__ == "__main__":
    unittest.main()
