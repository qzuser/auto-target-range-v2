"""端点凭据判定：谁能真的打出去，谁得先去「模型」页补密钥。

LiteLLM 拿到 `openai/` 前缀的模型时**必须有 api_key**，否则在发请求之前
就抛 `Missing credentials`。本机端点（LM Studio / Ollama 之类）本来就不校验
密钥，但 litellm 仍要求非空，所以统一给一个占位密钥。
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

# litellm 只检查非空，值是什么无所谓；固定字符串便于日志里辨认
LOCAL_PLACEHOLDER_KEY = "sk-local"

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


def is_local(base_url: str) -> bool:
    """端点是否在本机（含 127.0.0.0/8 与 *.local）。"""
    host = (urlsplit(base_url or "").hostname or "").lower()
    if not host:
        return False
    return host in _LOCAL_HOSTS or host.startswith("127.") or host.endswith(".local")


def api_key_for(entry: Any) -> str:
    """该条目实际要用的密钥；本机端点无密钥时给占位，远端无密钥返回空串。"""
    key = str(getattr(entry, "api_key", "") or "").strip()
    if key:
        return key
    return LOCAL_PLACEHOLDER_KEY if is_local(str(getattr(entry, "base_url", "") or "")) else ""


def is_usable(entry: Any) -> bool:
    """能不能直接调用：有密钥，或者是本机端点（占位密钥够用）。"""
    return bool(api_key_for(entry))
