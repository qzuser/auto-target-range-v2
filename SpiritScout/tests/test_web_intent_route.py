"""续聊意图路由：模型不按 JSON 输出时不能让整轮续传失败。

真实故障：自定义渠道的 `cn:deepseek-v4.1-flash` 完全无视 `response_format=json`
与「只输出 JSON」的指令，回一段散文（"好的，继续第三题。不过…请把题目发我"），
`extract_json` 抛错后旧实现直接 `raise SpiritScoutError("续聊意图应答无效")`，
用户在续聊框里发什么都被挡住。现在按「解析 → 压成单词再问一次 → 措辞启发式」
降级，模型本身不可用才上抛。
"""
from __future__ import annotations

import unittest
from typing import Any
from unittest import mock

from spiritscout.core.audit import NullAuditLogger
from spiritscout.web import sessions as ws

_PROSE = "好的，继续第三题。不过当前对话里没有第三题的题干/图片，请把题目发我，我接着解。"


class _FakeGateway:
    """按顺序吐预设回复；元素是异常时抛出。"""

    def __init__(self, replies: list[Any]) -> None:
        self.replies = list(replies)
        self.calls: list[list[dict[str, str]]] = []

    async def chat(self, messages, **kwargs):  # noqa: ANN001, ANN003, ARG002
        self.calls.append(messages)
        reply = self.replies.pop(0) if self.replies else ""
        if isinstance(reply, BaseException):
            raise reply

        class _Resp:
            content = reply
        return _Resp()


def _route(gateway: _FakeGateway, mission: str = "继续", history=None):
    cfg = mock.Mock()
    cfg.gateway.request_timeout_seconds = 45
    with mock.patch.object(ws, "_conversation_gateway", return_value=gateway), \
         mock.patch.object(ws, "_bound_model", return_value=""):
        import asyncio
        return asyncio.run(ws._llm_route_intent(
            cfg, [], mission, NullAuditLogger(), history=history))


class ParseIntentTests(unittest.TestCase):
    def test_json_shapes(self) -> None:
        self.assertEqual(ws._parse_intent_text('{"intent":"dialogue"}'), "dialogue")
        self.assertEqual(ws._parse_intent_text('{"answer":{"intent":"task"}}'), "task")
        self.assertEqual(ws._parse_intent_text('```json\n{"intent": "rules"}\n```'), "rules")
        self.assertEqual(ws._parse_intent_text('好的：{"intent":"task_with_rules"}'),
                         "task_with_rules")

    def test_bare_word_and_alias(self) -> None:
        self.assertEqual(ws._parse_intent_text("dialogue"), "dialogue")
        self.assertEqual(ws._parse_intent_text("intent: continue"), "task")

    def test_prose_yields_nothing(self) -> None:
        self.assertEqual(ws._parse_intent_text(_PROSE), "")
        self.assertEqual(ws._parse_intent_text(""), "")


class GuessIntentTests(unittest.TestCase):
    def test_continue_wins(self) -> None:
        self.assertEqual(ws._guess_intent("继续"), "task")
        self.assertEqual(ws._guess_intent("接着打第三题"), "task")
        self.assertEqual(ws._guess_intent("把 misc-01 也打一遍"), "task")

    def test_short_question_or_greeting_is_dialogue(self) -> None:
        self.assertEqual(ws._guess_intent("三题都解完了吗"), "dialogue")
        self.assertEqual(ws._guess_intent("为什么没打 misc"), "dialogue")
        self.assertEqual(ws._guess_intent("你好呀"), "dialogue")

    def test_empty_defaults_to_task(self) -> None:
        self.assertEqual(ws._guess_intent(""), "task")


class RouteIntentTests(unittest.TestCase):
    def test_prose_answers_fall_back_to_heuristic_without_raising(self) -> None:
        gateway = _FakeGateway([_PROSE])
        self.assertEqual(_route(gateway), "task")
        self.assertEqual(len(gateway.calls), 1,
                         "散文应答不再追问第二次（实测 0/9 成功，纯浪费一次调用）")

    def test_short_question_prose_becomes_dialogue(self) -> None:
        gateway = _FakeGateway([
            "还没有，三题没全部解完：前两题已完成，第三题还在处理，尚未完成。"])
        self.assertEqual(_route(gateway, mission="三题都解完了吗"), "dialogue")

    def test_valid_json_short_circuits(self) -> None:
        gateway = _FakeGateway(['{"intent":"dialogue"}'])
        self.assertEqual(_route(gateway), "dialogue")
        self.assertEqual(len(gateway.calls), 1, "解析成功不该再问第二次")

    def test_model_unavailable_raises(self) -> None:
        class _Broken(_FakeGateway):
            async def chat(self, messages, **kwargs):  # noqa: ANN001, ANN003, ARG002
                raise RuntimeError("模型不可用")

        with self.assertRaises(RuntimeError):
            _route(_Broken([]))
