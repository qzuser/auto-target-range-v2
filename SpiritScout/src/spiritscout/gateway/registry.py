"""模型注册表与主备关系。

优先使用**会话选定的模型**（`ModelGateway.set_session_model`，未选定/未绑定才
往下走）；否则按**用户排的模型优先级**（编队表的 naming 链）选择，链外的模型
按注册表顺序排在后面。

优先级链在运行期按 `priority_refresh_seconds` 定时重读：用户在「模型」页改完
顺序，运行中的会话下一批调用就跟上，不必重启进程。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from spiritscout.config.agent_models import read_naming_chain
from spiritscout.config.settings import ModelEntry
from spiritscout.core.exceptions import ConfigurationError, SpiritScoutError
from spiritscout.gateway.credentials import is_usable

DEFAULT_PRIORITY_REFRESH = 30.0


class ModelRegistry:
    def __init__(self, entries: list[ModelEntry], *,
                 priority: list[str] | None = None,
                 priority_source: Callable[[], list[str]] | None = None,
                 refresh_seconds: float = DEFAULT_PRIORITY_REFRESH):
        """priority_source：返回当前优先级链的回调（运行期定时重读）。

        refresh_seconds<=0 表示每次排序都重读（测试与「立刻生效」场景用）。
        """
        if not entries:
            raise ConfigurationError("模型注册表为空：请先在 Web 控制台「模型」页配置至少一个模型")
        self._by_model: dict[str, ModelEntry] = {e.model: e for e in entries}
        # 优先级里已经不在注册表的条目（停用/改名/删行）直接忽略，不参与排序
        self._priority = [m for m in (priority or []) if m in self._by_model]
        self._source = priority_source
        self._refresh_seconds = float(refresh_seconds)
        self._synced_at = time.monotonic()

    @property
    def priority(self) -> list[str]:
        self._sync_priority()
        return list(self._priority)

    def _sync_priority(self) -> None:
        """按间隔重读优先级链：读失败/格式错沿用旧链，绝不让排序抛错。

        配置文件可能正被保存（半截 JSON）或所在盘掉线，这类错误只该让
        「新顺序」晚一条街生效，不该让整轮任务倒在路由上。
        """
        if self._source is None:
            return
        now = time.monotonic()
        if self._refresh_seconds > 0 and now - self._synced_at < self._refresh_seconds:
            return
        self._synced_at = now
        try:
            fresh = list(self._source() or [])
        except (SpiritScoutError, OSError, ValueError):
            return
        self._priority = [m for m in fresh if m in self._by_model]

    def _ordered(self) -> list[ModelEntry]:
        """优先级链在前，其余按注册表顺序——用户在前端排的顺序就是首选顺序。

        没有密钥的远端渠道一律排到最后：让它排在链首只会换来一句
        `Missing credentials`，反倒是把能用的渠道挡在后面。
        """
        self._sync_priority()
        if not self._priority:
            ordered = list(self._by_model.values())
        else:
            head = [self._by_model[m] for m in self._priority]
            head_set = set(self._priority)
            ordered = head + [e for e in self._by_model.values()
                              if e.model not in head_set]
        usable = [e for e in ordered if is_usable(e)]
        if not usable:
            return ordered           # 全都没密钥：照旧给调用方一个明确报错
        return usable + [e for e in ordered if not is_usable(e)]

    def get(self, model: str) -> ModelEntry:
        try:
            return self._by_model[model]
        except KeyError as exc:
            raise ConfigurationError(f"未注册的模型: {model}") from exc

    def has(self, model: str) -> bool:
        return model in self._by_model

    def fallback_of(self, model: str) -> list[ModelEntry]:
        """主备关系：返回声明为该模型备机的条目（4.9.3-5 主备切换）。"""
        return [e for e in self._by_model.values() if model in e.is_fallback_for]

    def all(self) -> list[ModelEntry]:
        return list(self._by_model.values())

    def route(
        self, task_type: str = "", *, prefer_model: str | None = None,
        required_capability: str | None = None,
    ) -> ModelEntry:
        """路由：绑定模型优先；否则能力过滤后按用户优先级链取首个。

        required_capability 是硬要求：候选中无具备该能力者时在全表内放宽
        匹配，仍无才回退原候选（避免路由到不胜任的模型）。
        """
        if prefer_model:
            return self.get(prefer_model)
        pool = self._ordered()
        if required_capability:
            capable = [c for c in pool if required_capability in c.capabilities]
            pool = capable or pool
        return pool[0]

    def top_models(self, n: int, *, task_type: str = "") -> list[ModelEntry]:
        """投票/辩论候选：按用户优先级链取 n 个不同模型。"""
        return self._ordered()[: max(n, 0)]

    def cheapest_for(self, task_type: str = "") -> ModelEntry:
        """级联首棒：优先级链首个（用户配置顺序即优先级）。"""
        return self._ordered()[0]


def registry_for(models: list[ModelEntry], cfg: Any = None, *,
                 refresh_seconds: float | None = None) -> ModelRegistry:
    """按配置建注册表：模型优先级取编队表 naming 链（第一条＝首选）。

    注册表带着「重读优先级」的回调，运行期按 `cfg.gateway
    .priority_refresh_seconds`（默认 30 秒）刷新——设置页调整顺序后，在跑的
    会话不必重启就能改用新首选。文件缺失/格式错误时退回注册表顺序：宁可按旧
    行为跑，也不因为一行配置让整条链路起不来。
    """
    path = getattr(cfg, "agent_models_path", "") if cfg is not None else ""
    if not path:
        return ModelRegistry(models)
    if refresh_seconds is None:
        gateway_cfg = getattr(cfg, "gateway", None)
        refresh_seconds = float(getattr(
            gateway_cfg, "priority_refresh_seconds", DEFAULT_PRIORITY_REFRESH))
    priority: list[str] = []
    try:
        priority = read_naming_chain(path)
    except (SpiritScoutError, OSError, ValueError):
        priority = []
    return ModelRegistry(models, priority=priority,
                         priority_source=lambda: read_naming_chain(path),
                         refresh_seconds=refresh_seconds)
