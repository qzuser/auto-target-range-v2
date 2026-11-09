"""经验合并（absorb）：把选中的经验并入已有条目，**一条都不删**。

与「二次提炼」的分工：

================  ======================================  ==========================
功能              做什么                                  对原始条目
================  ======================================  ==========================
二次提炼 merge    组内极相似 → 提炼成一条新条目           确认后**删除**原件
合并 absorb       交给模型判断能不能并进某条已有经验      只更新目标条目，原件**全部保留**
================  ======================================  ==========================

合并的硬约束（对应「不能删除任何经验」）：

1. 只做 ``UPDATE``，任何路径都不出现 ``DELETE``；
2. 模型给的目标必须落在本次候选集内（候选集来自库里的有效条目，且排除被选中的
   那几条），否则整组作废；
3. 模型给不出可并入的分组就什么都不写，如实回「没有可合并的内容」；
4. 落库前后各数一次行数，少一行就整体回滚并报错——宁可什么都不做，也不能少。
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

from spiritscout.core.exceptions import SpiritScoutError

from .experience import (  # noqa: PLC2701 —— 同包私有助手，合并与提炼共用一套读写
    _ensure_columns,
    _load_conn,
    _read_all,
    _row,
)

#: 候选目标上限：整库塞进提示词会先把上下文撑爆，按新到旧取这么多条
MAX_CANDIDATES = 160

#: 单条合并后正文的上限（与技能页的 2000 字口径一致，够写一段事实）
MAX_INSIGHT = 2000

_SYSTEM = (
    "你是灵枢。用户勾选了一些经验条目，想知道能不能把它们并进经验库里**已有的**"
    "某一条——同样的规律不必占两行。\n"
    "纪律：\n"
    "① 只能选择下面「候选目标」里出现过的 id 作为并入对象，不许新建条目；\n"
    "② 只有当某条候选确实在讲同一类事实、合并后信息量更大且不丢原有细节时才合并；"
    "拿不准、或只是「主题相近」的，一律不合并；\n"
    "③ 合并后的正文写成陈述句：什么条件下、能看到什么信号、为什么值得注意；"
    "不写操作序列与处方，不写单题坐标（路径、参数、口令、端口、flag 原文）；\n"
    "④ 一条候选最多出现一次；被合并的候选不需要再单独输出；\n"
    "⑤ 没有任何可合并的就返回空数组——什么都不做是合格答案。\n"
    '返回 JSON：{"groups": [{"target_id": str, "insight": str, '
    '"context": str, "sources": [str]}]}'
)


def _payload(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append({
            "id": str(row.get("insight_id") or ""),
            "insight": str(row.get("insight") or "")[:1200],
            "context": str(row.get("context") or "")[:400],
            "tags": row.get("tags") or [],
        })
    return out


def _tags_of(row: dict[str, Any]) -> list[str]:
    raw = row.get("tags") or []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = []
    return [str(tag) for tag in raw if str(tag).strip()]


def _merge_tags(rows: list[dict[str, Any]], extra: Any = None) -> list[str]:
    """目标与来源的标签取并集，最多 8 个——只增不减标签，避免检索面变窄。"""
    seen: list[str] = []
    for row in rows:
        for tag in _tags_of(row):
            if tag not in seen:
                seen.append(tag)
    for tag in extra or []:
        text = str(tag or "").strip()
        if text and text not in seen:
            seen.append(text)
    return seen[:8]


def collect(db_path: str | Path, ids: list[str]) -> tuple[list[dict[str, Any]],
                                                          list[dict[str, Any]]]:
    """读出被选中的条目和候选目标；顺带把明显冲突的输入挡在模型之前。"""
    wanted: list[str] = []
    for raw in ids or []:
        key = str(raw or "").strip()
        if key and key not in wanted:
            wanted.append(key)
    if not wanted:
        raise SpiritScoutError("合并至少要选一条经验")
    path = Path(db_path)
    if not path.exists():
        raise SpiritScoutError("经验库还不存在，没有可合并的条目")
    rows = _read_all(path)
    by_id = {str(row.get("insight_id") or ""): row for row in rows}
    selected: list[dict[str, Any]] = []
    for key in wanted:
        row = by_id.get(key)
        if row is None:
            raise SpiritScoutError(f"经验不存在: {key}")
        if str(row.get("merged_into") or "").strip():
            raise SpiritScoutError(f"这条经验已经合并过: {key}")
        selected.append(row)
    # 候选目标＝库里其它有效条目（新到旧），排除这次勾选的
    candidates = [row for row in rows
                  if str(row.get("insight_id") or "") not in wanted
                  and not str(row.get("merged_into") or "").strip()]
    return selected, candidates[:MAX_CANDIDATES]


def validate_groups(groups: Any, *, selected: list[dict[str, Any]],
                    candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把模型输出收成可执行的分组：目标必须在候选集内、来源必须来自这次勾选。"""
    allowed_targets = {str(row.get("insight_id") or ""): row for row in candidates}
    allowed_sources = {str(row.get("insight_id") or "") for row in selected}
    by_target: dict[str, dict[str, Any]] = {}
    for group in groups or []:
        if not isinstance(group, dict):
            continue
        target = str(group.get("target_id") or "").strip()
        if target not in allowed_targets:
            continue                        # 模型自己编的 id：整组作废
        insight = str(group.get("insight") or "").strip()
        if not insight:
            continue
        sources = [str(s or "").strip() for s in (group.get("sources") or [])]
        sources = [s for s in dict.fromkeys(sources) if s in allowed_sources]
        if not sources:
            continue
        item = by_target.setdefault(target, {
            "target_id": target,
            "target_insight": str(allowed_targets[target].get("insight") or ""),
            "insight": insight[:MAX_INSIGHT],
            "context": str(group.get("context") or "").strip()[:600],
            "sources": [],
            "tags": _merge_tags([allowed_targets[target]], group.get("tags")),
        })
        for source in sources:
            if source not in item["sources"]:
                item["sources"].append(source)
    return list(by_target.values())


async def plan_absorb(gateway: Any, db_path: str | Path, ids: list[str], *,
                      timeout_seconds: int = 90, audit: Any = None) -> dict[str, Any]:
    """交给模型判断：这些经验能不能并进已有的某一条。不写库。

    模型不可用、回的不是 JSON、或没有可合并的内容，都如实返回 ``groups: []``
    并附原因——页面照常显示，不伪装成异常。
    """
    from spiritscout.gateway.backends import extract_json
    from spiritscout.gateway.gateway import chat_decision

    selected, candidates = collect(db_path, ids)
    if not candidates:
        return {"groups": [], "checked": len(selected), "candidates": 0,
                "note": "库里只有你勾选的这几条，没有别的经验可以并入"}
    payload = {
        "selected": _payload(selected),
        "candidates": _payload(candidates),
    }
    try:
        resp = await asyncio.wait_for(chat_decision(
            gateway,
            [{"role": "system", "content": _SYSTEM},
             {"role": "user", "content": json.dumps(payload, ensure_ascii=False)[:24000]}],
            task_type="meta_planning", response_format="json",
            max_tokens=8192, reasoning_effort="low",
            timeout_seconds=timeout_seconds, audit=audit, actor="master"),
            timeout=timeout_seconds + 40)
    except asyncio.TimeoutError as exc:
        raise SpiritScoutError(
            f"模型在 {timeout_seconds} 秒内没有给结果，先不合并（经验库没动）") from exc
    try:
        data = extract_json(resp.content) or {}
    except ValueError as exc:
        raise SpiritScoutError(
            "模型没有返回可解析的 JSON，先不合并（经验库没动）") from exc
    raw_groups = data.get("groups") if isinstance(data, dict) else data
    groups = validate_groups(raw_groups, selected=selected, candidates=candidates)
    note = ("没有可以并入同一条经验的内容" if not groups
            else f"找到 {len(groups)} 处可以并入的地方")
    return {"groups": groups, "checked": len(selected),
            "candidates": len(candidates), "note": note}


def apply_absorb(db_path: str | Path, groups: list[dict[str, Any]], *,
                 audit: Any = None) -> dict[str, Any]:
    """把确认过的分组写进目标条目。**只 UPDATE，绝不 DELETE。**

    写前写后各数一次行数：数量变化即回滚并报错，因为「不能删除任何经验」是
    这条功能的硬约束，任何删除都是 bug 而不是分支。
    """
    path = Path(db_path)
    if not path.exists():
        raise SpiritScoutError("经验库还不存在，没有可合并的条目")
    items = [g for g in (groups or []) if isinstance(g, dict)
             and str(g.get("target_id") or "").strip()
             and str(g.get("insight") or "").strip()]
    if not items:
        raise SpiritScoutError("没有要应用的合并（模型没给出可并入的分组）")
    conn = _load_conn(path)
    applied: list[dict[str, Any]] = []
    try:
        _ensure_columns(conn)
        before = int(conn.execute("SELECT COUNT(*) FROM insights").fetchone()[0])
        with conn:
            for group in items:
                target_id = str(group["target_id"]).strip()
                row = _row(conn, target_id)
                if row is None:
                    raise SpiritScoutError(f"目标经验不存在: {target_id}")
                sources = [str(s or "").strip() for s in (group.get("sources") or [])]
                sources = [s for s in dict.fromkeys(sources)
                           if s and _row(conn, s) is not None]
                if not sources:
                    raise SpiritScoutError(
                        f"这条合并没有有效的来源条目: {target_id}")
                previous = [str(x) for x in _absorbed_of(row)]
                absorbed = previous + [s for s in sources if s not in previous]
                tags = _merge_tags([row], group.get("tags"))
                conn.execute(
                    "UPDATE insights SET insight = ?, context = ?, tags = ?,"
                    " absorbed_from = ? WHERE insight_id = ?",
                    (str(group["insight"])[:MAX_INSIGHT],
                     str(group.get("context") or row.get("context") or "")[:600],
                     json.dumps(tags, ensure_ascii=False),
                     json.dumps(absorbed, ensure_ascii=False), target_id))
                applied.append({"target_id": target_id, "sources": sources,
                                "absorbed_from": absorbed})
        after = int(conn.execute("SELECT COUNT(*) FROM insights").fetchone()[0])
        if after != before:
            raise SpiritScoutError(
                f"合并前后条数不一致（{before} → {after}），已回滚：不删除任何经验")
    except sqlite3.Error as exc:
        raise SpiritScoutError(
            f"经验库操作失败（{type(exc).__name__}）: {str(exc)[:200]}") from exc
    finally:
        conn.close()
    if audit is not None and applied:
        audit.log("experience.absorbed", "user", {
            "applied": len(applied),
            "targets": [item["target_id"] for item in applied],
            "deleted": 0})
    return {"applied": len(applied), "deleted": 0, "groups": applied}


def _absorbed_of(row: dict[str, Any]) -> list[str]:
    raw = row.get("absorbed_from") or []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else []
        except ValueError:
            raw = []
    return [str(x) for x in raw or [] if str(x).strip()]


__all__ = [
    "MAX_CANDIDATES", "MAX_INSIGHT", "apply_absorb", "collect", "plan_absorb",
    "validate_groups",
]
