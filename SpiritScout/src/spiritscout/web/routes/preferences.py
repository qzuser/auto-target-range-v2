"""界面偏好的持久化：把"上次选的模式"记在服务端。

只存界面选择（目前就是任务模式），不存任何凭据、目标或题目内容。落在工作
区根目录（默认 `.spiritscout/preferences.json`），所以重开控制台、换浏览器、
清缓存都沿用同一个选择——这正是"下次不用再手动选"的实现方式。

读的一侧永不报错：文件缺失、内容损坏、值不认识都回落到默认模式，控制台不会
因为一个偏好文件打不开。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

FILENAME = "preferences.json"
# 默认即 CTF 解题：新建任务最常见的动作是解题，别的模式再手动切
DEFAULT_MODE = "ctf"
VALID_MODES = ("src", "ctf", "competition")


class PreferencesPayload(BaseModel):
    mode: str | None = None


def preferences_path(root: str | Path) -> Path:
    return Path(root) / FILENAME


def load(root: str | Path) -> dict[str, Any]:
    """读偏好；任何异常都回落默认，绝不向上抛。"""
    try:
        raw = json.loads(preferences_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"mode": DEFAULT_MODE}
    mode = str((raw or {}).get("mode") or "").strip().lower()
    return {"mode": mode if mode in VALID_MODES else DEFAULT_MODE}


def save(root: str | Path, prefs: dict[str, Any]) -> dict[str, Any]:
    """原子写：先落临时文件再替换，半个文件不会被下次启动读到。"""
    path = preferences_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(prefs, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)
    return prefs


def mount_preferences(app: FastAPI, *, cfg: Any) -> None:
    """挂两条路由：读当前偏好、写回用户的选择。"""
    root = cfg.workspace.root

    @app.get("/api/preferences")
    def get_preferences() -> dict[str, Any]:
        """控制台启动时读一次：决定首页默认选中哪个模式。"""
        return load(root)

    @app.put("/api/preferences")
    def put_preferences(payload: PreferencesPayload) -> dict[str, Any]:
        """用户切换模式时写回；非法值直接拒，不静默改写成默认。"""
        mode = (payload.mode or "").strip().lower()
        if mode not in VALID_MODES:
            raise HTTPException(
                422, f"未知模式: {payload.mode}（可选 {', '.join(VALID_MODES)}）")
        return save(root, {"mode": mode})
