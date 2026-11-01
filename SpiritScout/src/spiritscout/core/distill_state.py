"""进程内「哪个会话正在提炼经验」登记表。

提炼有两条入口——会话收尾后的自动提炼（``runtime._distill_run``）与会话页的
手动提炼——但两者都经过 ``runtime._distill_experience``，所以登记放在那一层，
一次覆盖两条路。控制台据此刻「提炼中」徽标；它不落库、不跨进程，重启即清空。

嵌套调用按引用计数回收：外层还在提炼时内层退出不能提前把徽标抹掉。
"""
from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

_LOCK = threading.Lock()
_ACTIVE: dict[str, int] = {}


@contextmanager
def tracked(session_id: str) -> Iterator[None]:
    """在 with 体内把该会话标记为「正在提炼」，退出（含异常）即摘掉。"""
    key = str(session_id or "")
    if key:
        with _LOCK:
            _ACTIVE[key] = _ACTIVE.get(key, 0) + 1
    try:
        yield
    finally:
        if key:
            with _LOCK:
                left = _ACTIVE.get(key, 0) - 1
                if left > 0:
                    _ACTIVE[key] = left
                else:
                    _ACTIVE.pop(key, None)


def active(session_id: str) -> bool:
    """该会话此刻是否正在提炼。"""
    with _LOCK:
        return _ACTIVE.get(str(session_id or ""), 0) > 0


def active_ids() -> set[str]:
    """正在提炼的会话集合（仪表盘/列表排查用）。"""
    with _LOCK:
        return set(_ACTIVE)
