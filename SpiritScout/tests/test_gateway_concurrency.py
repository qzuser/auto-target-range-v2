"""端点并发闸：单槽本地模型不该被十几个任务同时砸。

实测背景：LM Studio 以 `--parallel 1` 加载 27B（16384 上下文全部给一个槽），
灵枢一轮同时派 12 个任务，12 个请求一起打到只有一个槽的端点上——前两个在
90s 辅助硬超时里被判失败，其余全排在队列里，会话卡住不动。这里验证
`max_concurrency` 能把并发收成排队：排队发生在单次调用硬超时之外，慢端点
只会变慢，不会因为挤在同一时刻而集体失败。

用本机真实 HTTP 端点验证，不访问付费模型。
"""
from __future__ import annotations

import asyncio
import json
import unittest

from spiritscout.config.settings import GatewayConfig, ModelEntry
from spiritscout.core.audit import NullAuditLogger
from spiritscout.gateway.gateway import ModelGateway
from spiritscout.gateway.registry import ModelRegistry

_BODY = json.dumps({
    "id": "fixture",
    "object": "chat.completion",
    "created": 0,
    "model": "fixture",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"},
                 "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
}).encode()


class _Counter:
    """记录端点观测到的同时在飞请求数与峰值。"""

    def __init__(self) -> None:
        self.inflight = 0
        self.max_inflight = 0
        self.served = 0


async def _serve(counter: _Counter, delay: float):
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        counter.inflight += 1
        counter.max_inflight = max(counter.max_inflight, counter.inflight)
        try:
            await reader.readuntil(b"\r\n\r\n")
            await asyncio.sleep(delay)
            counter.served += 1
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                         b"Content-Length: " + str(len(_BODY)).encode()
                         + b"\r\nConnection: close\r\n\r\n" + _BODY)
            await writer.drain()
        finally:
            counter.inflight -= 1
            writer.close()

    return await asyncio.start_server(handle, "127.0.0.1", 0)


def _gateway(port: int, *, max_concurrency: int, timeout: int = 20) -> ModelGateway:
    entry = ModelEntry(model="fixture", provider="openai_compatible",
                       base_url=f"http://127.0.0.1:{port}/v1", api_key="local-test-only",
                       max_concurrency=max_concurrency)
    return ModelGateway(ModelRegistry([entry]),
                        config=GatewayConfig(request_timeout_seconds=timeout),
                        audit=NullAuditLogger())


class ConcurrencyGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_single_slot_endpoint_is_never_hit_concurrently(self) -> None:
        """`max_concurrency: 1` = 一次只放一个请求进去，其余排队等。"""
        counter = _Counter()
        server = await _serve(counter, delay=0.15)
        port = server.sockets[0].getsockname()[1]
        try:
            gateway = _gateway(port, max_concurrency=1)
            results = await asyncio.gather(*[
                gateway.chat([{"role": "user", "content": "fixture"}], max_tokens=8)
                for _ in range(4)
            ])
        finally:
            server.close()
            await server.wait_closed()
        self.assertEqual(len(results), 4)
        self.assertEqual(counter.served, 4, "四个请求都要真的跑完，不该有被挤掉的")
        self.assertEqual(counter.max_inflight, 1,
                         "单槽端点同一时刻只能有一个请求在飞")

    async def test_unset_limit_keeps_requests_parallel(self) -> None:
        """未声明 `max_concurrency` 的端点行为不变：请求照旧并行。"""
        counter = _Counter()
        server = await _serve(counter, delay=0.15)
        port = server.sockets[0].getsockname()[1]
        try:
            gateway = _gateway(port, max_concurrency=0)
            await asyncio.gather(*[
                gateway.chat([{"role": "user", "content": "fixture"}], max_tokens=8)
                for _ in range(4)
            ])
        finally:
            server.close()
            await server.wait_closed()
        self.assertEqual(counter.served, 4)
        self.assertGreaterEqual(counter.max_inflight, 2,
                                "没声明上限就不该凭空串行化")

    async def test_queue_wait_does_not_burn_the_hard_timeout(self) -> None:
        """排队时间算在硬超时之外：每个请求 1.2s、硬超时 2s，串起来也不该超时。

        先打一次预热（SDK 首次调用要建 client、准备解析），再量两个并发请求——
        否则测的就不是排队，而是首次初始化的开销。
        """
        counter = _Counter()
        server = await _serve(counter, delay=1.2)
        port = server.sockets[0].getsockname()[1]
        try:
            gateway = _gateway(port, max_concurrency=1, timeout=2)
            await gateway.chat([{"role": "user", "content": "warmup"}], max_tokens=8)
            baseline = counter.served
            await asyncio.gather(*[
                gateway.chat([{"role": "user", "content": "fixture"}], max_tokens=8)
                for _ in range(2)
            ])
            served = counter.served - baseline
        finally:
            server.close()
            await server.wait_closed()
        self.assertEqual(served, 2, "排队久只是慢，不该被判超时后重发")
