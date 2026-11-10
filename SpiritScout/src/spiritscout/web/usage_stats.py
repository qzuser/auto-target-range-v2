"""按模型汇总 token 用量：把各处的用量账本合成一张表。

用量按「谁记谁家账」落在多个 SQLite 账本里：控制台的命名/提炼/对话记在
``<工作区>/usage.db``，每个会话一开始也记在自己的 ``sessions/<id>/usage.db``，
并库之后同一笔会同时出现在两处——所以这里**按 ``call_id`` 去重**，同一笔只算一次。
统计页只读这些账本，按模型聚合调用次数、token（输入/输出/缓存读）与费用，
不参与调度、不改任何账。

口径（页面表头也这么写）：
- ``input`` 是本次调用的输入（**含**缓存命中部分），``cached`` 是其中命中提示词缓存
  的那一截；``new_input = input - cached`` 才是按原价计费的增量输入；
- ``tokens = input + output``，别把 ``cached`` 再加一遍，否则三列加不出合计。
"""
from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from spiritscout.gateway.usage import read_usage
from spiritscout.web.dashboard import BJT, start_of_period

PERIODS = ("hour", "today", "7d", "30d", "all")
UNKNOWN_MODEL = "未标注模型"
DAILY_POINTS_CAP = 90


def _ledger_files(cfg: Any) -> list[Path]:
    """所有可能有用量记录的账本入口（统一按 ``usage.json`` 形式返回）。

    ``read_usage`` 会优先找同名 ``usage.db``，所以传哪一半都行；这里把
    ``sessions/<id>/usage.db`` 也归一到 ``usage.json``，免得只有新式账本
    （旧 JSON 早被替换掉）的会话被漏掉。
    """
    root = Path(str(getattr(getattr(cfg, "workspace", None), "root", "") or ""))
    if not root.is_dir():
        return []
    files: list[Path] = []
    if (root / "usage.db").is_file() or (root / "usage.json").is_file():
        files.append(root / "usage.json")
    sessions = root / "sessions"
    if not sessions.is_dir():
        return files
    # 用 scandir：目录项的 stat 在扫描时就带回来了，别对每个会话再 is_file 两次
    # （每轮统计要做几十次系统调用，Windows 上一次 stat 就是 0.08 ms 量级）
    try:
        entries = list(os.scandir(sessions))
    except OSError:
        return files
    for entry in entries:
        try:
            if not entry.is_dir():
                continue
            names = {item.name for item in os.scandir(entry.path)}
        except OSError:
            continue
        if names & {"usage.json", "usage.db"}:
            files.append(Path(entry.path) / "usage.json")
    return files


def _empty_bucket(model: str) -> dict[str, Any]:
    return {"model": model, "calls": 0, "tokens": 0, "input": 0, "output": 0,
            "cached": 0, "new_input": 0, "usd": 0.0, "cny_min": 0.0, "cny_max": 0.0,
            "priced_calls": 0, "first_ts": 0.0, "last_ts": 0.0}


def _add(bucket: dict[str, Any], call: dict[str, Any]) -> None:
    tokens = int(call.get("tokens") or 0)
    bucket["calls"] += 1
    bucket["tokens"] += tokens
    bucket["input"] += int(call.get("input_tokens") or 0)
    bucket["output"] += int(call.get("output_tokens") or 0)
    cached = int(call.get("cached_input_tokens") or 0)
    bucket["cached"] += cached
    # 增量输入：按原价计费的那部分（缓存命中另算），保证 输入+输出=合计 之外
    # 还有一列能看出「这次真花了多少新 token」
    bucket["new_input"] += max(0, int(call.get("input_tokens") or 0) - cached)
    usd = float(call.get("cost_usd") or 0)
    bucket["usd"] += usd
    low = call.get("estimated_cost_cny_min")
    high = call.get("estimated_cost_cny_max")
    if isinstance(low, (int, float)):
        bucket["cny_min"] += float(low)
    if isinstance(high, (int, float)):
        bucket["cny_max"] += float(high)
    if usd > 0 or isinstance(low, (int, float)):
        bucket["priced_calls"] += 1
    ts = float(call.get("ts") or 0)
    if ts:
        bucket["first_ts"] = ts if not bucket["first_ts"] else min(bucket["first_ts"], ts)
        bucket["last_ts"] = max(bucket["last_ts"], ts)


def _iso(ts: float) -> str:
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(ts, BJT).strftime("%Y-%m-%d %H:%M")
    except (OSError, OverflowError, ValueError):
        return ""


def _day(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts, BJT).strftime("%Y-%m-%d")
    except (OSError, OverflowError, ValueError):
        return ""


def collect(cfg: Any, *, period: str = "7d", now: float | None = None) -> dict[str, Any]:
    """汇总一个时间窗内的用量：按模型分组，附带总量与日趋势。"""
    period = period if period in PERIODS else "7d"
    now = time.time() if now is None else now
    start = start_of_period(period, now)

    buckets: dict[str, dict[str, Any]] = {}
    daily: dict[str, dict[str, int]] = {}
    ledgers = 0
    total_calls = 0
    seen: set[str] = set()
    duplicated = 0
    for path in _ledger_files(cfg):
        snapshot = read_usage(path, readonly=True)   # 只读遍历，不必深拷贝整份序列
        if not snapshot:
            continue
        calls = snapshot.get("call_series") or []
        if not calls:
            continue
        ledgers += 1
        for call in calls:
            # 并库后同一笔会同时挂在会话账本和工作区账本上：按 call_id 只算一次
            call_id = str(call.get("call_id") or "")
            if call_id:
                if call_id in seen:
                    duplicated += 1
                    continue
                seen.add(call_id)
            ts = float(call.get("ts") or 0)
            if ts and ts < start:
                continue
            model = str(call.get("model") or "").strip() or UNKNOWN_MODEL
            bucket = buckets.setdefault(model, _empty_bucket(model))
            _add(bucket, call)
            total_calls += 1
            day = _day(ts) if ts else ""
            if day:
                slot = daily.setdefault(day, {"tokens": 0, "calls": 0, "input": 0, "output": 0})
                slot["tokens"] += int(call.get("tokens") or 0)
                slot["calls"] += 1
                slot["input"] += int(call.get("input_tokens") or 0)
                slot["output"] += int(call.get("output_tokens") or 0)

    total_tokens = sum(b["tokens"] for b in buckets.values())
    models: list[dict[str, Any]] = []
    for bucket in sorted(buckets.values(), key=lambda b: (-b["tokens"], b["model"])):
        item = dict(bucket)
        item["share"] = round(bucket["tokens"] / total_tokens, 4) if total_tokens else 0.0
        item["first_at"] = _iso(bucket["first_ts"])
        item["last_at"] = _iso(bucket["last_ts"])
        models.append(item)

    series = [{"date": day, **daily[day]} for day in sorted(daily)]
    input_tokens = sum(b["input"] for b in buckets.values())
    cached_tokens = sum(b["cached"] for b in buckets.values())
    totals = {
        "calls": total_calls,
        "tokens": total_tokens,
        "input": input_tokens,
        "output": sum(b["output"] for b in buckets.values()),
        # 含在 input 里的那部分，单列出来免得「输入+缓存」被误当成两笔
        "cached": cached_tokens,
        "new_input": sum(b["new_input"] for b in buckets.values()),
        "cache_rate": round(cached_tokens / input_tokens, 4) if input_tokens else 0.0,
        "usd": round(sum(b["usd"] for b in buckets.values()), 6),
        "cny_min": round(sum(b["cny_min"] for b in buckets.values()), 6),
        "cny_max": round(sum(b["cny_max"] for b in buckets.values()), 6),
        "priced_calls": sum(b["priced_calls"] for b in buckets.values()),
        "models": len(models),
        "unpriced_calls": total_calls - sum(b["priced_calls"] for b in buckets.values()),
    }
    return {
        "period": period,
        "range_start": start,
        "range_start_at": _iso(start) if start else "",
        "generated_at": now,
        "timezone": "Asia/Shanghai",
        "ledgers": ledgers,
        # 并库里重复出现的笔数（去重后不计入上面的合计），排查账本问题时有据可查
        "duplicated_calls": duplicated,
        "totals": totals,
        "models": models,
        "daily": series[-DAILY_POINTS_CAP:],
    }
