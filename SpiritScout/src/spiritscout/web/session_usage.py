"""会话视图的用量：把「属于本会话的调用」从共享账本里认回来。

会话页原来只读 `sessions/<id>/usage.db`，可运行期的逐笔调用大多落在了工作区
共享账本（`usage.json/usage.db`）里——于是同一场任务，用量页显示几百万 token，
会话页只显示几百。两个数字都是"真读数"，错的是**归属**：会话台账里没有它会话
的调用，而共享账本里的行本身不带 session_id。

可靠的归属凭据是**会话自己的审计流**：每次模型调用都会在本会话 `audit.jsonl`
留下 `model.call`（含 `call_id`），共享账本每一行也有同一个 `call_id`。按
`call_id` 取交集即可——不做时间窗猜测，也不按 actor 前缀猜。

这里只做三件事：增量扫审计拿 call_id 集合、把共享账本里命中的行并进会话用量、
按并后的序列重算总量。审计扫描按追加位点增量推进，轮询不会反复读整份日志。
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from spiritscout.gateway.cache import cache_summary
from spiritscout.gateway.usage import file_version, read_usage

MODEL_EVENTS = frozenset({"model.call", "model.failed", "model.cancelled"})
# 会话目录的父目录名：`<工作区根>/sessions/<会话 id>` 才推得出共享账本位置
SESSIONS_DIRNAME = "sessions"


@dataclass
class _AuditIndex:
    """一份审计文件的增量视图：位点 + 已见 call_id。"""

    offset: int = 0
    version: tuple[Any, ...] = ()
    ids: set[str] = field(default_factory=set)


_LOCK = threading.Lock()
_CACHE: dict[str, _AuditIndex] = {}


def _reset(entry: _AuditIndex) -> None:
    entry.offset = 0
    entry.ids = set()


def audit_call_ids(path: Path) -> set[str]:
    """会话审计里出现过的模型调用 call_id（按追加位点增量更新）。

    文件被替换（mtime/inode/size 变短）时从头重读；解析不了的行跳过——审计里
    有半行是常态，不能因此丢掉其余调用。
    """
    key = str(path)
    version = file_version(path)
    with _LOCK:
        entry = _CACHE.get(key)
        if entry is None:
            entry = _CACHE[key] = _AuditIndex()
            _reset(entry)
        if not version:
            return set(entry.ids)
        if entry.version and (entry.version[:3] != version[:3] or version[2] < entry.offset):
            _reset(entry)
        if entry.version == version:
            return set(entry.ids)
        start = entry.offset
    try:
        with path.open("rb") as stream:
            stream.seek(start)
            while True:
                line = stream.readline()
                if not line or not line.endswith(b"\n"):
                    break                      # 半行不消费，下次接着读
                try:
                    event = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    continue
                if not isinstance(event, dict) or event.get("type") not in MODEL_EVENTS:
                    continue
                detail = event.get("detail")
                call_id = detail.get("call_id") if isinstance(detail, dict) else None
                if call_id:
                    with _LOCK:
                        _CACHE[key].ids.add(str(call_id))
            end = stream.tell()
    except OSError:
        return set(entry.ids)
    with _LOCK:
        current = _CACHE.get(key)
        if current is not None:
            current.offset, current.version = end, version
            return set(current.ids)
    return set()


def workspace_root(workspace: Path) -> Path | None:
    """会话工作区推工作区根（`<root>/sessions/<id>` → `<root>`）；推不出就是 None。"""
    workspace = Path(workspace)
    if workspace.parent.name == SESSIONS_DIRNAME:
        return workspace.parent.parent
    return None


def merge_usage(local: dict[str, Any], extra: list[dict[str, Any]]) -> dict[str, Any]:
    """把额外调用并进会话用量，并按并后的序列重算总量（不改传入的字典）。"""
    base = dict(local or {})
    series = list(base.get("call_series") or [])
    if not extra:
        return base
    seen = {str(row.get("call_id") or "") for row in series}
    added = [row for row in extra if str(row.get("call_id") or "") not in seen]
    if not added:
        return base
    series.extend(added)
    per_model = dict(base.get("per_model_tokens") or {})
    per_mode = dict(base.get("per_mode_tokens") or {})
    for row in added:
        tokens = int(row.get("tokens") or 0)
        model = str(row.get("model") or "")
        if model:
            per_model[model] = per_model.get(model, 0) + tokens
        mode = str(row.get("mode") or "")
        if mode:
            per_mode[mode] = per_mode.get(mode, 0) + tokens
    base["merged_calls"] = len(added)
    base.update({
        "call_series": series,
        "used_tokens": int(base.get("used_tokens") or 0)
        + sum(int(row.get("tokens") or 0) for row in added),
        "used_usd": float(base.get("used_usd") or 0.0)
        + sum(float(row.get("cost_usd") or 0.0) for row in added),
        "calls": max(int(base.get("calls") or 0), len(series) - len(added)) + len(added),
        "per_model_tokens": per_model,
        "per_mode_tokens": per_mode,
        "mode": str(base.get("mode") or "") or (str(added[-1].get("mode") or "") or base.get("mode", "")),
        "cache": cache_summary(series),
    })
    return base


@dataclass
class _Merged:
    version: tuple[Any, ...]
    usage: dict[str, Any]


_MERGED: dict[str, _Merged] = {}
_MERGED_CAP = 64


def _merged_cache(key: str, version: tuple[Any, ...]) -> dict[str, Any] | None:
    with _LOCK:
        hit = _MERGED.get(key)
        return hit.usage if hit is not None and hit.version == version else None


def _remember(key: str, version: tuple[Any, ...], usage: dict[str, Any]) -> None:
    with _LOCK:
        if len(_MERGED) >= _MERGED_CAP:
            _MERGED.clear()             # 工作区会话有限，清了重建也不会反复重建
        _MERGED[key] = _Merged(version, usage)


def session_usage(workspace: Path, audit_path: Path, *, root: Path | None = None,
                  fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    """本会话的用量视图：会话账本 ∪ 共享账本里 `call_id` 命中的行。

    ``fallback`` 是账本读不出来时用的运行汇总快照（历史会话），照样并入共享
    账本的行——旧账本缺失不该让会话页退回"只有几百 token"的旧口径。
    """
    local_path = Path(workspace) / "usage.json"
    shared_root = root if root is not None else workspace_root(workspace)
    if shared_root is None:
        local = read_usage(local_path, readonly=True)
        return dict(local if local is not None else (fallback or {}))

    # 会话台账、共享账本、审计流三者任一变了才重算；轮询里这一步只有几次 stat
    shared_path = Path(shared_root) / "usage.json"
    version = (file_version(local_path), file_version(shared_path.with_suffix(".db")),
               file_version(Path(str(shared_path.with_suffix(".db")) + "-wal")),
               file_version(Path(audit_path)))
    key = f"{workspace}|{fallback is not None}"
    hit = _merged_cache(key, version)
    if hit is not None:
        return hit

    local = read_usage(local_path, readonly=True)
    if local is None:
        local = dict(fallback or {})
    ids = audit_call_ids(Path(audit_path))
    shared = read_usage(shared_path, readonly=True) if ids else None
    if not ids or not shared:
        _remember(key, version, dict(local))
        return dict(local)
    extra = [row for row in (shared.get("call_series") or [])
             if str(row.get("call_id") or "") in ids]
    merged = merge_usage(local, extra)
    # shared_calls = 共享账本里命中的行数；merged_calls = 其中真正并进来的（去重后）
    merged["shared_calls"] = len(extra)
    _remember(key, version, merged)
    return merged
