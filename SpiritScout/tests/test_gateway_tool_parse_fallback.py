"""端点自己解析 tool_calls 崩溃时，去掉 tools 重发让正文 JSON 说话。"""
from __future__ import annotations

import unittest

from spiritscout.gateway.backends import LiteLLMBackend


def _err(msg: str) -> Exception:
    return RuntimeError(msg)


class ToolParseBrokenTests(unittest.TestCase):
    def test_llama_cpp_json_error_is_recognised(self) -> None:
        """llama.cpp 的解析器在长参数上直接报 json.exception。"""
        exc = _err(
            "litellm.InternalServerError: OpenAIException - Failed to parse tool call "
            "arguments as JSON: [json.exception.parse_error.101] parse error at line 1, "
            "column 1127: syntax error while parsing value - invalid string")
        self.assertTrue(LiteLLMBackend._tool_parse_broken(exc))

    def test_plain_protocol_message_is_recognised(self) -> None:
        exc = _err("Failed to parse tool call arguments as JSON: unexpected end")
        self.assertTrue(LiteLLMBackend._tool_parse_broken(exc))

    def test_other_errors_are_not_mistaken(self) -> None:
        """超窗、鉴权、限流不能被误判成「解析坏了」，否则会白丢一次带工具的机会。"""
        for msg in (
            "Context size has been exceeded",
            "Error code: 401 - invalid api key",
            "Error code: 429 - rate limit",
            "litellm.Timeout",
        ):
            self.assertFalse(LiteLLMBackend._tool_parse_broken(_err(msg)), msg)


if __name__ == "__main__":
    unittest.main()
