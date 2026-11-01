"""缓存盘点与一键清理。

前端「关于」页的按钮走这里：先看账（`GET`），再决定清不清（`POST`）。
删除口径由 `spiritscout/maintenance.py` 统一把关——工具、虚拟环境、配置、
密钥、经验库都不在可删范围内。
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from spiritscout.config.settings import SystemConfig
from spiritscout.core.audit import AuditLogger
from spiritscout.maintenance import DEFAULT_DAYS, plan_cache, purge_cache


class PurgeRequest(BaseModel):
    """清理请求：默认按 30 天、清理全部可删类别。"""

    days: int = Field(default=DEFAULT_DAYS, ge=1, le=3650)
    keys: list[str] = Field(default_factory=list,
                            description="只清这些类别（sessions/staging/build/dev-cache），留空=全部")


def mount_maintenance(app: FastAPI, *, cfg: SystemConfig) -> None:
    @app.get("/api/maintenance/cache")
    def cache_preview(days: int = DEFAULT_DAYS) -> dict[str, Any]:
        """盘点：返回每一类的占用、最后使用时间与是否可删（不改任何文件）。"""
        return plan_cache(cfg.workspace.root, days=days).as_dict()

    @app.post("/api/maintenance/cache/purge")
    def cache_purge(payload: PurgeRequest) -> dict[str, Any]:
        """清理：只删盘点里标记为可删的项，结果逐条回报。"""
        result = purge_cache(cfg.workspace.root, days=payload.days,
                             keys=payload.keys or None)
        AuditLogger(cfg.audit_log_path).log("cache.purged", "system", {
            "days": result["days"],
            "freed_bytes": result["freed_bytes"],
            "removed": [item["path"] for item in result["removed"]],
            "kept": len(result["kept"]),
        })
        return result
