"""同一路线里重复提问必须被折叠：问-答-再问的空转烧的是真 token。"""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from spiritscout.core.models import AgentType
from spiritscout.ctf.agents import ASK_USER_REPEAT_LIMIT, CTFBaseAgent


class _Audit:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def log(self, kind: str, actor: str, detail: dict) -> None:
        self.events.append((kind, detail))


class _Broker:
    """只回答一次的用户：后端记录它到底被打搅了几次。"""

    interactive = True

    def __init__(self) -> None:
        self.calls = 0

    async def ask(self, agent: str, question: str, options: list[str],
                  targets: list[str], multiple: bool = False) -> dict:
        self.calls += 1
        return {"answer": "附件可读，按原计划继续"}


def _agent(audit: _Audit, broker: _Broker) -> SimpleNamespace:
    return SimpleNamespace(
        ctx=SimpleNamespace(audit=audit, questions=broker),
        agent_type=AgentType.CTF_CRYPTO,
        agent_id="ctf-crypto-test",
        challenge_id=lambda task: "mission-1",
    )


class AskUserDedupeTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_question_is_not_asked_twice(self) -> None:
        audit, broker = _Audit(), _Broker()
        agent = _agent(audit, broker)
        state: dict = {}
        task = SimpleNamespace(task_id="task-1")
        route = SimpleNamespace(name="solve")
        args = {"question": "附件是否可读？", "options": ["可读", "不可读"]}

        first = await CTFBaseAgent._tool_ask_user(agent, task, route, state, args)
        self.assertTrue(first.ok)
        self.assertEqual(broker.calls, 1)
        self.assertIn("用户答复", first.note)

        second = await CTFBaseAgent._tool_ask_user(agent, task, route, state, args)
        self.assertTrue(second.ok)
        self.assertEqual(broker.calls, 1, "重复提问不该再打搅用户")
        self.assertIn("不要重复提问", second.text)

        self.assertTrue(any(kind == "agent.ask_user_deduped" for kind, _ in audit.events))

    async def test_repeat_limit_stops_asking_entirely(self) -> None:
        audit, broker = _Audit(), _Broker()
        agent = _agent(audit, broker)
        state: dict = {}
        task = SimpleNamespace(task_id="task-1")
        route = SimpleNamespace(name="solve")
        args = {"question": "附件是否可读？"}

        for _ in range(ASK_USER_REPEAT_LIMIT - 1):
            await CTFBaseAgent._tool_ask_user(agent, task, route, state, args)
        final = await CTFBaseAgent._tool_ask_user(agent, task, route, state, args)

        self.assertFalse(final.ok, "到上限后该拒绝继续提问")
        self.assertIn("停止提问", final.text)
        self.assertEqual(broker.calls, 1, "用户只被打搅一次")
        self.assertEqual(state["asked_questions"]["附件是否可读？"]["count"],
                         ASK_USER_REPEAT_LIMIT)

    async def test_different_questions_still_reach_the_user(self) -> None:
        audit, broker = _Audit(), _Broker()
        agent = _agent(audit, broker)
        state: dict = {}
        task = SimpleNamespace(task_id="task-1")
        route = SimpleNamespace(name="solve")

        await CTFBaseAgent._tool_ask_user(agent, task, route, state,
                                          {"question": "附件可读吗？"})
        await CTFBaseAgent._tool_ask_user(agent, task, route, state,
                                          {"question": "要不要连带查固件版本？"})
        self.assertEqual(broker.calls, 2)


if __name__ == '__main__':
    unittest.main()
