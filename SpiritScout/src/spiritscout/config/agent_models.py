"""编队表（`agent_models.yaml`）的读取：模型优先级与各 Agent 的指派。

Web 编队页写、运行链读，两边共用同一份解析。**命名链就是模型优先级**：
链上第一条是路由首选，取不到才按链的顺序往下走，链外的模型排在最后。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from spiritscout.core.exceptions import SpiritScoutError


def _read_doc(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        # 半截文件（编辑到一半保存）不该让整条路由链起不来：调用方按
        # 「读不到优先级」处理，沿用上一份可用排序。
        raise SpiritScoutError(f"编队表解析失败（{p}）: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise SpiritScoutError(f"Agent 模型分配表格式错误: {p}")
    return data


def read_naming_chain(path: str | Path) -> list[str]:
    """模型优先级（＝命名候选链）：顺序即首选次序，去重保序。"""
    raw = _read_doc(path).get("naming") or []
    if not isinstance(raw, list):
        raise SpiritScoutError(f"命名候选链格式错误: {path}")
    chain: list[str] = []
    for item in raw:
        mid = str(item).strip()
        if mid and mid not in chain:
            chain.append(mid)
    return chain


def read_assignments(path: str | Path) -> dict[str, str]:
    """agent → model 的显式指派（空表＝不干预，走优先级链）。"""
    raw = _read_doc(path).get("assignments") or {}
    if not isinstance(raw, dict):
        raise SpiritScoutError(f"Agent 模型分配表格式错误: {path}")
    return {str(k): str(v) for k, v in raw.items() if v and str(v).strip()}
