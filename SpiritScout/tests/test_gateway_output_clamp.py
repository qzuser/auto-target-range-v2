"""输出上限收进模型窗口：小窗口端点不能因为「输入 + 输出」越界直接 400。"""
from __future__ import annotations

import asyncio
import json
import unittest

from spiritscout.config.settings import GatewayConfig, ModelEntry
from spiritscout.gateway.context import (
    OUTPUT_FLOOR_TOKENS,
    TOKEN_SAFETY_MIN,
    clamp_output_tokens,
    estimate_input_tokens,
)
from spiritscout.gateway.gateway import ModelGateway
from spiritscout.gateway.registry import ModelRegistry


class ClampOutputTokensTests(unittest.TestCase):
    def test_roomy_window_keeps_requested_budget(self) -> None:
        messages = [{"role": "user", "content": "短问题"}]
        self.assertEqual(clamp_output_tokens(messages, None, 32768, 1536), 1536)

    def test_tight_window_shrinks_output_so_input_plus_output_fits(self) -> None:
        messages = [{"role": "user", "content": "x" * 6000}]
        used = estimate_input_tokens(messages)
        clamped = clamp_output_tokens(messages, None, used + 512, 4096)
        self.assertIsNotNone(clamped)
        self.assertLessEqual(used + clamped, used + 512)
        self.assertGreater(clamped, 0)

    def test_overfull_input_still_gets_a_floor_budget(self) -> None:
        messages = [{"role": "user", "content": "y" * 40000}]
        self.assertEqual(clamp_output_tokens(messages, None, 1024, 2048),
                         OUTPUT_FLOOR_TOKENS)

    def test_output_floor_must_hold_a_multi_line_script(self) -> None:
        """保底必须够写一段完整脚本，不能只够写半行。

        本机实测：保底 128 token 时，模型每次都在 `for ...:` 的缩进块开头被
        切断，拿到 `IndentationError` 就回头重读源码，永远走不到结论。工具调用
        连 arguments 通常就要 200~600 token，保底不能低于 512。
        """
        self.assertGreaterEqual(OUTPUT_FLOOR_TOKENS, 512)

    def test_unknown_window_or_budget_is_left_alone(self) -> None:
        messages = [{"role": "user", "content": "fixture"}]
        self.assertEqual(clamp_output_tokens(messages, None, 0, 700), 700)
        self.assertIsNone(clamp_output_tokens(messages, None, 4096, None))

    def test_estimated_input_keeps_safety_margin(self) -> None:
        """估算偏低是真的会发生：8k 窗口里「估 8.1k、真 8.57k」直接 400。

        收口时必须比估算值再让出一截，否则估算一偏就又撞墙。"""
        messages = [{"role": "user", "content": "中文工具调用" * 400}]
        used = estimate_input_tokens(messages)
        window = used + 1200
        clamped = clamp_output_tokens(messages, None, window, 4096)
        self.assertIsNotNone(clamped)
        # 输出上限 + 估算输入 + 余量 必须落在窗口内，且余量至少 TOKEN_SAFETY_MIN
        self.assertLessEqual(used + clamped + TOKEN_SAFETY_MIN, window)

    def test_thirteen_percent_underestimate_still_fits(self) -> None:
        """本机实测：服务端数出 16425 token、窗口 16384，只超 41 就被判失败。

        服务端 tokenizer（Qwen BPE）对中文与代码比离线估算多算约 13%，
        留出的余量必须盖得住这点偏差，否则每跑几十回合都要撞一次墙。"""
        messages = [{"role": "system", "content": "契" * 1200},
                    {"role": "user", "content": "观察" * 2600},
                    {"role": "assistant", "content": "```python\nprint(1)\n```" * 400}]
        window = 16384
        clamped = clamp_output_tokens(messages, None, window, 3072)
        self.assertIsNotNone(clamped)
        estimated = estimate_input_tokens(messages)
        real = int(estimated * 1.13)
        self.assertLessEqual(real + clamped, window,
                             f"估 {estimated}、真 {real}、输出 {clamped}：真实总量超窗")


class SmallWindowHttpGatewayTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_body_never_asks_for_more_than_the_window(self) -> None:
        """4k 窗口的本地模型：输入已经占掉大半时，输出上限得跟着收。"""
        requests: list[dict] = []

        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                header = await reader.readuntil(b'\r\n\r\n')
                headers = dict(line.split(b':', 1) for line in header.split(b'\r\n')[1:] if b':' in line)
                size = int(next(value for key, value in headers.items()
                                if key.lower() == b'content-length'))
                requests.append(json.loads(await reader.readexactly(size)))
                result = {'id': 'local-clamp', 'object': 'chat.completion', 'created': 1,
                          'model': 'fixture',
                          'choices': [{'index': 0,
                                       'message': {'role': 'assistant', 'content': '{"ok": true}'},
                                       'finish_reason': 'stop'}],
                          'usage': {'prompt_tokens': 10, 'completion_tokens': 2,
                                    'total_tokens': 12}}
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
                               context_window=4096, max_output_tokens=2048)
            gateway = ModelGateway(ModelRegistry([entry]),
                                   config=GatewayConfig(request_timeout_seconds=10))
            messages = [{"role": "system", "content": "系统提示" * 60},
                        {"role": "user", "content": "任务正文" * 60}]
            response = await gateway.chat(messages, max_tokens=4096)
            self.assertEqual(response.content, '{"ok": true}')
            self.assertEqual(len(requests), 1)
            asked = requests[0].get('max_tokens')
            self.assertIsNotNone(asked, '请求必须显式带上收好的 max_tokens')
            self.assertLess(asked, 4096)
            self.assertGreater(asked, OUTPUT_FLOOR_TOKENS)
            # 真正发出去的那份消息 + 输出上限必须装得进窗口（压缩在前、收口在后）
            self.assertLessEqual(
                asked + estimate_input_tokens(requests[0]['messages'],
                                              requests[0].get('tools')), 4096)
        finally:
            server.close()
            await server.wait_closed()

    async def test_decision_path_with_preserve_context_still_clamps(self) -> None:
        """决策通道传 preserve_context=True：跳过压缩分支，也必须还能收口。

        这条路径就是 `UnboundLocalError: clamp_output_tokens` 的现场——import 写在
        压缩分支里，决策通道根本不进去，收口函数在运行时就成了未定义。
        """
        requests: list[dict] = []

        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                header = await reader.readuntil(b'\r\n\r\n')
                headers = dict(line.split(b':', 1) for line in header.split(b'\r\n')[1:] if b':' in line)
                size = int(next(value for key, value in headers.items()
                                if key.lower() == b'content-length'))
                requests.append(json.loads(await reader.readexactly(size)))
                result = {'id': 'local-clamp', 'object': 'chat.completion', 'created': 1,
                          'model': 'fixture',
                          'choices': [{'index': 0,
                                       'message': {'role': 'assistant', 'content': '{"ok": 1}'},
                                       'finish_reason': 'stop'}],
                          'usage': {'prompt_tokens': 10, 'completion_tokens': 2,
                                    'total_tokens': 12}}
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
                               context_window=4096, max_output_tokens=2048)
            gateway = ModelGateway(ModelRegistry([entry]),
                                   config=GatewayConfig(request_timeout_seconds=10))
            messages = [{'role': 'system', 'content': '系统提示' * 40},
                        {'role': 'user', 'content': '任务正文' * 40}]
            response = await gateway.chat(messages, max_tokens=4096, preserve_context=True)
            self.assertEqual(response.content, '{"ok": 1}')
            self.assertEqual(len(requests), 1)
            asked = requests[0].get('max_tokens')
            self.assertIsNotNone(asked)
            self.assertLessEqual(
                asked + estimate_input_tokens(requests[0]['messages'],
                                              requests[0].get('tools')), 4096)
        finally:
            server.close()
            await server.wait_closed()


class ToolArgumentTruncationRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_truncated_tool_arguments_retry_with_bigger_budget(self) -> None:
        """工具参数被截断：先在协议层回灌「截断」事实重发，再翻倍输出预算重发。

        这不是端点坏了：模型想写的参数比给它的额度长。回灌一次仍截断时，网关
        把输出预算翻倍再发一次，而不是把整轮判死。
        """
        requests: list[dict] = []

        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                header = await reader.readuntil(b'\r\n\r\n')
                headers = dict(line.split(b':', 1) for line in header.split(b'\r\n')[1:] if b':' in line)
                size = int(next(value for key, value in headers.items()
                                if key.lower() == b'content-length'))
                requests.append(json.loads(await reader.readexactly(size)))
                if len(requests) <= 2:
                    body = json.dumps({
                        'error': {'message': 'Failed to parse tool call arguments as JSON: '
                                             '[json.exception.parse_error.101] parse error at line 1,'
                                             ' column 412: invalid string: missing closing quote',
                                  'type': 'invalid_request_error'}}).encode()
                    writer.write(b'HTTP/1.1 500 Internal Server Error\r\n'
                                 b'Content-Type: application/json\r\nContent-Length: '
                                 + str(len(body)).encode() + b'\r\nConnection: close\r\n\r\n' + body)
                    await writer.drain()
                    return
                result = {'id': 'local-retry', 'object': 'chat.completion', 'created': 1,
                          'model': 'fixture',
                          'choices': [{'index': 0,
                                       'message': {'role': 'assistant', 'content': '{"ok": 1}'},
                                       'finish_reason': 'stop'}],
                          'usage': {'prompt_tokens': 12, 'completion_tokens': 3,
                                    'total_tokens': 15}}
                body = json.dumps(result, ensure_ascii=False).encode()
                writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: '
                             + str(len(body)).encode() + b'\r\nConnection: close\r\n\r\n' + body)
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(handle, '127.0.0.1', 0)
        try:
            port = server.sockets[0].getsockname()[1]
            entry = ModelEntry(model='fixture', provider='openai_compatible',
                               base_url=f'http://127.0.0.1:{port}/v1', api_key='local-test-only',
                               context_window=16384, max_output_tokens=3072)
            gateway = ModelGateway(ModelRegistry([entry]),
                                   config=GatewayConfig(request_timeout_seconds=10, max_retries=0))
            response = await gateway.chat([{'role': 'user', 'content': '写个脚本'}],
                                          max_tokens=512)
            self.assertEqual(response.content, '{"ok": 1}')
            self.assertGreaterEqual(len(requests), 3, '截断后必须重发')
            first, last = requests[0].get('max_tokens'), requests[-1].get('max_tokens')
            self.assertEqual(first, 512)
            self.assertGreater(last, first, '第二次重发必须放大输出预算')
            self.assertLessEqual(last, 3072, '放大后不能超过模型声明的输出上限')
        finally:
            server.close()
            await server.wait_closed()


if __name__ == '__main__':
    unittest.main()
