"""用量统计页的数据接口（只读）。

各会话的用量账本各记各的，这里把它们合成一份「按模型」的视图给前端。
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Query

from spiritscout.config.settings import SystemConfig
from spiritscout.web.usage_stats import PERIODS, collect


def mount_usage(app: FastAPI, *, cfg: SystemConfig) -> None:
    @app.get("/api/usage/stats")
    def usage_stats(period: str = Query("7d", pattern="^(hour|today|7d|30d|all)$")
                    ) -> dict[str, Any]:
        """按模型汇总 token 用量；不读模型配置，也不打外部请求。"""
        return collect(cfg, period=period if period in PERIODS else "7d")
