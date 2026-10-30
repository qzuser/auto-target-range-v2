"""本地 LLM 的 MCP 服务器：把本机推理端点接成一组工具。

模型跑在自己机器上，提问不出网、不计费，适合拿它做摘要、改写、批量分类这类
廉价活，把贵的云端模型留给真正需要判断的环节。后端走 OpenAI 兼容协议，LM Studio
（默认 1234）和 Ollama（11434）都能直接对上：

    SPIRITSCOUT_LOCAL_LLM_URL=http://127.0.0.1:11434/v1   # Ollama
    SPIRITSCOUT_LOCAL_LLM_URL=http://127.0.0.1:1234/v1    # LM Studio（默认）

开关在控制台「设置 → MCP 接入」里：``local-llm`` 这条的启用状态决定它是否并入
agent 的工具目录，改完即生效。

连不上时不留一个光秃秃的 URLError：``_fail`` 会把「后端没起」和「地址配错」分开说，
并给出对应的下一步命令。
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any

DEFAULT_BASE_URL = "http://127.0.0.1:1234/v1"
DEFAULT_TIMEOUT = 120.0
MAX_PROMPT_CHARS = 24000
MAX_OUTPUT_TOKENS = 8192
DEFAULT_MAX_TOKENS = 512
DEFAULT_TEMPERATURE = 0.2

#: 无参工具的 inputSchema，三处共用一份。
NO_ARGS: dict[str, Any] = {"type": "object", "properties": {}, "additionalProperties": False}

SERVER_INFO = {"name": "local-llm", "version": "1.0.0"}


def base_url() -> str:
    """端点地址；尾部斜杠一律去掉，避免拼出 ``//chat/completions``。"""
    return (os.environ.get("SPIRITSCOUT_LOCAL_LLM_URL") or DEFAULT_BASE_URL).rstrip("/")


def timeout_seconds() -> float:
    try:
        value = float(os.environ.get("SPIRITSCOUT_LOCAL_LLM_TIMEOUT", ""))
    except ValueError:
        return DEFAULT_TIMEOUT
    return value if value > 0 else DEFAULT_TIMEOUT


def default_model() -> str:
    return os.environ.get("SPIRITSCOUT_LOCAL_LLM_MODEL", "").strip()


def _request(path: str, payload: dict[str, Any] | None = None) -> Any:
    """只发本机请求：端点是用户自己配的，不做代理与重定向跟随。"""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    token = os.environ.get("SPIRITSCOUT_LOCAL_LLM_KEY", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(f"{base_url()}{path}", data=data, headers=headers,
                                     method="POST" if data else "GET")
    with urllib.request.urlopen(request, timeout=timeout_seconds()) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def _fail(exc: Exception) -> str:
    """把连不上的原因说清楚——这条路最常见的故障就是后端没起。

    ``HTTPError`` 是 ``URLError`` 的子类，必须先判：否则端点明明返回了 400，
    也会被说成"连不上、后端起没起"。
    """
    if isinstance(exc, urllib.error.HTTPError):
        detail = exc.read().decode("utf-8", "replace")[:300]
        return f"本地端点返回 {exc.code}：{detail}"
    if isinstance(exc, urllib.error.URLError):
        reason = str(exc.reason).rstrip("。. ")
        return (f"连不上本地推理端点 {base_url()}：{reason}。"
                "先在 LM Studio 里点 Start Server（或 `lms server start`），"
                "Ollama 则是 `ollama serve`；端点不对就改 SPIRITSCOUT_LOCAL_LLM_URL。")
    return f"调用本地端点失败：{exc}"


def list_models() -> list[str]:
    data = _request("/models")
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    names = [str(row.get("id", "")).strip() for row in rows if isinstance(row, dict)]
    return [name for name in names if name]


def server_status() -> dict[str, Any]:
    """端点是否在线、有哪些模型、往返多少毫秒。"""
    started = time.monotonic()
    try:
        models = list_models()
    except Exception as exc:  # noqa: BLE001 - 把底层异常翻成人话，不吞栈
        return {"online": False, "endpoint": base_url(), "error": _fail(exc), "models": []}
    return {
        "online": True,
        "endpoint": base_url(),
        "latency_ms": round((time.monotonic() - started) * 1000),
        "models": models,
        "default_model": default_model() or (models[0] if models else ""),
    }


def _post_chat(payload: dict[str, Any]) -> Any:
    """发一次补全；端点不认 ``chat_template_kwargs`` 就摘掉重发，别让整次调用白费。"""
    try:
        return _request("/chat/completions", payload)
    except urllib.error.HTTPError as exc:
        if exc.code >= 500 or "chat_template_kwargs" not in payload:
            raise
        payload.pop("chat_template_kwargs", None)
        return _request("/chat/completions", payload)


def _resolve_model(model: str) -> tuple[str, str]:
    """挑一个模型名。返回 (模型名, 错误消息)，两者恰有一个非空。"""
    picked = (model or "").strip() or default_model()
    if picked:
        return picked, ""
    try:
        available = list_models()
    except Exception as exc:  # noqa: BLE001 - 同上，报错要能指导下一步
        return "", _fail(exc)
    if not available:
        return "", f"端点 {base_url()} 上没有可用模型，先在 LM Studio 里加载一个"
    return available[0], ""


def _extract(data: Any) -> tuple[str, str, str]:
    """从 OpenAI 兼容响应里取 (正文, 思考内容, 结束原因)。"""
    choices = data.get("choices") if isinstance(data, dict) else None
    first = choices[0] if isinstance(choices, list) and choices else None
    first = first if isinstance(first, dict) else {}
    message = first.get("message")
    message = message if isinstance(message, dict) else {}
    return (str(message.get("content") or ""),
            str(message.get("reasoning_content") or ""),
            str(first.get("finish_reason") or ""))


def chat(prompt: str, system: str = "", model: str = "",
         max_tokens: int = DEFAULT_MAX_TOKENS, temperature: float = DEFAULT_TEMPERATURE,
         thinking: bool = False) -> dict[str, Any]:
    """单轮补全。返回正文与用量，正文超长按 max_tokens 截断。

    推理模型（Gemma 4 这类）默认会先"想"一大段再开口，纯 CPU 上这一点能吃掉几十秒：
    实测同一句「1+1」开着思考要 51 秒、关掉只要 4 秒。所以默认发
    ``chat_template_kwargs.enable_thinking = false``，需要推理过程时再用 ``thinking`` 打开。
    """
    text = (prompt or "").strip()
    if not text:
        return {"ok": False, "error": "prompt 不能为空"}
    if len(text) > MAX_PROMPT_CHARS:
        return {"ok": False,
                "error": f"prompt 超过 {MAX_PROMPT_CHARS} 字符，本地小模型的上下文装不下，先自己截一段"}
    picked, problem = _resolve_model(model)
    if problem:
        return {"ok": False, "error": problem}
    messages: list[dict[str, str]] = []
    if system.strip():
        messages.append({"role": "system", "content": system.strip()})
    messages.append({"role": "user", "content": text})
    payload: dict[str, Any] = {
        "model": picked,
        "messages": messages,
        "max_tokens": max(1, min(int(max_tokens), MAX_OUTPUT_TOKENS)),
        "temperature": max(0.0, min(float(temperature), 2.0)),
        "stream": False,
    }
    if not thinking:
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    started = time.monotonic()
    try:
        data = _post_chat(payload)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": _fail(exc)}
    content, reasoning, finish = _extract(data)
    usage = data.get("usage") if isinstance(data, dict) else None
    result: dict[str, Any] = {
        "ok": bool(content),
        "model": picked,
        "text": content,
        "elapsed_ms": round((time.monotonic() - started) * 1000),
        "usage": usage if isinstance(usage, dict) else {},
    }
    if finish:
        result["finish_reason"] = finish
    if not content and reasoning:
        # 推理模型把额度全用在思考上时，正文就是空的——直说，别让人以为模型坏了。
        result["hint"] = (f"模型只产出了 {len(reasoning)} 字符的思考内容，正文被 max_tokens 截断；"
                          "调大 max_tokens，或保持 thinking=false。")
    return result


TOOLS: list[dict[str, Any]] = [
    {
        "name": "local_llm_status",
        "description": ("检查本机 LLM 端点是否在线、有哪些模型、往返延迟。"
                        "调用本地模型前先用它确认后端起着。"),
        "inputSchema": NO_ARGS,
    },
    {
        "name": "local_llm_models",
        "description": "列出本机已加载 / 可用的模型名，用来挑 local_llm_chat 的 model 参数。",
        "inputSchema": NO_ARGS,
    },
    {
        "name": "local_llm_chat",
        "description": ("向本机模型提一个单轮问题，返回纯文本。模型跑在本地：不出网、"
                        "不计费，适合摘要、改写、批量分类这类廉价活。默认不让推理模型"
                        "先思考（纯 CPU 上思考能吃掉几十秒）。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "要问的内容"},
                "system": {"type": "string", "description": "可选的系统提示"},
                "model": {"type": "string", "description": "模型名；留空用默认或第一个可用模型"},
                "max_tokens": {"type": "integer", "description": "输出上限，默认 512，最多 8192"},
                "temperature": {"type": "number", "description": "采样温度，默认 0.2"},
                "thinking": {"type": "boolean",
                             "description": "要不要让推理模型先思考，默认 false；慢很多，只在确实需要推理过程时开"},
            },
            "required": ["prompt"],
            "additionalProperties": False,
        },
    },
]


def _as_number(value: Any, cast: type, fallback: Any) -> Any:
    """转不动就退回默认——模型给的参数经常是字符串。"""
    try:
        return cast(value)
    except (TypeError, ValueError):
        return fallback


def _as_bool(value: Any, fallback: bool = False) -> bool:
    """模型常把布尔写成字符串，而 ``bool("false")`` 是 True——按字面意思判。"""
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if value is None:
        return fallback
    return bool(value)


def call_tool(name: str, arguments: dict[str, Any]) -> Any:
    """把工具名分派到实现。参数一律先做类型兜底，坏参数退回默认值。"""
    if name == "local_llm_status":
        return server_status()
    if name == "local_llm_models":
        try:
            return {"ok": True, "models": list_models(), "endpoint": base_url()}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": _fail(exc)}
    if name == "local_llm_chat":
        args = arguments or {}
        return chat(
            str(args.get("prompt", "")),
            system=str(args.get("system", "")),
            model=str(args.get("model", "")),
            max_tokens=_as_number(args.get("max_tokens"), int, DEFAULT_MAX_TOKENS),
            temperature=_as_number(args.get("temperature"), float, DEFAULT_TEMPERATURE),
            thinking=_as_bool(args.get("thinking")),
        )
    raise ValueError(f"未知工具：{name}")


def _write(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _result(request_id: Any, result: Any) -> None:
    _write({"jsonrpc": "2.0", "id": request_id, "result": result})


def _error(request_id: Any, code: int, message: str) -> None:
    _write({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})


def _call(request_id: Any, params: dict[str, Any]) -> None:
    """跑一个工具并回写结果：工具自身失败也回结构化错误，连接不能断。"""
    name = str(params.get("name", ""))
    try:
        output = call_tool(name, params.get("arguments") or {})
    except ValueError as exc:
        _error(request_id, -32602, str(exc))
        return
    except Exception as exc:  # noqa: BLE001 - 工具崩了也要给客户端一个交代
        _result(request_id, {"content": [{"type": "text", "text": f"工具执行失败：{exc}"}],
                             "isError": True})
        return
    _result(request_id, {"content": [{"type": "text",
                                      "text": json.dumps(output, ensure_ascii=False)}]})


def main() -> int:
    """stdio JSON-RPC 循环。stdout 只承载协议，日志一律走 stderr。"""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            print(f"[local-llm MCP] 收到非 JSON 输入：{exc}", file=sys.stderr)
            continue
        if not isinstance(message, dict):
            print("[local-llm MCP] 报文必须是 JSON 对象，已跳过", file=sys.stderr)
            continue
        method = message.get("method", "")
        request_id = message.get("id")
        params = message.get("params")
        params = params if isinstance(params, dict) else {}
        if method == "initialize":
            _result(request_id, {
                "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            })
        elif method in {"notifications/initialized", "initialized"}:
            continue
        elif method == "tools/list":
            _result(request_id, {"tools": TOOLS})
        elif method == "tools/call":
            _call(request_id, params)
        elif method == "ping":
            _result(request_id, {})
        elif request_id is not None:
            _error(request_id, -32601, f"不支持的方法：{method}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
