"""端点熔断：连续全链失败后必须快速失败并抛可识别异常，别让上层继续堆任务。"""
from __future__ import annotations

import asyncio
import json
import socket
import time
import unittest

from spiritscout.config.settings import GatewayConfig, ModelEntry
from spiritscout.core.exceptions import SpiritScoutError
from spiritscout.gateway.gateway import (
    MODEL_BREAKER_THRESHOLD,
    ModelGateway,
    ModelUnavailableError,
)
from spiritscout.gateway.registry import ModelRegistry


def _closed_port() -> int:
    """拿一个刚关掉的端口：连接会被立刻拒绝，制造稳定失败。"""
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class ModelBreakerTests(unittest.IsolatedAsyncioTestCase):
    async def test_breaker_trips_after_threshold_and_then_fails_fast(self) -> None:
        port = _closed_port()
        entry = ModelEntry(model='unreachable', provider='openai_compatible',
                           base_url=f'http://127.0.0.1:{port}/v1', api_key='local-test-only',
                           context_window=8192, max_output_tokens=256)
        gateway = ModelGateway(ModelRegistry([entry]),
                               config=GatewayConfig(request_timeout_seconds=2, max_retries=0))
        messages = [{'role': 'user', 'content': 'fixture'}]

        # 前两次失败只是普通全链失败，还没到熔断线
        for _ in range(MODEL_BREAKER_THRESHOLD - 1):
            with self.assertRaises(SpiritScoutError) as plain:
                await gateway.chat(messages, max_tokens=64)
            self.assertNotIsInstance(plain.exception, ModelUnavailableError)

        # 第三次触发熔断
        with self.assertRaises(ModelUnavailableError):
            await gateway.chat(messages, max_tokens=64)

        # 熔断期间：立刻失败，不再去碰端点（< 1 秒）
        started = time.perf_counter()
        with self.assertRaises(ModelUnavailableError):
            await gateway.chat(messages, max_tokens=64)
        self.assertLess(time.perf_counter() - started, 1.0)


class ModelBreakerResetTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_clears_failure_count(self) -> None:
        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                header = await reader.readuntil(b'\r\n\r\n')
                headers = dict(line.split(b':', 1) for line in header.split(b'\r\n')[1:] if b':' in line)
                size = int(next(value for key, value in headers.items()
                                if key.lower() == b'content-length'))
                await reader.readexactly(size)
                result = {'id': 'local-ok', 'object': 'chat.completion', 'created': 1,
                          'model': 'fixture',
                          'choices': [{'index': 0,
                                       'message': {'role': 'assistant', 'content': '{"ok": 1}'},
                                       'finish_reason': 'stop'}],
                          'usage': {'prompt_tokens': 5, 'completion_tokens': 1,
                                    'total_tokens': 6}}
                data = json.dumps(result, ensure_ascii=False).encode()
                writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: '
                             + str(len(data)).encode() + b'\r\nConnection: close\r\n\r\n' + data)
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(handle, '127.0.0.1', 0)
        try:
            port = server.sockets[0].getsockname()[1]
            entry = ModelEntry(model='fixture', provider='openai_compatible',
                               base_url=f'http://127.0.0.1:{port}/v1', api_key='local-test-only',
                               context_window=8192, max_output_tokens=256)
            gateway = ModelGateway(ModelRegistry([entry]),
                                   config=GatewayConfig(request_timeout_seconds=5))
            gateway._breaker_failures = 2                 # 之前抖过两下
            gateway._breaker_open_until = 0.0
            response = await gateway.chat([{'role': 'user', 'content': 'fixture'}], max_tokens=32)
            self.assertEqual(response.content, '{"ok": 1}')
            self.assertEqual(gateway._breaker_failures, 0)
            self.assertEqual(gateway._breaker_last_error, '')
        finally:
            server.close()
            await server.wait_closed()


if __name__ == '__main__':
    unittest.main()
