"""题目身份：这次做的是不是上一次那道题。

会话可以续聊、可以重开，但"上一道题"的事实不该被"这一道题"继承。上一题
挖到的路径、端点、凭据、flag 一旦留在黑板和工作区里，新题的智能体会把它们
当成既有资产：轻则白白复测一遍死胡同，重则把旧题的 flag 当新答案交上去。

所以在每次派发前做一次身份比对——指纹相同就什么都不动（同一道题重开，上
一轮的成果正是这一轮的起点）；指纹变了就切断关联：清掉只对上一题成立的六
层黑板事实，并把 flag 库与平台进度的落盘文件归档改名，让新一轮从零开始。
用户原话与题目身份记录本身留在原地：它们说明"谁授权、这次是哪道题"，不随
题目变化。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from spiritscout.core.models import BlackboardLayer

if TYPE_CHECKING:  # 仅供类型标注，避免与 launch/audit 相互导入
    from spiritscout.core.audit import AuditLogger
    from spiritscout.launch import LaunchPlan

# 身份记录挂在目标与授权层：它描述"这次是哪道题"，与授权事实同层。
IDENTITY_LAYER = BlackboardLayer.TARGET_AUTH
IDENTITY_RECORD = "task-identity"
# 换题时保留的记录：用户原话（授权来源）与身份记录本身。
KEEP_RECORDS = ("user-context", IDENTITY_RECORD)

# 只对某一题成立、换题即失效的层。
CLEARED_LAYERS = (
    BlackboardLayer.ASSET,
    BlackboardLayer.RECON_CLUE,
    BlackboardLayer.VULN,
    BlackboardLayer.CREDENTIAL,
    BlackboardLayer.TOPOLOGY,
    BlackboardLayer.TASK_STATE,
)

# 跟随题目走的落盘产物：不清掉会被新一轮当成"已经做过/已经交过"。
CLEARED_FILES = ("flags.json", "competition_progress.json")


@dataclass
class TaskIdentity:
    """一次派发的题目身份：指纹 + 给人看的标签 + 参与计算的原始材料。"""

    fingerprint: str
    label: str
    material: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class TaskSwitch:
    """一次真实发生的换题：从哪道到哪道、清了多少、归档了什么。"""

    previous_fingerprint: str
    previous_label: str
    current: TaskIdentity
    cleared: dict[str, int] = field(default_factory=dict)
    archived: list[str] = field(default_factory=list)

    @property
    def cleared_total(self) -> int:
        return sum(self.cleared.values())

    def summary(self) -> str:
        """给用户看的一句话（进时间线与会话摘要）。"""
        was = self.previous_label or self.previous_fingerprint
        head = f"换题：上一道「{was}」→ 这一道「{self.current.label}」"
        parts = []
        if self.cleared_total:
            parts.append(f"清掉上一题 {self.cleared_total} 条黑板事实")
        if self.archived:
            parts.append("归档 " + "、".join(self.archived))
        return head + ("，" + "，".join(parts) if parts else "") + "；不再带入本次。"


def _challenge_rows(plan: LaunchPlan) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for ch in plan.challenges or []:
        if not isinstance(ch, dict):
            continue
        rows.append({
            "id": str(ch.get("id") or "").strip(),
            "title": str(ch.get("title") or "").strip(),
            "category": str(ch.get("category") or "").strip(),
            "url": str(ch.get("url") or "").strip(),
        })
    return sorted(rows, key=lambda r: (r["id"], r["title"], r["url"]))


def _material(plan: LaunchPlan) -> list[dict[str, Any]]:
    """参与指纹计算的材料——只取结构化标识，不取任务原文。

    任务原文会随续聊追加新消息而变，用它做指纹会把"同一道题接着聊"误判成
    换题。题目清单优先；没有清单（例如平台侧动态拉题、SRC 单目标）就退到
    授权范围 + 目标 + 平台档案，这些都稳定。
    """
    rows = _challenge_rows(plan)
    if rows:
        return rows
    scope = plan.authorization.scope
    material: dict[str, Any] = {
        "target": str(plan.target or "").strip().lower(),
        "domains": sorted({str(d).strip().lower() for d in scope.allowed_domains if str(d).strip()}),
        "urls": sorted({str(u).strip().lower() for u in scope.allowed_urls if str(u).strip()}),
    }
    profile = plan.platform_profile if isinstance(plan.platform_profile, dict) else None
    if profile:
        # 同平台不同场次也算不同题目：把平台标识纳入，但不含任何凭据。
        material["platform"] = str(
            profile.get("name") or profile.get("base_url") or "").strip().lower()
    return [material]


def _label(plan: LaunchPlan, material: list[dict[str, Any]]) -> str:
    rows = _challenge_rows(plan)
    if rows:
        if len(rows) == 1:
            only = rows[0]
            name = only["title"] or only["id"] or "未命名题目"
            return f"题目 · {name}"[:120]
        names = [r["title"] or r["id"] or "未命名" for r in rows[:3]]
        tail = "…" if len(rows) > 3 else ""
        return f"{len(rows)} 道题：{'、'.join(names)}{tail}"[:120]
    target = str(plan.target or "").strip()
    if target:
        return f"目标 · {target}"[:120]
    domains = (material[0].get("domains") if material else []) or []
    if domains:
        return f"目标 · {domains[0]}（{len(domains)} 个域）"[:120]
    return "未标明题目"


def identity_of(plan: LaunchPlan) -> TaskIdentity:
    """算出这道题的身份指纹（同样输入必然同样输出，跨重启稳定）。"""
    material = _material(plan)
    blob = json.dumps(material, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
    return TaskIdentity(fingerprint=digest, label=_label(plan, material), material=material)


def read_identity(blackboard: Any) -> dict[str, Any] | None:
    """读上一轮记下的身份；没有或格式不对都当作"第一次"。"""
    data = blackboard.read(IDENTITY_LAYER, IDENTITY_RECORD)
    if isinstance(data, dict) and str(data.get("fingerprint") or ""):
        return data
    return None


def _archive(path: Path, fingerprint: str) -> str | None:
    """把上一题的落盘产物改名留档（不删除，用户还能翻），返回新文件名。"""
    if not path.exists():
        return None
    stem = f"{path.stem}.prev-{fingerprint or 'unknown'}"
    target = path.with_name(f"{stem}{path.suffix}")
    n = 2
    while target.exists():
        target = path.with_name(f"{stem}-{n}{path.suffix}")
        n += 1
    try:
        path.replace(target)
    except OSError:
        return None
    return target.name


def switch_if_changed(
    *,
    bb_path: Path,
    workspace: Path,
    plan: LaunchPlan,
    mode: str,
    audit: AuditLogger,
) -> TaskSwitch | None:
    """派发前调用：题目变了就切断上一题的关联，并把本轮身份记下来。

    返回 None 表示"还是同一道题"（含第一次开工），调用方什么都不用做。
    """
    from spiritscout.blackboard import Blackboard

    identity = identity_of(plan)
    blackboard = Blackboard(bb_path)
    try:
        previous = read_identity(blackboard)
        if previous and str(previous["fingerprint"]) == identity.fingerprint:
            return None

        switch: TaskSwitch | None = None
        if previous:
            cleared: dict[str, int] = {}
            for layer in (*CLEARED_LAYERS, IDENTITY_LAYER):
                keep = KEEP_RECORDS if layer is IDENTITY_LAYER else ()
                removed = blackboard.purge(layer, keep=keep)
                if removed:
                    cleared[layer.value] = removed
            archived = [name for name in (
                _archive(workspace / name, str(previous["fingerprint"]))
                for name in CLEARED_FILES) if name]
            switch = TaskSwitch(
                previous_fingerprint=str(previous["fingerprint"]),
                previous_label=str(previous.get("label") or ""),
                current=identity, cleared=cleared, archived=archived)

        blackboard.write(
            IDENTITY_LAYER, IDENTITY_RECORD,
            {"fingerprint": identity.fingerprint, "label": identity.label,
             "items": identity.material, "mode": mode,
             "superseded": (switch.previous_fingerprint if switch else ""),
             "at": datetime.now(UTC).isoformat()},
            updated_by="task-identity")
    finally:
        blackboard.close()

    if switch is None:
        return None
    audit.log("system.lifecycle", "runtime", {
        "action": "task_switched",
        "from": {"fingerprint": switch.previous_fingerprint, "label": switch.previous_label},
        "to": {"fingerprint": identity.fingerprint, "label": identity.label},
        "cleared": switch.cleared, "archived": switch.archived})
    return switch
