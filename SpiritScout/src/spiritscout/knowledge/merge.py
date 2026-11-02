"""经验二次提炼：把「极其相似」的条目合并压缩成一条。

设计要点（为什么这么做）：

- **不调模型**。合并是压缩同一件事的多种说法，模型改写可能悄悄丢掉差异细节；
  这里用确定性规则：取信息量最大的一条当底稿，其余条目里**底稿没有的句子**按
  「另：…」并入——压缩的是重复表述，不是事实。
- **先提炼、后确认**。``compose`` 只算出合并稿；要不要真入库由调用方决定
  （``ExperienceStore`` 那边对应「预览 → 确认保留 → 删原件、写入结果」两步）。
- **只合并极相似的**。相似度用归一化后的编辑相似度（``difflib`` 比例），且要求
  **整组两两都达标**（完整连接）：A≈B、B≈C 但 A≁C 时不成组，避免「链式合并」把
  不相干经验卷进来。默认阈值 0.90 ≈ 两句话只有一成以内的字符不同；页面上可改。
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

# 默认阈值：0.90 相当于两句话只差个别词、语序或虚词；页面可改（50%–100%）
DEFAULT_THRESHOLD = 0.90
MAX_GROUP = 6
_INSIGHT_CAP = 600
_CONTEXT_CAP = 300
_TAG_CAP = 8
_STRIP = re.compile(r"[\s，。；、：！？,.;:!?（）()\[\]【】\"'“”‘’/\\|—\-_=+*#>`~…]+")
_SPLIT = re.compile(r"[。；！？;!?\n]+")


def normalize(text: str) -> str:
    """比对用归一化：去空白与标点、统一小写；不改原文。"""
    return _STRIP.sub("", str(text or "")).lower()


def clamp_threshold(value: Any) -> float:
    """把页面送来的阈值收进 0.5–1.0：越界的值按边界算，不让它把组算飞。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return DEFAULT_THRESHOLD
    if number != number:            # NaN
        return DEFAULT_THRESHOLD
    return max(0.5, min(1.0, number))


def similarity(left: str, right: str) -> float:
    """归一化后的编辑相似度：0 毫不相干，1 归一化后完全一致。

    用 ``SequenceMatcher`` 而不是二元组 Jaccard：中文同义改写常常整词替换
    （「缺少」→「不一致」），Jaccard 会掉到 0.6 以下，编辑相似度还能保住 0.85。
    """
    a, b = normalize(left), normalize(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def _fragments(text: str) -> list[str]:
    return [part.strip() for part in _SPLIT.split(str(text or "")) if part.strip()]


def compose(items: list[dict[str, Any]]) -> dict[str, Any]:
    """把一组极相似条目压成一条：最长的那条当底稿，补上它没有的句子。"""
    ordered = sorted(items, key=lambda item: len(str(item.get("insight") or "")),
                     reverse=True)
    if not ordered:
        raise ValueError("compose 需要至少一条经验")
    base = str(ordered[0].get("insight") or "").strip()
    known = [normalize(fragment) for fragment in _fragments(base)]
    extras: list[str] = []
    for item in ordered[1:]:
        for fragment in _fragments(str(item.get("insight") or "")):
            norm = normalize(fragment)
            if not norm:
                continue
            # 底稿里已有（或几乎同文）的句子不重复收；只补真正新增的信息
            if any(norm in known_text or known_text in norm for known_text in known):
                continue
            if fragment not in extras:
                extras.append(fragment)
                known.append(norm)
    insight = base
    for fragment in extras:
        candidate = f"{insight}；另：{fragment}" if insight else fragment
        if len(candidate) > _INSIGHT_CAP:
            break
        insight = candidate

    contexts: list[str] = []
    for item in ordered:
        context = str(item.get("context") or "").strip()
        if context and context not in contexts:
            contexts.append(context)
    tags: list[str] = []
    for item in ordered:
        for tag in item.get("tags") or []:
            tag = str(tag or "").strip()
            if tag and tag not in tags:
                tags.append(tag)
    sources = {str(item.get("source_session") or "") for item in ordered}
    return {
        "insight": insight[:_INSIGHT_CAP],
        "context": "；".join(contexts)[:_CONTEXT_CAP],
        "tags": tags[:_TAG_CAP],
        "source_session": sources.pop() if len(sources) == 1 else "",
        "merged_from": [str(item.get("insight_id") or "") for item in ordered],
        "absorbed": sum(1 for _ in ordered) - 1,
    }


def build_groups(rows: list[dict[str, Any]], *, threshold: float = DEFAULT_THRESHOLD,
                 min_size: int = 2, max_size: int = MAX_GROUP,
                 limit: int = 20) -> list[dict[str, Any]]:
    """找出可以合并的组：整组两两相似度都 ≥ 阈值才算数。"""
    threshold = clamp_threshold(threshold)
    remaining = [row for row in rows
                 if str(row.get("insight") or "").strip()
                 and not str(row.get("merged_into") or "")]
    groups: list[dict[str, Any]] = []
    used: set[str] = set()
    for seed in remaining:
        seed_id = str(seed.get("insight_id") or "")
        if not seed_id or seed_id in used:
            continue
        members = [seed]
        for other in remaining:
            other_id = str(other.get("insight_id") or "")
            if other_id == seed_id or other_id in used or len(members) >= max_size:
                continue
            if all(similarity(str(member["insight"]), str(other["insight"])) >= threshold
                   for member in members):
                members.append(other)
        if len(members) < max(2, min_size):
            continue
        used.update(str(member.get("insight_id") or "") for member in members)
        scores = [similarity(str(a["insight"]), str(b["insight"]))
                  for index, a in enumerate(members) for b in members[index + 1:]]
        groups.append({
            "items": members,
            "score": round(min(scores), 4) if scores else 0.0,
            "preview": compose(members),
        })
        if len(groups) >= max(1, int(limit)):
            break
    groups.sort(key=lambda group: (-group["score"], -len(group["items"])))
    return groups
