"""本地工具索引的读写接口：目录由用户在控制台设置，扫描与清理都在工作区里做。

五条路由，边界都在这一层定好：

- ``GET  /api/local-tools``：当前配置 + 索引摘要 + 工具清单（可关键词过滤）；
- ``PUT  /api/local-tools``：改开关/目录/上限；目录必须是已存在的绝对路径，
  驱动器根和被拒绝（复制整盘进暂存毫无意义）；
- ``POST /api/local-tools/refresh``：重扫并落盘；
- ``POST /api/local-tools/cleanup``：清掉遗留的暂存目录（正常运行结束即删，
  这里兜的是崩溃残壳）；
- ``POST /api/local-tools/pick-dir``：弹本机「选择文件夹」对话框，把选中的
  绝对路径交给前端（取消返回 ``cancelled``）。

Agent 侧真正的执行入口是工具 ``local_tool``，这里不提供任意路径执行。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from spiritscout.tools import dir_picker, local_index, local_runner


class LocalToolsPayload(BaseModel):
    enabled: bool | None = None
    dirs: list[str] | None = None
    timeout_seconds: int | None = None
    max_depth: int | None = None
    max_files: int | None = None
    max_stage_mb: int | None = None


def _clean_dirs(raw: list[str]) -> list[str]:
    """校验目录：必须是已存在的绝对路径，且不是驱动器根（复制整盘进暂存没意义）。"""
    kept: list[str] = []
    problems: list[str] = []
    for item in raw:
        text = str(item or "").strip().strip('"')
        if not text:
            continue
        path = Path(os.path.expanduser(text))
        if not path.is_absolute():
            problems.append(f"{text}：需要绝对路径")
            continue
        if path.parent == path:
            problems.append(f"{text}：不能用磁盘根目录")
            continue
        if not path.is_dir():
            problems.append(f"{text}：目录不存在")
            continue
        norm = os.path.normpath(str(path))
        if norm not in kept:
            kept.append(norm)
    if problems:
        raise HTTPException(422, "目录不可用：" + "；".join(problems))
    return kept


def _view(root: Path, *, query: str = "", limit: int = 200) -> dict[str, Any]:
    config = local_index.load(root)
    index = local_index.LocalToolIndex(root).ensure(config)
    tools = local_index.LocalToolIndex.search(index.get("tools") or [], query, limit=limit)
    return {
        "config": config,
        "summary": local_index.summary(index),
        "tools": tools,
        "indexed": len(index.get("tools") or []),
        "runs_dir": str(local_runner.runs_root(root)),
        "notice": "运行由 Agent 发起：工具目录先复制到暂存副本，跑完还原原目录并删除副本。",
    }


def mount_local_tools(app: FastAPI, *, cfg: Any) -> None:
    root = Path(str(cfg.workspace.root))

    @app.get("/api/local-tools")
    def get_local_tools(q: str = "", limit: int = 200) -> dict[str, Any]:
        return _view(root, query=q, limit=max(1, min(int(limit or 200), 500)))

    @app.put("/api/local-tools")
    def put_local_tools(payload: LocalToolsPayload) -> dict[str, Any]:
        patch: dict[str, Any] = {}
        if payload.enabled is not None:
            patch["enabled"] = bool(payload.enabled)
        if payload.dirs is not None:
            patch["dirs"] = _clean_dirs(payload.dirs)
        for field_name in ("timeout_seconds", "max_depth", "max_files", "max_stage_mb"):
            value = getattr(payload, field_name)
            if value is not None:
                patch[field_name] = value
        config = local_index.save(root, patch)
        local_index.LocalToolIndex(root).refresh(config)     # 目录变了就立刻重扫
        return _view(root)

    @app.post("/api/local-tools/refresh")
    def refresh_local_tools() -> dict[str, Any]:
        local_index.LocalToolIndex(root).refresh(local_index.load(root))
        return _view(root)

    @app.post("/api/local-tools/cleanup")
    def cleanup_local_tools() -> dict[str, Any]:
        removed = local_runner.sweep_runs(root, stale_seconds=0)
        return {"removed": removed, "count": len(removed),
                "runs_dir": str(local_runner.runs_root(root))}

    @app.post("/api/local-tools/pick-dir")
    def pick_local_tool_dir(initial: str = "") -> dict[str, Any]:
        """弹本机原生「选择文件夹」对话框。

        对话框在子进程里开，用户选完才返回；取消返回 ``cancelled=True``，
        起不来（无图形环境）返回 503 并说明原因，前端退回手填。
        """
        start = initial.strip() or (local_index.load(root).get("dirs") or [""])[0]
        try:
            picked = dir_picker.pick_directory(start)
        except dir_picker.PickerError as exc:
            raise HTTPException(503, str(exc)) from exc
        if not picked:
            return {"cancelled": True, "path": None}
        return {"cancelled": False, "path": picked}
