"""单个会话的经验提炼：看这次学到了什么，必要时手动补一次。

自动提炼在会话收尾时由灵枢跑（`runtime._distill_run`），产出落在全局
``experience.db``，``source_session`` 记的就是会话 ID。会话页据此回看本次
产出；自动提炼因为模型不可用、会话被中断或判定「没活动」而跳过时，用户可以在
页面上手动补一次——战报从落盘状态重建（meta.json、flags.json、黑板、审计），
不依赖运行中的 runtime，所以已停止的会话也能补。
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

from spiritscout.blackboard import Blackboard
from spiritscout.core.audit import AuditLogger
from spiritscout.core.models import BlackboardLayer
from spiritscout.core.sqlite_ro import ro_uri
from spiritscout.knowledge.experience import (
    DEFAULT_DUPLICATE_THRESHOLD,
    ExperienceStore,
    shared_db_path,
)

SESSION_INSIGHTS_LIMIT = 100
DISTILL_EVENTS_LIMIT = 8
AUDIT_TAIL_BYTES = 131072          # 提炼在收尾：只看审计尾段
_ACTIVE_STATUSES = {"created", "queued", "running", "paused"}
_OUTCOME = {"completed": "completed", "stopped": "completed", "failed": "failed",
            "interrupted": "interrupted"}
_LOCKS: dict[str, asyncio.Lock] = {}


def read_session_insights(db_path: str | Path, session_id: str, *,
                          limit: int = SESSION_INSIGHTS_LIMIT) -> list[dict[str, Any]]:
    """本会话产出的经验，最新在前。库不存在或表缺失一律按「还没产出」处理。"""
    path = Path(db_path)
    if not session_id or not path.exists():
        return []
    try:
        conn = sqlite3.connect(ro_uri(path), uri=True)
        try:
            rows = conn.execute(
                "SELECT insight_id, insight, context, tags, source_session, "
                "source_model, ts FROM insights WHERE source_session = ? "
                "ORDER BY ts DESC LIMIT ?", (session_id, max(1, int(limit)))).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return []
    items: list[dict[str, Any]] = []
    for row in rows:
        try:
            tags = json.loads(row[3] or "[]")
        except (TypeError, ValueError):
            tags = []
        items.append({"insight_id": row[0], "insight": row[1], "context": row[2],
                      "tags": [str(tag) for tag in tags] if isinstance(tags, list) else [],
                      "source_session": row[4], "source_model": row[5], "ts": row[6]})
    return items


def read_distill_events(audit_path: str | Path, *,
                        limit: int = DISTILL_EVENTS_LIMIT) -> list[dict[str, Any]]:
    """本会话的提炼记录（自动 + 手动），最新在前；读不到就是没记录。"""
    path = Path(audit_path)
    if not path.exists():
        return []
    try:
        with path.open("rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - AUDIT_TAIL_BYTES))
            tail = fh.read().decode("utf-8", "ignore")
    except OSError:
        return []
    events: list[dict[str, Any]] = []
    for line in tail.splitlines():
        if '"experience.distill"' not in line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if record.get("type") != "experience.distill":
            continue
        detail = record.get("detail") if isinstance(record.get("detail"), dict) else {}
        events.append({"ts": record.get("ts", ""),
                       "trigger": str(detail.get("trigger") or "auto"), **detail})
    events.reverse()                                    # 日志是追加的，最新的在末尾
    return events[:max(1, int(limit))]


def _mission(session: Any) -> str:
    """任务原文：请求里的 mission/text 优先，退到对话里第一条用户原话。"""
    request = session.request if isinstance(session.request, dict) else {}
    for key in ("mission", "text", "task"):
        text = str(request.get(key) or "").strip()
        if text:
            return text[:200]
    for message in session.dialogue_history:
        if str(message.get("role")) == "user":
            return str(message.get("content") or "")[:200]
    return ""


def _flag_stats(session: Any) -> dict[str, int]:
    """与 ``FlagManager.stats()`` 同口径，直接数落盘的条目。"""
    path = Path(session.flags_path)
    stats = {"extracted": 0, "submitted": 0, "accepted": 0, "rejected": 0}
    if not path.exists():
        return stats
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return stats
    if not isinstance(data, list):
        return stats
    for item in data:
        if not isinstance(item, dict):
            continue
        stats["extracted"] += 1
        if item.get("submitted"):
            stats["submitted"] += 1
        if item.get("accepted") is True:
            stats["accepted"] += 1
        elif item.get("accepted") is False:
            stats["rejected"] += 1
    return stats


def _blackboard_digest(session: Any) -> dict[str, Any]:
    """黑板里的发现与失败路线：与自动提炼的战报同形，读不到就少这几项。"""
    if not Path(session.bb_path).exists():
        return {}
    extra: dict[str, Any] = {}
    try:
        blackboard = Blackboard(session.bb_path, readonly=True)
        try:
            findings: dict[str, Any] = {
                "total": blackboard.count(BlackboardLayer.VULN),
                "by_status": blackboard.status_counts(BlackboardLayer.VULN)}
            accepted = []
            for record in blackboard.query(BlackboardLayer.VULN, limit=200):
                data = record["data"]
                if str(data.get("status")) == "accepted" and data.get("title"):
                    accepted.append({"title": str(data["title"])[:100],
                                     "severity": str(data.get("severity", "")),
                                     "type": str(data.get("vuln_type", ""))})
            if accepted:
                findings["accepted"] = accepted[:8]
            extra["findings"] = findings
            trials: list[dict[str, str]] = []
            for record in blackboard.query(BlackboardLayer.TASK_STATE, limit=100):
                data = record["data"]
                if "dag_snapshot" in data:
                    continue
                task = data.get("task", {})
                for route in data.get("routes", []):
                    if str(route.get("status")) in {"pruned", "failed"}:
                        note = (route.get("notes") or [""])[-1]
                        trials.append({"agent": str(task.get("agent_type", "")),
                                       "route": str(route.get("name", ""))[:60],
                                       "status": str(route.get("status")),
                                       "note": str(note)[:140]})
            if trials:
                extra["trials"] = trials[:8]
            extra["tasks_recorded"] = blackboard.count(BlackboardLayer.TASK_STATE)
        finally:
            blackboard.close()
    except Exception:  # noqa: BLE001 —— 黑板坏了不该让「看一眼经验」也失败
        return {}
    return extra


def session_digest(session: Any) -> dict[str, Any]:
    """按落盘状态重建提炼用的战报（不读运行期对象）。"""
    digest: dict[str, Any] = {
        "mode": str(session.mode or ""),
        "target": str(session.target or "")[:200],
        "mission": _mission(session),
        "outcome": _OUTCOME.get(str(session.status or ""), str(session.status or "")),
        "flags": _flag_stats(session),
    }
    summary = session.summary if isinstance(session.summary, dict) else {}
    plan = summary.get("dag_nodes") or []
    if plan:
        digest["plan"] = [{"title": str(node.get("title", ""))[:80],
                           "status": str(node.get("status", ""))} for node in plan[:10]]
    if session.error:
        digest["error"] = str(session.error)[:300]
    digest.update(_blackboard_digest(session))
    return digest


def distill_blocker(session: Any, digest: dict[str, Any] | None = None) -> str:
    """不能提炼的原因（空串 = 可以）。运行中的会话等它收尾，没活动的不白烧模型。"""
    status = str(session.status or "")
    if status in _ACTIVE_STATUSES:
        return "会话还在执行，等它收尾时自动提炼（也可以停了再手动提炼）"
    data = digest if digest is not None else session_digest(session)
    flags = data.get("flags") or {}
    findings = data.get("findings") or {}
    if (not flags.get("extracted") and not data.get("tasks_recorded")
            and not findings.get("total") and not data.get("mission")):
        return "这次会话没有可提炼的活动"
    return ""


def _distilling(session_id: str) -> bool:
    lock = _LOCKS.get(session_id)
    return bool(lock and lock.locked())


def experience_library(cfg: Any) -> Path:
    """共享经验库路径——与会话页、经验库页、开工召回必须是同一本。

    ``experience.root`` 为空时跟随**基础工作区**（``cfg.workspace.root``），而不是
    会话工作区：手动提炼曾经按 ``session.workspace`` 算路径，条目写进
    ``sessions/<id>/experience.db``，经验库页读共享库，于是「提炼了却查不到」。
    """
    return shared_db_path(cfg)


def session_page(cfg: Any, session: Any) -> dict[str, Any]:
    """会话页「经验」页签的数据：本次产出 + 提炼记录 + 现在能不能手动提炼。"""
    db_path = experience_library(cfg)
    items = read_session_insights(db_path, session.session_id)
    digest = session_digest(session)
    blocker = distill_blocker(session, digest)
    return {
        "session_id": session.session_id,
        "items": items,
        "total": len(items),
        "history": read_distill_events(session.audit_path),
        "state": {"status": str(session.status or ""), "distilling": _distilling(session.session_id),
                  "can_distill": not blocker and not _distilling(session.session_id),
                  "reason": blocker},
        "distill": {"timeout": int(getattr(cfg.experience, "distill_timeout_seconds", 90) or 90)},
    }


def _skipped_note(names: list[str]) -> str:
    """失败时交代清楚：这一轮把哪些没 Key 的渠道跳过了。"""
    if not names:
        return ""
    return f"（本次跳过了没有 API Key 的渠道：{'、'.join(names)}）"


def _usable_models(models: list[Any]) -> list[Any]:
    """只把真的能调通的渠道交给网关。

    没 Key 的模型派过去必定失败，而网关的路由会按质量分挑primary——挑到没 Key
    的那条，一次提炼就白跑（``Missing credentials``）。所以先把没凭据的剔掉，
    剩下有 Key 的照常走主备；一个都没有时由调用方直接给原因，不发这次请求。
    """
    return [entry for entry in models if str(getattr(entry, "api_key", "") or "")]


def _channel_names(models: list[Any]) -> str:
    names: list[str] = []
    for entry in models:
        name = str(getattr(entry, "provider_ref", "")
                   or getattr(entry, "model", "") or "未命名渠道")
        if name not in names:
            names.append(name)
    return "、".join(names)


def _missing_dependency(exc: ModuleNotFoundError) -> str:
    """解释器跑错时导入会在请求里炸，用户只看到 500。这里把它翻成人话。"""
    name = str(getattr(exc, "name", "") or "运行依赖")
    return (f"服务端缺少运行依赖 {name}：当前解释器（{sys.executable}）只能起控制台壳子，"
            f"跑任务与提炼都会失败。请用项目虚拟环境启动："
            f".venv\\Scripts\\python.exe -m spiritscout --config configs\\system.yaml，"
            f"或直接 launch.cmd")


def _error_result(cfg: Any, session: Any, message: str) -> dict[str, Any]:
    """失败也要给与成功一致的结构（页签照常刷新），并把原因留在提炼记录里。"""
    audit = AuditLogger(session.audit_path)
    audit.log("experience.distill", "master", {
        "result": "error", "insights": 0, "error": message[:400],
        "trigger": "manual", "outcome": str(session.status or "")})
    db_path = experience_library(cfg)
    items = read_session_insights(db_path, session.session_id)
    return {"result": "error", "insights": 0, "error": message, "trigger": "manual",
            "items": items, "total": len(items),
            "history": read_distill_events(session.audit_path)}


async def distill_now(cfg: Any, session: Any, *, models: list[Any]) -> dict[str, Any]:
    """手动提炼一次；返回提炼结果与本会话最新的经验列表。

    与自动提炼共用同一段提示词与落库逻辑（``runtime._distill_experience``），
    审计里多一个 ``trigger: manual``，用户能分清哪条是自己点的。
    """
    try:
        from spiritscout.runtime import _distill_experience
        from spiritscout.web.sessions import _conversation_gateway
    except ModuleNotFoundError as exc:      # 服务端跑在没装依赖的解释器上
        return _error_result(cfg, session, _missing_dependency(exc))
    lock = _LOCKS.setdefault(session.session_id, asyncio.Lock())
    if lock.locked():
        return {"result": "busy", "insights": 0, "reason": "正在提炼中，稍等一会儿"}
    async with lock:
        if not models:
            return _error_result(cfg, session, "没有可用模型：先到设置里配一个，再回来提炼")
        usable = _usable_models(models)
        if not usable:
            return _error_result(
                cfg, session,
                f"没有配了 API Key 的渠道：{_channel_names(models)}"
                f"（到「模型」页补上 Key，或把已有 Key 的渠道设为主模型）")
        skipped = [str(getattr(entry, "provider_ref", "") or getattr(entry, "model", ""))
                   for entry in models if entry not in usable]
        if skipped:
            models = usable       # 没凭据的渠道进链只会白跑一次
        audit = AuditLogger(session.audit_path)
        digest = session_digest(session)
        started = time.monotonic()
        store = ExperienceStore(
            experience_library(cfg), audit=audit,
            duplicate_threshold=getattr(cfg.experience, "duplicate_threshold",
                                        DEFAULT_DUPLICATE_THRESHOLD))
        try:
            try:
                gateway = _conversation_gateway(cfg, models, audit)
                result = await _distill_experience(
                    gateway, store, digest,
                    timeout_seconds=int(getattr(cfg.experience, "distill_timeout_seconds", 90) or 90),
                    audit=audit, source_session=session.session_id)
            except Exception as exc:  # noqa: BLE001 —— 模型/网络问题如实记账，不炸请求
                result = {"result": "error", "insights": 0,
                          "error": f"{type(exc).__name__}: {exc}"[:200]}
            if result.get("result") == "error":
                note = _skipped_note([name for name in skipped if name])
                if note:
                    result["error"] = f"{result.get('error') or '提炼失败'}{note}"
        finally:
            store.close()
        audit.log("experience.distill", "master", {
            **result, "trigger": "manual", "outcome": digest.get("outcome", ""),
            "duration_ms": round((time.monotonic() - started) * 1000, 1)})
        items = read_session_insights(experience_library(cfg), session.session_id)
        return {**result, "trigger": "manual", "items": items, "total": len(items),
                "history": read_distill_events(session.audit_path)}
