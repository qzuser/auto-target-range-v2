"""控制台提醒：解出的题与等人回答的问题。

前端每十几秒拉一次 ``/api/notifications``，按 ``id`` 去重后弹系统通知：

* ``solved``   —— 会话目录 ``flags.json`` 里 ``accepted is True`` 的 Flag。落盘
  数据，控制台重启后依然成立；
* ``question`` —— 会话内待答队列 ``QuestionBroker.view()``，与界面上的提问卡
  同源。它是进程内状态，重启即清空，这里不假装还在。

只算「此刻有什么值得叫醒用户」，不记录已读、不写盘：提醒过一次就该安静，
那是客户端 seen 集合的事——多标签页各有各的屏，不该在服务端互相压制。

读盘一律容错：文件缺失、半截 JSON、字段类型不对都当作没有这条，一条坏记录
不能把整轮提醒打断。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

KIND_SOLVED = "solved"
KIND_QUESTION = "question"
# 一次最多推这么多条：控制台开着几十个会话时，别让一个响应把人埋了
MAX_ITEMS = 60
VALUE_PREVIEW = 32
QUESTION_PREVIEW = 160
# flags.json 解析缓存：轮询每十几秒一次，50 个会话不该每轮都重读一遍磁盘。
# 键是 (mtime, 大小)——只看 mtime 会漏掉同一时钟刻度内的两次写（Windows 上是
# 100ns 精度，但同一落盘批次里确实能撞上）；满了就丢最早的一条，不整表清空。
_CACHE: dict[str, tuple[tuple[float, int], list[dict[str, Any]]]] = {}
_CACHE_MAX = 512


def _preview(text: Any, limit: int) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _digest(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8", "replace")).hexdigest()[:10]


def read_accepted_flags(flags_path: Path) -> list[dict[str, Any]]:
    """``flags.json`` → 已被平台判定正确的 Flag（未判定、判错都不算解出）。"""
    path = Path(flags_path)
    try:
        stat = path.stat()
    except OSError:
        return []
    stamp = (stat.st_mtime, stat.st_size)
    key = str(path)
    cached = _CACHE.get(key)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = []
    accepted: list[dict[str, Any]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or item.get("accepted") is not True:
            continue
        value = str(item.get("value") or "")
        accepted.append({
            "flag_id": str(item.get("flag_id") or "") or _digest(value),
            "challenge_id": str(item.get("challenge_id") or ""),
            "value": value,
            "found_by": str(item.get("found_by") or ""),
        })
    while len(_CACHE) >= _CACHE_MAX:
        _CACHE.pop(next(iter(_CACHE)), None)
    _CACHE.pop(key, None)          # 重新插到队尾，让热点条目最后被淘汰
    _CACHE[key] = (stamp, accepted)
    return accepted


def solved_items(session: Any) -> list[dict[str, Any]]:
    """一个会话里解出来的题，转成待提醒条目。"""
    session_id = str(getattr(session, "session_id", "") or "")
    if not session_id:
        return []
    flags_path = getattr(session, "flags_path", None)
    if flags_path is None:
        workspace = getattr(session, "workspace", None)
        if workspace is None:
            return []
        flags_path = Path(workspace) / "flags.json"
    # 先判有没有解出的题：绝大多数会话这一轮是空的，别为它们多 stat 一次、
    # 也别去格式化标题
    accepted = read_accepted_flags(flags_path)
    if not accepted:
        return []
    try:
        at = Path(flags_path).stat().st_mtime
    except OSError:
        at = 0.0
    title = _session_title(session)
    items: list[dict[str, Any]] = []
    for flag in accepted:
        challenge = flag["challenge_id"] or "未标注题目"
        value = _preview(flag["value"], VALUE_PREVIEW)
        items.append({
            "id": f"flag:{session_id}:{flag['flag_id']}",
            "kind": KIND_SOLVED,
            "session_id": session_id,
            "session_title": title,
            "mode": str(getattr(session, "mode", "") or ""),
            "title": "解出一道题",
            "body": f"{challenge} · {value}" if value else challenge,
            "at": at,
            "detail": {"challenge_id": flag["challenge_id"],
                       "value_preview": value,
                       "found_by": flag["found_by"]},
        })
    return items


def question_items(session: Any) -> list[dict[str, Any]]:
    """一个会话里还挂着的提问，转成待提醒条目。"""
    session_id = str(getattr(session, "session_id", "") or "")
    broker = getattr(session, "questions", None)
    view = getattr(broker, "view", None)
    if not session_id or not callable(view):
        return []
    try:
        pending = view()
    except Exception:  # noqa: BLE001 —— 提醒是旁路，读不到就当没有
        return []
    if not isinstance(pending, list) or not pending:
        return []
    title = _session_title(session)
    items: list[dict[str, Any]] = []
    for record in pending:
        if not isinstance(record, dict):
            continue
        question_id = str(record.get("question_id") or "")
        if not question_id:
            continue
        question = _preview(record.get("question"), QUESTION_PREVIEW)
        options = record.get("options") if isinstance(record.get("options"), list) else []
        try:
            at = float(record.get("requested_at") or 0.0)
        except (TypeError, ValueError):
            at = 0.0
        items.append({
            "id": f"ask:{session_id}:{question_id}",
            "kind": KIND_QUESTION,
            "session_id": session_id,
            "session_title": title,
            "mode": str(getattr(session, "mode", "") or ""),
            "title": "灵枢在等你回答",
            "body": question or "有一个问题需要你拍板",
            "at": at,
            "detail": {"agent": str(record.get("agent") or ""),
                       "options": [_preview(opt, 60) for opt in options[:6]],
                       "multiple": bool(record.get("multiple"))},
        })
    return items


def _session_title(session: Any) -> str:
    display = getattr(session, "display_title", None)
    if callable(display):
        try:
            return str(display() or "")
        except Exception:  # noqa: BLE001
            return ""
    return str(getattr(session, "title", "") or "")


def snapshot(sessions: Iterable[Any]) -> dict[str, Any]:
    """此刻值得提醒的条目 + 计数 + 一个可比的 revision。

    ``revision`` 只由条目 id 决定：客户端拿它跟自己上次的比，一样就直接
    跳过——省掉逐条比对，也不影响「有没有新东西」的判断。
    """
    items: list[dict[str, Any]] = []
    for session in sessions or []:
        items.extend(question_items(session))
        items.extend(solved_items(session))
    # 新的在前；没有时间戳的（极少）排最后，靠 id 保证顺序稳定
    items.sort(key=lambda item: (float(item.get("at") or 0.0), item["id"]), reverse=True)
    counts = {KIND_SOLVED: 0, KIND_QUESTION: 0}
    for item in items:
        counts[item["kind"]] = counts.get(item["kind"], 0) + 1
    revision = hashlib.sha1(
        "|".join(sorted(item["id"] for item in items)).encode("utf-8")).hexdigest()[:16]
    shown = items[:MAX_ITEMS]
    return {"items": shown, "counts": counts, "revision": revision,
            # 计数是全部条目的实数，items 只给最近的一批；差出来的部分由客户端
            # 折成一条汇总，别让人以为「就这些」
            "truncated": len(items) > len(shown)}
