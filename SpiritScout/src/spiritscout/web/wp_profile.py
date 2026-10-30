"""解题思路（WP）的信息表：团队名称、队员、单位、赛事与补充交代。

用户要求在写 WP 之前先问一遍这些信息，并且「上次填过的下次带出来」。所以它落在
工作区里一个独立的小 JSON——与界面偏好（`preferences.json`）分开：那边管的是
控制台怎么显示，这边是文档里写什么，改动来源和生命周期都不一样。

所有字段都可为空：不填就按材料里的事实生成，模板里缺的那几行写「（待填写）」。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

FILENAME = "wp-profile.json"
MAX_MEMBERS = 20

FIELDS = ("name", "members", "affiliation", "contest", "notes")


def profile_path(root: str | Path) -> Path:
    return Path(root) / FILENAME


def normalize(raw: Any) -> dict[str, Any]:
    """只保留认识的字段；字符串裁长度、队员去空去重。

    前端送什么进来都可能——多出来的键、超长文本、把队员写成单个字符串。
    这里一律收拢成固定形状，坏数据不该顺着模板漏进最终文档。
    """
    data = raw if isinstance(raw, dict) else {}
    members: list[str] = []
    for item in (data.get("members") or [])[:MAX_MEMBERS * 2]:
        text = str(item or "").strip()[:60]
        if text and text not in members:
            members.append(text)
    return {
        "name": str(data.get("name") or "").strip()[:120],
        "members": members[:MAX_MEMBERS],
        "affiliation": str(data.get("affiliation") or "").strip()[:120],
        "contest": str(data.get("contest") or "").strip()[:120],
        "notes": str(data.get("notes") or "").strip()[:1000],
    }


def load(root: str | Path) -> dict[str, Any]:
    """读上次填的信息；文件缺失或损坏一律当没填过，绝不阻断生成。"""
    try:
        return normalize(json.loads(profile_path(root).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return normalize(None)


def save(root: str | Path, profile: Any) -> dict[str, Any]:
    """原子写入：临时文件 + 替换，半个文件不会被下次读到。"""
    data = normalize(profile)
    path = profile_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return data


def is_empty(profile: Any) -> bool:
    """没填过（或全清空）——用于前端提示「这是第一次，可留空」。"""
    data = normalize(profile)
    return not any(data[key] for key in FIELDS)
