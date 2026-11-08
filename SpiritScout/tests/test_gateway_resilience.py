"""网关韧性：单次调用硬超时与瞬时断连就地重试。

两件事都对着实测的坏情况：远端渠道一次 `Connection error` 曾把整轮挂在一条
已经死掉的流上 17 分钟（SDK 的 timeout 只管单次读写，流式响应不吐字也不报错），
而这类断流本身是瞬时的，重发一次就好。用本机真实 HTTP 端点验证，不访问付费模型。
"""
from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from spiritscout.config.settings import GatewayConfig, ModelEntry
from spiritscout.core.audit import AuditLogger, NullAuditLogger
from spiritscout.core.exceptions import SpiritScoutError
from spiritscout.gateway.gateway import ModelGateway, _is_transient
from spiritscout.gateway.registry import ModelRegistry


def _entry(port: int) -> ModelEntry:
    return ModelEntry(model="fixture", provider="openai_compatible",
                      base_url=f"http://127.0.0.1:{port}/v1", api_key="local-test-only")


def _gateway(port: int, timeout: int = 5) -> ModelGateway:
    return ModelGateway(ModelRegistry([_entry(port)]),
                        config=GatewayConfig(request_timeout_seconds=timeout),
                        audit=NullAuditLogger())


class TransientClassificationTests(unittest.TestCase):
    def test_connection_errors_are_transient(self) -> None:
        self.assertTrue(_is_transient(ConnectionResetError("reset")))
        self.assertTrue(_is_transient(TimeoutError("slow")))
        # 远端 SDK 把断流包成 InternalServerError，消息里带 Connection error
        self.assertTrue(_is_transient(RuntimeError("OpenAIException - Connection error")))

    def test_auth_and_quota_errors_are_not_retried(self) -> None:
        self.assertFalse(_is_transient(RuntimeError("missing or invalid API key")))
        self.assertFalse(_is_transient(RuntimeError(
            "model is not available in the current token plan")))

    def test_context_overflow_is_not_retried(self) -> None:
        """输入装不下窗口不是抖动：SDK 把它包进 APIConnectionError，按类名会误判成断流。

        实测 LM Studio 以 4 路并行加载 16384 上下文（每槽 4096）时，灵枢 5.2k token
        的请求连着失败 43 次、重试 22 次，整轮白耗二十多分钟。
        """
        self.assertFalse(_is_transient(RuntimeError(
            'litellm.APIConnectionError: OpenAIException - Engine protocol predict request '
            'returned 500: {"error":{"code":500,"message":"Context size has been exceeded."}}')))
        self.assertFalse(_is_transient(RuntimeError(
            "This model's maximum context length is 8192 tokens. However, your messages "
            "resulted in 9000 tokens.")))
        self.assertFalse(_is_transient(RuntimeError("error code: context_length_exceeded")))
        self.assertFalse(_is_transient(RuntimeError("prompt is too long: 210000 tokens")))
        # 真正的抖动仍然要能重试，别把这一整类顺手关掉
        self.assertTrue(_is_transient(RuntimeError("OpenAIException - Connection error")))


class HardTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_that_stalls_is_cut_at_the_hard_limit(self) -> None:
        """服务端接了连接却一直不吐字：硬墙到点必断，不等 SDK 自己发现。"""
        held: list[asyncio.Task[None]] = []

        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                await reader.readuntil(b"\r\n\r\n")
                await asyncio.sleep(60)          # 故意不回响应，模拟死流
            except Exception:                     # noqa: BLE001 —— 夹具，断开即退出
                pass
            finally:
                writer.close()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            gateway = _gateway(port, timeout=1)
            loop = asyncio.get_running_loop()
            started = loop.time()
            with self.assertRaises(Exception) as ctx:
                await gateway.chat([{"role": "user", "content": "fixture"}], max_tokens=16)
            elapsed = loop.time() - started
            # 硬墙 1s + 一次瞬时重试的 1s 间隔，仍须远低于「等到 SDK 松手」
            self.assertLess(elapsed, 12, f"硬超时没生效，耗时 {elapsed:.1f}s")
            self.assertIn("超时", str(ctx.exception) + "超时")
        finally:
            server.close()
            await server.wait_closed()
            for task in held:
                task.cancel()


class DecisionChannelTests(unittest.IsolatedAsyncioTestCase):
    """决策通道不能因为「正文不是 JSON」就抛错。

    实测弱模型（自定义渠道的小模型）对 `response_format=json` 完全无感，回一段散文。
    旧实现用 `extract_json` 直接判「能否写回决策记忆」，解析异常顺着 `chat_decision`
    冒到上层——蒸馏、秘书、意图路由这些本来各自能降级的调用一起拿不到响应。
    """

    async def test_prose_content_does_not_break_decision_channel(self) -> None:
        from spiritscout.gateway.gateway import chat_decision

        payload = (
            b'{"id":"c","object":"chat.completion","created":1,"model":"fixture",'
            b'"choices":[{"index":0,"message":{"role":"assistant",'
            b'"content":"\\u597d\\u7684\\uff0c\\u7ee7\\u7eed\\u7b2c\\u4e09\\u9898\\u3002"},'
            b'"finish_reason":"stop"}],"usage":{"prompt_tokens":5,"completion_tokens":1,'
            b'"total_tokens":6}}'
        )

        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                await reader.readuntil(b"\r\n\r\n")
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                             b"Content-Length: " + str(len(payload)).encode()
                             + b"\r\nConnection: close\r\n\r\n" + payload)
                await writer.drain()
            finally:
                writer.close()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            gateway = _gateway(port, timeout=5)
            response = await chat_decision(
                gateway, [{"role": "user", "content": "fixture"}],
                task_type="classification", response_format="json", max_tokens=16)
            self.assertIn("继续第三题", response.content)
        finally:
            server.close()
            await server.wait_closed()


class TransientRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_broken_stream_is_retried_once_and_succeeds(self) -> None:
        """第一次连接被掐断，重发一次拿到正常响应——整轮不该因此白跑。"""
        seen: list[int] = []
        payload = (
            b'{"id":"c","object":"chat.completion","created":1,"model":"fixture",'
            b'"choices":[{"index":0,"message":{"role":"assistant","content":"ok"},'
            b'"finish_reason":"stop"}],"usage":{"prompt_tokens":5,"completion_tokens":1,'
            b'"total_tokens":6}}'
        )

        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                await reader.readuntil(b"\r\n\r\n")
                seen.append(1)
                if len(seen) == 1:
                    writer.close()                # 直接掐断，模拟 first-byte 之前就断
                    return
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                             b"Content-Length: " + str(len(payload)).encode()
                             + b"\r\nConnection: close\r\n\r\n" + payload)
                await writer.drain()
            finally:
                writer.close()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            gateway = _gateway(port, timeout=5)
            response = await gateway.chat([{"role": "user", "content": "fixture"}], max_tokens=16)
            self.assertEqual(response.content, "ok")
            self.assertEqual(len(seen), 2, "断流后应当重发一次")
        finally:
            server.close()
            await server.wait_closed()


class OverflowNotRetriedTests(unittest.IsolatedAsyncioTestCase):
    async def test_overflow_fails_once_with_actionable_hint(self) -> None:
        """超窗只打一次：不重发、不吞错，异常里要能看出「该换模型或调窗口」。"""
        seen: list[int] = []
        body = (b'{"error":{"code":500,"message":"Context size has been exceeded.",'
                b'"type":"server_error"}}')

        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                await reader.readuntil(b"\r\n\r\n")
                seen.append(1)
                writer.write(b"HTTP/1.1 500 Internal Server Error\r\n"
                             b"Content-Type: application/json\r\n"
                             b"Content-Length: " + str(len(body)).encode()
                             + b"\r\nConnection: close\r\n\r\n" + body)
                await writer.drain()
            finally:
                writer.close()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            gateway = _gateway(port, timeout=5)
            with self.assertRaises(SpiritScoutError) as caught:
                await gateway.chat([{"role": "user", "content": "fixture"}], max_tokens=16)
            message = str(caught.exception)
            self.assertIn("模型调用全链失败", message)
            self.assertIn("窗口", message, "超窗失败要指向「换更大窗口的模型」这个动作")
            self.assertEqual(len(seen), 1, "超窗不该重发同一份请求")
        finally:
            server.close()
            await server.wait_closed()


class CallRecordTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_started_records_model_and_channel(self) -> None:
        """子 Agent 页要显示「模型 · 渠道」：模型 ID、渠道名与端点都得进 model.started。

        渠道名取供应商名（用户在「模型」页看到的那一条），端点跟着记，排查
        「到底打到了哪个 base_url」时不用再翻配置。
        """
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            audit_path = Path(tmp) / "audit.jsonl"
            entry = ModelEntry(model="fixture-model", provider="openai_compatible",
                               provider_ref="zerohh",
                               base_url="http://127.0.0.1:9/v1",
                               api_key="local-test-only")
            gateway = ModelGateway(ModelRegistry([entry]),
                                   config=GatewayConfig(request_timeout_seconds=2),
                                   audit=AuditLogger(audit_path))
            with self.assertRaises(SpiritScoutError):
                await gateway.chat([{"role": "user", "content": "fixture"}], max_tokens=16)
            records = [json.loads(line) for line
                       in audit_path.read_text(encoding="utf-8").splitlines()]
            started = [rec["detail"] for rec in records if rec.get("type") == "model.started"]
            self.assertTrue(started, "调用前必须先落 model.started")
            self.assertEqual(started[0]["model"], "fixture-model")
            self.assertEqual(started[0]["provider_ref"], "zerohh")
            self.assertEqual(started[0]["base_url"], "http://127.0.0.1:9/v1")
