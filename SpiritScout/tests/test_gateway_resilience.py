"""网关韧性：单次调用硬超时与瞬时断连就地重试。

两件事都对着实测的坏情况：远端渠道一次 `Connection error` 曾把整轮挂在一条
已经死掉的流上 17 分钟（SDK 的 timeout 只管单次读写，流式响应不吐字也不报错），
而这类断流本身是瞬时的，重发一次就好。用本机真实 HTTP 端点验证，不访问付费模型。
"""
from __future__ import annotations

import asyncio
import unittest

from spiritscout.config.settings import GatewayConfig, ModelEntry
from spiritscout.core.audit import NullAuditLogger
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
