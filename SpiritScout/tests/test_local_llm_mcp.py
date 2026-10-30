"""本地 LLM 的 MCP 服务器：协议走通、工具真的能拿到模型输出。

这条链路最容易坏在两个地方：一是 stdio 上的 JSON-RPC 说错话，客户端的握手直接
挂住；二是端点连不上时只抛一个 URLError，使用者看不出「后端没起」还是「地址配
错」。所以这里两头都钉住——协议按真实报文验，后端用一个本地假端点验，不依赖
本机是否真的装着 LM Studio。
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spiritscout.tools import local_llm_mcp as mcp  # noqa: E402


class _StubModel(BaseHTTPRequestHandler):
    """假 OpenAI 兼容端点：只认两道接口，够验通链路。"""

    last_payload: ClassVar[dict[str, Any]] = {}
    reject_chat_template_kwargs: ClassVar[bool] = False

    def log_message(self, *args) -> None:  # 静音，别刷测试输出
        return

    def _send(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 的约定
        if self.path.rstrip("/").endswith("/models"):
            self._send({"object": "list", "data": [{"id": "gemma-4-12b"}, {"id": "bonsai-27b"}]})
        else:
            self._send({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length) or b"{}")
        type(self).last_payload = request
        if self.path.rstrip("/").endswith("/chat/completions"):
            if self.reject_chat_template_kwargs and "chat_template_kwargs" in request:
                self._send({"error": "unknown field chat_template_kwargs"}, 400)
                return
            turns = len(request.get("messages", []))
            self._send({
                "id": "chatcmpl-stub",
                "model": request.get("model", ""),
                "choices": [{
                    "message": {"role": "assistant", "content": f"本地回声：{turns}"},
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
            })
        else:
            self._send({"error": "not found"}, 404)


class StubEndpointMixin:
    """起一个只监听回环的临时端口，测完立刻关。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.server = HTTPServer(("127.0.0.1", 0), _StubModel)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self) -> None:
        self.env = mock.patch.dict(os.environ, {
            "SPIRITSCOUT_LOCAL_LLM_URL": f"http://127.0.0.1:{self.port}/v1",
            "SPIRITSCOUT_LOCAL_LLM_TIMEOUT": "20",
        }, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)


class EndpointTests(StubEndpointMixin, unittest.TestCase):
    def test_status_reports_online_and_the_available_models(self) -> None:
        status = mcp.server_status()
        self.assertTrue(status["online"])
        self.assertEqual(status["models"], ["gemma-4-12b", "bonsai-27b"])
        self.assertIn("latency_ms", status)

    def test_models_reads_the_openai_compatible_listing(self) -> None:
        self.assertEqual(mcp.list_models(), ["gemma-4-12b", "bonsai-27b"])

    def test_chat_returns_the_model_text_and_usage(self) -> None:
        result = mcp.chat("你好", system="你是本地助手")
        self.assertTrue(result["ok"])
        self.assertEqual(result["model"], "gemma-4-12b", "没指定模型时用端点上的第一个")
        self.assertEqual(result["text"], "本地回声：2", "系统提示 + 用户消息共两条")
        self.assertEqual(result["usage"]["total_tokens"], 8)

    def test_chat_honours_an_explicit_model_and_skips_the_system_prompt(self) -> None:
        result = mcp.chat("只问一句", model="bonsai-27b")
        self.assertEqual(result["model"], "bonsai-27b")
        self.assertEqual(result["text"], "本地回声：1", "没给 system 就只发一条 user")

    def test_chat_rejects_an_empty_prompt(self) -> None:
        result = mcp.chat("   ")
        self.assertFalse(result["ok"])
        self.assertIn("prompt", result["error"])

    def test_chat_rejects_a_prompt_too_large_for_a_local_model(self) -> None:
        result = mcp.chat("x" * (mcp.MAX_PROMPT_CHARS + 1))
        self.assertFalse(result["ok"])
        self.assertIn("上下文", result["error"])

    def test_chat_clamps_out_of_range_sampling_parameters(self) -> None:
        result = mcp.chat("hi", max_tokens=999999, temperature=-5)
        self.assertTrue(result["ok"], "越界参数应被夹到合法区间而不是报错")

    def test_bad_parameter_types_fall_back_instead_of_failing_the_call(self) -> None:
        """模型经常把数字写成字符串。转不动要退回默认值，而不是报成"未知工具"。"""
        result = mcp.call_tool("local_llm_chat",
                               {"prompt": "参数乱填也得能跑", "max_tokens": "abc",
                                "temperature": "热", "thinking": "false"})
        self.assertTrue(result["ok"], result.get("error", ""))
        self.assertIn("本地回声", result["text"])

    def test_thinking_string_false_is_not_truthy(self) -> None:
        """``bool("false")`` 是 True——客户端传字符串时必须按字面意思读。"""
        mcp.call_tool("local_llm_chat", {"prompt": "关掉思考", "thinking": "false"})
        self.assertEqual(_StubModel.last_payload.get("chat_template_kwargs"),
                         {"enable_thinking": False})

    def test_http_error_is_not_reported_as_a_dead_backend(self) -> None:
        """HTTPError 是 URLError 的子类：判反了就会把 400 说成"后端没起"。"""
        _StubModel.reject_chat_template_kwargs = True
        self.addCleanup(setattr, _StubModel, "reject_chat_template_kwargs", False)
        message = mcp._fail(urllib.error.HTTPError(
            "http://127.0.0.1/v1/chat", 400, "Bad Request", {}, io.BytesIO(b"bad field")))
        self.assertIn("返回 400", message)
        self.assertNotIn("连不上", message)
        self.assertNotIn("Start Server", message)

    def test_thinking_is_off_by_default(self) -> None:
        """推理模型默认先想一大段；纯 CPU 上这一项能吃掉几十秒，默认必须关掉。"""
        mcp.chat("一句话回答")
        kwargs = _StubModel.last_payload.get("chat_template_kwargs")
        self.assertEqual(kwargs, {"enable_thinking": False})

    def test_thinking_can_be_turned_back_on(self) -> None:
        mcp.chat("需要推理过程", thinking=True)
        self.assertNotIn("chat_template_kwargs", _StubModel.last_payload,
                         "要思考的时候不该发关闭标志")

    def test_endpoint_that_rejects_the_extension_field_still_answers(self) -> None:
        """这个字段是 llama.cpp 系的扩展，别的端点不认——去掉重发一次，别让整次调用白费。"""
        _StubModel.reject_chat_template_kwargs = True
        self.addCleanup(setattr, _StubModel, "reject_chat_template_kwargs", False)
        result = mcp.chat("换个能认的端点")
        self.assertTrue(result["ok"], result.get("error", ""))
        self.assertIn("本地回声", result["text"])
        self.assertNotIn("chat_template_kwargs", _StubModel.last_payload)


class OfflineTests(unittest.TestCase):
    """端口上没人听的时候，错误消息必须能指导下一步。"""

    def setUp(self) -> None:
        self.env = mock.patch.dict(os.environ, {
            "SPIRITSCOUT_LOCAL_LLM_URL": "http://127.0.0.1:9/v1",
            "SPIRITSCOUT_LOCAL_LLM_TIMEOUT": "5",
        }, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_status_reports_offline_with_an_actionable_hint(self) -> None:
        status = mcp.server_status()
        self.assertFalse(status["online"])
        self.assertEqual(status["endpoint"], "http://127.0.0.1:9/v1")
        for hint in ("Start Server", "ollama serve", "SPIRITSCOUT_LOCAL_LLM_URL"):
            self.assertIn(hint, status["error"], f"错误提示里缺 {hint}，用户照着做不了")

    def test_models_surfaces_the_same_hint_instead_of_raising(self) -> None:
        result = mcp.call_tool("local_llm_models", {})
        self.assertFalse(result["ok"])
        self.assertIn("连不上", result["error"])

    def test_chat_does_not_raise_when_the_backend_is_down(self) -> None:
        result = mcp.chat("hi")
        self.assertFalse(result["ok"])
        self.assertIn("连不上", result["error"])


class DefaultsTests(unittest.TestCase):
    def test_defaults_point_at_lm_studio(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SPIRITSCOUT_LOCAL_LLM_URL", None)
            os.environ.pop("SPIRITSCOUT_LOCAL_LLM_TIMEOUT", None)
            self.assertEqual(mcp.base_url(), "http://127.0.0.1:1234/v1")
            self.assertEqual(mcp.timeout_seconds(), 120.0)

    def test_trailing_slash_is_trimmed_so_paths_do_not_double_up(self) -> None:
        with mock.patch.dict(os.environ, {"SPIRITSCOUT_LOCAL_LLM_URL": "http://127.0.0.1:11434/v1/"}):
            self.assertEqual(mcp.base_url(), "http://127.0.0.1:11434/v1")

    def test_bad_timeout_falls_back_instead_of_crashing(self) -> None:
        with mock.patch.dict(os.environ, {"SPIRITSCOUT_LOCAL_LLM_TIMEOUT": "abc"}):
            self.assertEqual(mcp.timeout_seconds(), 120.0)
        with mock.patch.dict(os.environ, {"SPIRITSCOUT_LOCAL_LLM_TIMEOUT": "0"}):
            self.assertEqual(mcp.timeout_seconds(), 120.0)


class ProtocolTests(StubEndpointMixin, unittest.TestCase):
    """真起一个子进程，按 MCP 的 stdio 报文对话。"""

    def _run(self, messages: list[dict]) -> list[dict]:
        stdin = "\n".join(json.dumps(m) for m in messages) + "\n"
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT / "src")
        env["SPIRITSCOUT_LOCAL_LLM_URL"] = f"http://127.0.0.1:{self.port}/v1"
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "spiritscout.tools.local_llm_mcp"],
            input=stdin, capture_output=True, text=True, encoding="utf-8",
            errors="replace", cwd=str(ROOT), env=env, timeout=90)
        self.assertEqual(proc.returncode, 0, proc.stderr[-800:])
        replies = []
        for line in proc.stdout.splitlines():
            line = line.strip()
            if line:
                replies.append(json.loads(line))
        return replies

    def test_handshake_then_tools_list(self) -> None:
        replies = self._run([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ])
        by_id = {r.get("id"): r for r in replies}
        self.assertEqual(by_id[1]["result"]["serverInfo"]["name"], "local-llm")
        self.assertIn("tools", by_id[1]["result"]["capabilities"])
        names = [t["name"] for t in by_id[2]["result"]["tools"]]
        self.assertEqual(names, ["local_llm_status", "local_llm_models", "local_llm_chat"])
        self.assertNotIn(3, by_id, "通知不该有回复——多回一条会让客户端错位")

    def test_tool_call_returns_text_content(self) -> None:
        replies = self._run([
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
             "params": {"name": "local_llm_chat", "arguments": {"prompt": "打个招呼"}}},
        ])
        content = replies[0]["result"]["content"][0]
        self.assertEqual(content["type"], "text")
        payload = json.loads(content["text"])
        self.assertTrue(payload["ok"])
        self.assertIn("本地回声", payload["text"])

    def test_unknown_tool_is_a_protocol_error(self) -> None:
        replies = self._run([
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
             "params": {"name": "no_such_tool", "arguments": {}}},
        ])
        self.assertEqual(replies[0]["error"]["code"], -32602)
        self.assertIn("no_such_tool", replies[0]["error"]["message"])

    def test_ping_is_answered(self) -> None:
        replies = self._run([{"jsonrpc": "2.0", "id": 7, "method": "ping"}])
        self.assertEqual(replies[0], {"jsonrpc": "2.0", "id": 7, "result": {}})

    def test_malformed_envelopes_do_not_kill_the_loop(self) -> None:
        """客户端偶尔会发非对象报文或别把 params 写成数组——跳过就行，不能退出。"""
        replies = self._run([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2024-11-05"}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": ["not", "a", "dict"]},
            {"jsonrpc": "2.0", "id": 3, "method": "ping"},
        ])
        self.assertEqual(replies[0]["result"]["serverInfo"]["name"], "local-llm")
        self.assertEqual(replies[-1]["result"], {}, "畸形 params 之后循环还该继续")

    def test_stdout_carries_only_protocol_json(self) -> None:
        """stdout 一旦混进日志，客户端解析就会崩——这是 stdio MCP 最常见的翻车点。"""
        replies = self._run([{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}])
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0]["jsonrpc"], "2.0")


if __name__ == "__main__":
    unittest.main()
