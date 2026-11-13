"""模型调用、路由、主备切换与 Token 用量统计。

多模型协作调用位于 gateway.collab。"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from spiritscout import __version__
from spiritscout.config.settings import GatewayConfig, ModelEntry
from spiritscout.core.audit import AuditLogger, NullAuditLogger
from spiritscout.core.exceptions import SpiritScoutError
from spiritscout.gateway.attempts import AttemptTrace, current_attempt_trace

# LiteLLM 默认会去 GitHub 拉模型价格表：一次调用前先跑三个外网请求，离线/内网
# 环境里纯属白等（还留下 SDK 连外网的日志）。本地模型和"不出网"测试都要求它闭嘴。
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

from spiritscout.gateway.backends import (
    ChatBackend,
    DeltaCallback,
    MockBackend,
    backend_for,
    emit_delta,
    extract_json,
)
from spiritscout.gateway.cache import PrefixTracker, cache_summary
from spiritscout.gateway.capabilities import EndpointCapabilities
from spiritscout.gateway.context import DecisionMemory, estimate_input_tokens
from spiritscout.gateway.pricing import estimate_deepseek_cny
from spiritscout.gateway.registry import ModelRegistry
from spiritscout.tools.invocation import ExecutionScope, current_execution_scope


class ModelUnavailableError(SpiritScoutError):
    """端点连续不可用（熔断中）。

    和普通「这一次调用失败了」不同：这条异常的意思是「别再试了，先把端点修好」。
    上层拿到它必须停止推进本轮循环，而不是当成一次抖动继续下一回合——否则
    模型挂了之后，规划层会把每一轮都记成「调查了一次」，任务越堆越多，会话
    永远到不了终态（用户看到的就是"卡住"）。
    """


# 连续多少次「全链失败」就熔断；熔断后多久放一次探活请求
MODEL_BREAKER_THRESHOLD = 3
MODEL_BREAKER_COOLDOWN_SECONDS = 30.0

# 瞬时断连就地重试的间隔：远端渠道一次抖动通常瞬时，等 1 秒重发比整轮失败划算
_TRANSIENT_RETRY_DELAY = 1.0

# 判「这条连接没了，重发就好」的指纹。SDK 把同一种断流包进不同异常类
# （`litellm.InternalServerError: OpenAIException - Connection error` 就不是 OSError），
# 所以按类名与消息双重匹配，而不是靠异常类型穷举。
_TRANSIENT_HINTS = ("connection error", "connection reset", "connection aborted",
                    "server disconnected", "incompletestream", "timed out", "timeout",
                    "apiconnectionerror", "remotedisconnected", "temporarily unavailable")

# 工具调用参数没写完（撞到输出上限）时 llama.cpp 的原文。属于「额度不够，不是端点坏了」：
# 这类错误放大输出预算重发一次，比整轮判失败划算。
_TOOL_ARGUMENT_TRUNCATION_HINTS = ("failed to parse tool call arguments",
                                   "tool call arguments as json")

# 「输入装不下窗口」不是抖动：端点已经明确说装不下，重发同一份请求必然再失败一次。
# 本地端点一次推理常要几十秒，而槽位分片会让这条错误连着出现——实测 LM Studio 以
# `--parallel 4` 加载 16384 上下文时，每槽只剩 4096，灵枢 5.2k token 的请求连续失败
# 43 次、白白耗掉二十多分钟。这类错误一律交回上层，不在这里重试。
_OVERFLOW_HINTS = ("context size has been exceeded", "context_length_exceeded",
                   "maximum context length", "reduce the length of the messages",
                   "prompt is too long", "too many tokens", "input is too long")


def _is_context_overflow(exc: BaseException) -> bool:
    """端点明确报「上下文装不下」：该换模型或调窗口，重试没有意义。"""
    text = str(exc).lower()
    return any(hint in text for hint in _OVERFLOW_HINTS)


def _is_transient(exc: BaseException) -> bool:
    """判断是否值得就地重试一次：只认连接/超时类，鉴权、额度与超窗都不重试。

    超窗判定放最前面：SDK 把它包进 `APIConnectionError`，按类名会误判成断流。
    """
    if _is_context_overflow(exc):
        return False
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    name = type(exc).__name__.lower()
    if "connection" in name or "timeout" in name:
        return True
    text = str(exc).lower()
    return any(hint in text for hint in _TRANSIENT_HINTS)


def _is_tool_argument_truncation(exc: BaseException) -> bool:
    """端点说「工具调用参数不是合法 JSON」：多半是参数没写完就撞了输出上限。"""
    text = str(exc).lower()
    return any(hint in text for hint in _TOOL_ARGUMENT_TRUNCATION_HINTS)


@dataclass
class ChatResponse:
    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    latency_ms: float
    fallback_used: bool = False
    reasoning: str = ""          # 推理模型思考内容（reasoning_content/thinking）
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    finish_reason: str = ""
    cached_input_tokens: int | None = None
    cache_write_tokens: int | None = None
    first_delta_ms: float | None = None


def output_lost(resp: ChatResponse) -> bool:
    """检查模型正文是否为空或因输出上限截断，供决策重试使用。"""
    return (not str(resp.content or "").strip()) or resp.finish_reason in ("length", "max_tokens")


async def chat_decision(
    gateway: ModelGateway,
    messages: list[dict[str, Any]],
    *,
    audit=None,
    actor: str = "",
    memory: DecisionMemory | None = None,
    **kwargs: Any,
) -> ChatResponse:
    """决策 JSON 通道：输出为空或被端点截断时加大输出余量重试一次。

    思考型模型可能把输出额度耗在思考上，正文为空或只剩半截 JSON——解析
    失败会被上层当成决策缺席走规则回退，一次重试远比误判便宜。重试失败
    沿用原响应交由上层解析兜底，不掩盖原始结果。"""
    if memory is not None:
        budget_for = getattr(gateway, "context_budget", None)
        budget = budget_for(**kwargs) if callable(budget_for) else None
        messages = memory.prepare(messages, max_input_tokens=budget,
            compact_patches=bool(getattr(getattr(gateway, "config", None), "compact_decision_patches", False)),
            stable_snapshot_prefix=bool(getattr(getattr(gateway, "config", None), "stable_snapshot_prefix", False)))
        # 追加式现场已由 DecisionMemory 管理；二次节选历史会改写缓存前缀。
        kwargs["preserve_context"] = True
        if audit is not None and memory.segment_changed:
            audit.log("context.decision_segment", actor, memory.segment_info)
    resp = await gateway.chat(messages, **kwargs)
    if output_lost(resp):
        if audit is not None:
            audit.log("llm.output_retry", actor, {
                "task_type": kwargs.get("task_type", ""),
                "finish_reason": resp.finish_reason,
                "content_chars": len(resp.content or ""),
                # 思考型模型把额度全花在 reasoning_content 上时正文为空：这条
                # 字段就是判断「是模型想太多还是端点没回」的唯一线索
                "reasoning_chars": len(resp.reasoning or "")})
        try:
            retry_kwargs = {**kwargs, "max_tokens": max(32768, (kwargs.get("max_tokens") or 0) * 2)}
            retried = await gateway.chat(messages, **retry_kwargs)
            if not output_lost(retried):
                resp = retried
        except Exception:  # noqa: BLE001, S110 —— 重试失败沿用原响应，解析端兜底
            pass
    if memory is not None and not output_lost(resp):
        # 正文不是 JSON（弱模型常无视 response_format/json 直接回散文）只是
        # 「这条不写回决策记忆」——不能在决策通道上抛出去，否则蒸馏、秘书、
        # 意图路由这些本来能各自降级的上层会一起拿不到响应。
        try:
            rememberable = isinstance(extract_json(resp.content), dict)
        except ValueError:
            rememberable = False
        if rememberable:
            memory.commit(resp.content or "",
                          reasoning=getattr(resp, "reasoning", "") or "")
    return resp


@dataclass
class BudgetTracker:
    """用量计量（token/美元/按模型/按模式）。

    只计量不拦截：进度性的杀开关（预算耗尽/模式熔断）已移除——调查正酣时
    被后端规则掐断对用户是灾难；用量数据仅供控制台展示与成本复盘。
    """

    budget_tokens: int
    budget_usd: float
    mode_budgets: dict[str, int] = field(default_factory=dict)
    used_tokens: int = 0
    used_usd: float = 0.0
    per_model_tokens: dict[str, int] = field(default_factory=dict)
    per_mode_tokens: dict[str, int] = field(default_factory=dict)
    mode: str = ""
    call_log: list[dict] = field(default_factory=list)
    # 记账钩子：每笔调用后把用量快照外发（控制台实时展示，不等终场汇总）
    on_record: Any = None
    on_call: Any = None

    def record(self, model: str, tokens: int, usd: float, ts: float = 0, **metrics: Any) -> None:
        self.used_tokens += tokens
        self.used_usd += usd
        self.per_model_tokens[model] = self.per_model_tokens.get(model, 0) + tokens
        if self.mode:
            self.per_mode_tokens[self.mode] = self.per_mode_tokens.get(self.mode, 0) + tokens
        import time as _t
        entry = {
            "ts": ts or _t.time(), "model": model,
            "tokens": tokens, "cost_usd": usd, "mode": self.mode,
            "call_id": metrics.pop("call_id", None) or uuid.uuid4().hex, **metrics}
        self.call_log.append(entry)
        if self.on_call is not None:
            self.on_call(entry)
        if self.on_record is not None:
            # 展示面失败不拖累记账主链（sink 自身须可容错，如落盘瞬时失败）
            with contextlib.suppress(Exception):
                self.on_record(self.persist_snapshot())

    def persist_snapshot(self) -> dict:
        """落盘快照：实时计数 + 逐笔时序（进程续传时回灌 BudgetTracker）。"""
        snap = self.live_snapshot()
        snap.pop("live", None)
        snap["call_series"] = self.call_series()
        return snap

    def restore(self, snap: dict) -> None:
        """回灌上一进程的累计用量与逐笔时序（续传不重新从零计起）。"""
        self.used_tokens += int(snap.get("used_tokens", 0) or 0)
        self.used_usd += float(snap.get("used_usd", 0.0) or 0.0)
        for model, tokens in (snap.get("per_model_tokens") or {}).items():
            self.per_model_tokens[model] = self.per_model_tokens.get(model, 0) + int(tokens or 0)
        for mode, tokens in (snap.get("per_mode_tokens") or {}).items():
            self.per_mode_tokens[mode] = self.per_mode_tokens.get(mode, 0) + int(tokens or 0)
        self.call_log.extend(
            e for e in (snap.get("call_series") or []) if isinstance(e, dict))

    def live_snapshot(self) -> dict:
        """轻量实时快照（不含逐笔时序——文件随写随读，保持小体积）。"""
        return {
            "used_tokens": self.used_tokens,
            "used_usd": round(self.used_usd, 6),
            "per_model_tokens": dict(self.per_model_tokens),
            "per_mode_tokens": dict(self.per_mode_tokens),
            "mode": self.mode,
            "calls": len(self.call_log),
            "cache": self.cache_snapshot(),
            "live": True,
        }

    def cache_snapshot(self) -> dict[str, Any]:
        return cache_summary(self.call_log)

    def call_series(self) -> list[dict]:
        """逐笔调用记录（时序图表数据源）。"""
        return list(self.call_log)


class ModelGateway:
    def __init__(
        self,
        registry: ModelRegistry,
        config: GatewayConfig | None = None,
        audit: AuditLogger | None = None,
        mock_backend: MockBackend | None = None,
    ):
        self.prefix_tracker = PrefixTracker()
        self.registry = registry
        self.config = config or GatewayConfig()
        self.endpoint_capabilities = EndpointCapabilities(enabled=self.config.remember_endpoint_capabilities)
        self.audit = audit or NullAuditLogger()
        self.budget = BudgetTracker(
            self.config.budget_tokens, self.config.budget_usd,
            mode_budgets=dict(self.config.mode_budget_tokens),
        )
        self._mock = mock_backend or MockBackend()
        self._rate_state: dict[str, list[float]] = {}
        # 会话级模型选择：str = 固定；callable = 每次调用现取（会话页改选择即时生效）
        self._session_model: Any = ""
        # 失效的会话选择只记一次审计（每条调用都记会淹没审计流）
        self._missing_logged: set[str] = set()
        # 端点并发闸：按端点（base_url 优先）复用信号量，避免把十几个任务同时
        # 砸到一个单槽本地模型上——那样每个请求都在排队里耗到硬超时。
        self._gates: dict[str, asyncio.Semaphore] = {}
        # 端点熔断状态：连续全链失败计数 + 熔断到期时间 + 最后一次错误
        self._breaker_failures = 0
        self._breaker_open_until = 0.0
        self._breaker_last_error = ""

    def set_session_model(self, model: Any) -> None:
        """设置本会话优先使用的模型（空 = 跟随设置页的优先级链）。

        传字符串就是快照，传 callable 则每次调用现取——Web 端传
        `lambda: session.model`，用户在会话页换了模型，下一批调用立刻改道，
        不用重启会话。取不到（会话已删）时按空处理，即回到全局优先级。
        """
        self._session_model = model or ""

    def _preferred(self) -> str:
        """本会话当前选的模型（callable 现取；异常/空值一律视为未选）。"""
        source = self._session_model
        if callable(source):
            try:
                source = source()
            except Exception:  # noqa: BLE001 —— 取不到就是没选，不能让路由陪葬
                return ""
        return str(source or "").strip()

    def session_model(self) -> str:
        """当前会话选定的模型（空串 = 跟随设置页优先级链）。"""
        return self._preferred()

    def resolve_model(self, task_type: str = "execution", *,
                      model: str | None = None) -> str:
        """此刻这条调用会落到哪个模型（不改任何状态，供界面提示与自检）。"""
        return self._route(task_type, model=model).model

    def _route(self, task_type: str, *, model: str | None,
               required_capability: str | None = None) -> ModelEntry:
        """路由入口：显式绑定 > 会话选定 > 设置页优先级链。

        会话选的模型若已被停用/改名（注册表里没了），退回优先级链而不是让
        整轮调用报「未注册的模型」——用户已经把这个模型删了，会话不该因此停摆。
        """
        prefer = (model or "").strip() or self._preferred()
        if prefer and not self.registry.has(prefer):
            if prefer not in self._missing_logged:
                self._missing_logged.add(prefer)
                self.audit.log("model.override_missing", "gateway", {
                    "model": prefer, "task_type": task_type})
            prefer = ""
        return self.registry.route(
            task_type, prefer_model=prefer or None,
            required_capability=required_capability,
        )

    def set_mode(self, mode: str) -> None:
        """设置当前运行模式（src/ctf/competition）：按模式分开计量用量。"""
        self.budget.mode = mode

    # ------------------------------------------------------------ 主入口

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        task_type: str = "execution",
        model: str | None = None,
        required_capability: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        response_format: str | None = None,
        timeout_seconds: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        on_delta: DeltaCallback | None = None,
        reasoning_effort: str = "",
        preserve_context: bool = False,
        preserve_tool_order: bool = False,
    ) -> ChatResponse:
        """统一对话入口：路由 → 限流 → 调用（主备切换）→ 计量 → 审计。

        timeout_seconds：单次后端调用硬超时；缺省用网关配置。重推理角色
        （如解题环）可放宽，避免长链推理被全局默认值中途掐死。
        tools/on_delta：原生工具调用与流式增量（主备切换时若已吐出增量，
        切换前投递 reset 让消费端清屏，避免两次尝试的文本叠加）。
        reasoning_effort：思考强度取值，按候选模型各自声明的档位把关
        （未声明的取值不下发，见 _resolve_effort）。
        max_tokens：单次输出上限。None（默认）= 不设硬顶——是否限、限多少
        由模型档案声明（ModelEntry.max_output_tokens）或端点自定；上限只影响
        生成在哪停，设小了思考型模型会把额度耗在思考上、正文被截成半截。
        小通道（路由/连通性探测）可传定值收紧。"""
        now = time.monotonic()
        if now < self._breaker_open_until:
            # 熔断中：立刻失败，不再排队、不再等 300s 硬超时。上层据此停止本轮循环。
            self.audit.log("model.breaker_open", "gateway", {
                "remaining_seconds": round(self._breaker_open_until - now, 1),
                "failures": self._breaker_failures,
                "last_error": self._breaker_last_error[:200]})
            raise ModelUnavailableError(
                f"模型端点连续不可用（已熔断 {round(self._breaker_open_until - now, 1)}s，"
                f"期间不再重试）：{self._breaker_last_error[:200]}")
        entry = self._route(
            task_type, model=model, required_capability=required_capability,
        )
        chain = [entry, *self.registry.fallback_of(entry.model)]

        # 流式增量与主备切换的衔接：已吐出的增量在切换前用 reset 清屏
        emitted = False

        async def _relay(kind: str, text: str) -> None:
            nonlocal emitted
            emitted = True
            await emit_delta(on_delta, kind, text)

        last_exc: Exception | None = None
        for idx, candidate in enumerate(chain):
            try:
                await self._rate_limit(candidate)
                if idx > 0 and emitted:
                    await emit_delta(on_delta, "reset", "")
                    emitted = False
                resp = await self._invoke_with_retry(
                    candidate, messages,
                    temperature=temperature, max_tokens=max_tokens,
                    response_format=response_format,
                    timeout_seconds=timeout_seconds,
                    tools=tools, tool_choice=tool_choice,
                    on_delta=_relay if on_delta is not None else None,
                    # 思考强度按每个候选模型各自声明的档位把关（主备档位可能不同）
                    reasoning_effort=self._resolve_effort(candidate, reasoning_effort),
                    task_type=task_type,
                    preserve_context=preserve_context, preserve_tool_order=preserve_tool_order,
                )
                # 成功一次就把熔断状态清干净：抖动恢复后不该还背着历史失败
                self._breaker_failures = 0
                self._breaker_open_until = 0.0
                self._breaker_last_error = ""
                if idx > 0:
                    resp.fallback_used = True
                    self.audit.log(
                        "model.fallback", "gateway",
                        {"from": entry.model, "to": candidate.model, "reason": str(last_exc)},
                    )
                return resp
            except Exception as exc:  # noqa: BLE001 —— 主备切换语义（4.9.3-5）
                last_exc = exc
                continue
        # 全链失败时把「为什么」也说出来：最常见的是渠道没配密钥，
        # 原始 LiteLLM 文案（Missing credentials）对用户没有指向性。
        hint = ""
        if last_exc is not None and "Missing credentials" in str(last_exc):
            hint = ("；这条渠道没有可用密钥：去「模型」页给对应供应商填 API Key，"
                    "或把它从优先级链里移掉（本机端点会自动用占位密钥，不需要填）")
        elif last_exc is not None and _is_context_overflow(last_exc):
            # 这句话要能直接指到动作上：换模型，或去端点把窗口调大。槽位分片是最常见
            # 的坑——界面显示 16384，按 4 路并行就只有 4096 可用，看着够实际不够。
            hint = ("；模型窗口装不下本轮输入：换上下文更大的模型，或把端点的窗口调大"
                    "（并行槽数会把总窗口按槽平分，单槽只有 1/N）")
        self._breaker_failures += 1
        self._breaker_last_error = f"{type(last_exc).__name__}: {last_exc}"
        if self._breaker_failures >= MODEL_BREAKER_THRESHOLD:
            self._breaker_open_until = time.monotonic() + MODEL_BREAKER_COOLDOWN_SECONDS
            self.audit.log("model.breaker_tripped", "gateway", {
                "failures": self._breaker_failures,
                "cooldown_seconds": MODEL_BREAKER_COOLDOWN_SECONDS,
                "last_error": self._breaker_last_error[:200]})
            raise ModelUnavailableError(
                f"模型端点连续 {self._breaker_failures} 次不可用，熔断 "
                f"{int(MODEL_BREAKER_COOLDOWN_SECONDS)}s 后放探活：{last_exc}{hint}") from last_exc
        raise SpiritScoutError(f"模型调用全链失败（主备均不可用）: {last_exc}{hint}")

    async def _invoke_with_retry(self, entry: ModelEntry, *args: Any, **kwargs: Any) -> ChatResponse:
        """瞬时断连/超时就地重试一次，别把整轮耗在等一个已经不回来的流上。

        远端渠道的 `Connection error` 属于「这条连接没了，换一条就好」：不重试的话
        上层要么被一次抖动拖到硬超时上限，要么直接判失败白跑一轮。只重试瞬时类错误
        （连接中断、读超时），鉴权/参数/额度错误立即上抛，不做无意义重试。

        工具调用参数被截断（llama.cpp 报 `Failed to parse tool call arguments as JSON`）
        单独再试一次，并把输出预算翻倍：那不是端点坏了，是模型想写的参数比给它的
        额度长，翻倍后同一份请求大多能一次写完。
        """
        try:
            return await self._invoke(entry, *args, **kwargs)
        except Exception as exc:
            if isinstance(exc, asyncio.CancelledError):
                raise
            if _is_tool_argument_truncation(exc) and kwargs.get("max_tokens"):
                bigger = min(int(kwargs["max_tokens"]) * 2,
                             entry.max_output_tokens or int(kwargs["max_tokens"]) * 2)
                if bigger > int(kwargs["max_tokens"]):
                    self.audit.log("model.retry", "gateway",
                                   {"model": entry.model,
                                    "reason": "tool_arguments_truncated",
                                    "error": str(exc)[:160],
                                    "max_tokens": [int(kwargs["max_tokens"]), bigger]})
                    kwargs["max_tokens"] = bigger
                    return await self._invoke(entry, *args, **kwargs)
            if not _is_transient(exc):
                raise
            self.audit.log("model.retry", "gateway",
                           {"model": entry.model, "reason": str(exc)[:200],
                            "wait_ms": int(_TRANSIENT_RETRY_DELAY * 1000)})
            await asyncio.sleep(_TRANSIENT_RETRY_DELAY)
            return await self._invoke(entry, *args, **kwargs)

    def context_budget(self, *, task_type: str = "execution", model: str | None = None,
                       required_capability: str | None = None,
                       max_tokens: int | None = None, **kwargs: Any) -> int | None:
        """和 chat 使用同一路由，向对话所有者暴露输入整理阈值。"""
        from spiritscout.gateway.context import input_window_budget

        entry = self._route(task_type, model=model,
                            required_capability=required_capability)
        return input_window_budget(entry.context_window, max_tokens or entry.max_output_tokens)

    # ------------------------------------------------------------ 内部

    def context_identity(self, *, model: str | None = None, task_type: str = "execution") -> dict[str, str]:
        """对话协议身份；不包含密钥，供显式接力核对模型与端点。"""
        entry = self._route(task_type, model=model)
        return {"model": entry.model, "provider": entry.provider,
                "base_url": entry.base_url, "api_format": entry.api_format}

    def _gate(self, entry: ModelEntry) -> asyncio.Semaphore | None:
        """端点并发闸（`max_concurrency`）：0/未声明 = 不限，返回 None。

        同一端点上不同模型共享一把闸——限制来自端点本身的槽位，不是模型 ID。
        信号量按需创建并复用，排队时间不计入单次调用硬超时（超时只管真正在飞的
        那一次），所以慢端点只会变慢，不会因为并发而集体超时失败。
        """
        limit = int(getattr(entry, "max_concurrency", 0) or 0)
        if limit <= 0:
            return None
        key = entry.base_url or entry.provider_ref or entry.model
        gate = self._gates.get(key)
        if gate is None:
            gate = asyncio.Semaphore(limit)
            self._gates[key] = gate
        return gate

    def _resolve_effort(self, entry: ModelEntry, requested: str) -> str:
        """思考强度把关：只下发该模型自己声明过的取值。

        各模型支持的思考强度并不一致（有的 low/medium/high，有的另有 ultra），
        所以档位由每个模型条目自行声明，后端不设固定候选；请求值不在声明内
        时不下发并留痕（不猜、不代填、不静默改档）。
        """
        want = (requested or "").strip()
        if not want:
            return ""
        if want in entry.reasoning_effort_levels:
            return want
        self.audit.log("model.effort_ignored", "gateway", {
            "model": entry.model, "requested": want,
            "declared": list(entry.reasoning_effort_levels),
            "reason": ("该模型未声明此思考强度取值" if entry.reasoning_effort_levels
                       else "该模型未声明思考强度"),
        })
        return ""

    async def _invoke(
        self,
        entry: ModelEntry,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        max_tokens: int | None,
        response_format: str | None,
        timeout_seconds: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        on_delta: DeltaCallback | None = None,
        reasoning_effort: str = "",
        task_type: str = "execution",
        preserve_context: bool = False,
        preserve_tool_order: bool = False,
    ) -> ChatResponse:
        backend: ChatBackend = backend_for(entry, self._mock, capabilities=self.endpoint_capabilities)
        messages = copy.deepcopy(messages)
        # 引入必须无条件执行：决策通道传 preserve_context=True 时不进下面的压缩分支，
        # 把 import 写在分支里会让后面的 clamp 直接 UnboundLocalError。
        from spiritscout.gateway.context import clamp_output_tokens

        if entry.context_window and not preserve_context:
            from spiritscout.gateway.context import (
                compact_history_tokens,
                input_window_budget,
                shrink_history_to_window,
            )

            budget = input_window_budget(entry.context_window, max_tokens or entry.max_output_tokens)
            if budget is not None:
                compact_history_tokens(messages, budget, tools=tools)
                # 节选压不进窗口时丢掉最早的几组工具往返：小窗口模型跑到几十回合
                # 后输入仍超窗，端点 400，整条路线报废；丢旧观察比丢整轮划算。
                dropped = shrink_history_to_window(
                    messages, entry.context_window, tools=tools,
                    reserve=max_tokens or entry.max_output_tokens)
                if dropped:
                    self.audit.log("model.history_trimmed", "gateway", {
                        "model": entry.model, "context_window": entry.context_window,
                        "dropped_messages": dropped,
                        "estimated_input_tokens": estimate_input_tokens(messages, tools)})
        if tools:
            tools = copy.deepcopy(tools)
            if not preserve_tool_order:
                tools = sorted(tools, key=lambda t: str(t.get("function", {}).get("name", t.get("name", ""))))
            tools = json.loads(json.dumps(tools, ensure_ascii=False, sort_keys=True))
        # 输出上限落点：调用点显式给定值优先（小通道定值）；否则按模型档案
        # 声明下发；档案也没声明就 None（请求不带该字段，端点自定）
        if max_tokens is None and entry.max_output_tokens > 0:
            max_tokens = entry.max_output_tokens
        # 输出上限不能把窗口撑破：窗口小的模型（本地 4k/8k）输入 + 输出越界时端点
        # 直接 400，上层只能看到「模型调用全链失败」。按估算输入把余量收回窗口内。
        max_tokens = clamp_output_tokens(messages, tools, entry.context_window or 0, max_tokens)
        started = time.perf_counter()
        wall = time.time()                      # 记账用墙钟（时序图按日聚合）
        scope = current_execution_scope.get() or ExecutionScope()
        actor = scope.agent_id or "gateway"
        role = next((line[6:].strip() for m in messages if m.get("role") == "system"
                     for line in str(m.get("content") or "").splitlines() if line.startswith("ROLE: ")), "")
        prefix = self.prefix_tracker.observe(
            (entry.provider, entry.base_url or "", entry.model, actor, scope.task_id or "", scope.route_id or "", task_type, role),
            messages, tools)
        # provider_ref 是用户眼里的「渠道」（供应商名），模型页/子 Agent 页都按它显示；
        # base_url 跟着一起记，排查「打到了哪个端点」时不用再翻配置。
        call = {"call_id": f"model-{uuid.uuid4().hex}", "model": entry.model, "runtime_version": __version__,
                "provider_ref": entry.provider_ref, "base_url": entry.base_url or "",
                "task_type": task_type, "task_id": scope.task_id, "route_id": scope.route_id, "cache_scope": role or task_type, **prefix}
        self.audit.log("model.started", actor, call)
        stream = None
        if on_delta is None and scope.agent_id:
            from spiritscout.gateway.streaming import AuditStream

            stream = AuditStream(self.audit, actor, call)
            on_delta = stream
        attempts = AttemptTrace(self.audit, actor, call)
        attempt_token = current_attempt_trace.set(attempts)
        hard_timeout = timeout_seconds or self.config.request_timeout_seconds
        # 端点并发闸：本地单槽端点（parallel=1）一次只能算一份请求，十几个任务
        # 同时打上去的结果是每个都在队列里耗到硬超时。排队放在硬超时外面——
        # 等得久只是慢，不会因为等太久被判失败。
        gate = self._gate(entry)
        gate_waited_ms = 0.0
        if gate is not None:
            gate_wait_started = time.perf_counter()
            await gate.acquire()
            gate_waited_ms = round((time.perf_counter() - gate_wait_started) * 1000, 1)
            if gate_waited_ms >= 1000:
                self.audit.log("model.queued", actor,
                               {**call, "wait_ms": gate_waited_ms,
                                "limit": int(entry.max_concurrency)})
        try:
            # 硬墙：交给 SDK 的 timeout 只管单次读写，流式响应可以长时间不吐字也不报错
            # （实测远端渠道挂 17 分钟才回 Connection error）。这里到点必断，让上层
            # 立刻走重试或主备切换，而不是整轮陪着一条死连接等。
            async with asyncio.timeout(hard_timeout):
                raw = await backend.complete(
                    entry, messages,
                    temperature=temperature, max_tokens=max_tokens,
                    timeout=hard_timeout,
                    response_format=response_format,
                    tools=tools, tool_choice=tool_choice, on_delta=on_delta,
                    reasoning_effort=reasoning_effort,
                )
        except TimeoutError as exc:
            attempts.finish("failed")
            if stream is not None:
                stream.flush()
            self.audit.log("model.timeout", actor,
                           {**call, "limit_seconds": hard_timeout,
                            "latency_ms": round((time.perf_counter() - started) * 1000, 1)})
            raise TimeoutError(
                f"模型单次调用超过 {hard_timeout}s 硬超时（{entry.model}）") from exc
        except BaseException as exc:
            attempts.finish("cancelled" if isinstance(exc, asyncio.CancelledError) else "failed")
            if stream is not None:
                stream.flush()
            self.audit.log("model.cancelled" if isinstance(exc, asyncio.CancelledError)
                           else "model.failed", actor,
                           {**call, "error": str(exc)[:300],
                            "latency_ms": round((time.perf_counter() - started) * 1000, 1)})
            raise
        finally:
            current_attempt_trace.reset(attempt_token)
            # 无论成败都要还槽，否则一次超时就把端点永久占住。
            if gate is not None:
                gate.release()
        if stream is not None:
            # 不支持流式的端点至少回放实际返回正文，不能伪造生成中的分析。
            if not stream.emitted and not stream.parts:
                stream("reasoning", raw.get("reasoning", ""))
                stream("text", raw.get("content", ""))
            stream.flush()
        latency = (time.perf_counter() - started) * 1000
        metrics = {key: raw.get(key) for key in ("cached_input_tokens", "cache_write_tokens", "first_delta_ms")}
        metrics.update(runtime_version=__version__, **attempts.metrics())
        metrics["patch_optimization_enabled"] = self.config.compact_decision_patches
        metrics.update(estimate_deepseek_cny(entry, wall, raw["prompt_tokens"],
                                             raw.get("cached_input_tokens"), raw["completion_tokens"]))
        metrics.update(cache_scope=role or task_type, task_id=scope.task_id, route_id=scope.route_id)
        metrics.update(input_tokens=raw["prompt_tokens"], output_tokens=raw["completion_tokens"],
                       task_type=task_type, actor=actor, call_id=call["call_id"], **prefix)
        total_tokens = raw["prompt_tokens"] + raw["completion_tokens"]
        cost = (
            raw["prompt_tokens"] / 1e6 * entry.cost_input_per_mtok
            + raw["completion_tokens"] / 1e6 * entry.cost_output_per_mtok
        )
        read = raw.get("cached_input_tokens")
        write = raw.get("cache_write_tokens")
        if read is not None and entry.cost_cached_input_per_mtok is not None:
            cost += min(read, raw["prompt_tokens"]) / 1e6 * (entry.cost_cached_input_per_mtok - entry.cost_input_per_mtok)
        if write is not None and entry.cost_cache_write_per_mtok is not None:
            cost += min(write, max(0, raw["prompt_tokens"] - (read or 0))) / 1e6 * (entry.cost_cache_write_per_mtok - entry.cost_input_per_mtok)
        self.budget.record(entry.model, total_tokens, cost, ts=wall, **metrics)
        self.audit.log(
            "model.call", actor,
            {**call, "tokens": total_tokens,
             "input_tokens": raw["prompt_tokens"], "output_tokens": raw["completion_tokens"],
             "cost_usd": round(cost, 6), "latency_ms": round(latency, 1),
             "effort": reasoning_effort, **metrics,
             "tool_calls": [c.get("name") for c in raw.get("tool_calls", [])]},
        )
        return ChatResponse(
            cached_input_tokens=raw.get("cached_input_tokens"),
            cache_write_tokens=raw.get("cache_write_tokens"),
            first_delta_ms=raw.get("first_delta_ms"),
            content=raw["content"],
            model=entry.model,
            prompt_tokens=raw["prompt_tokens"],
            completion_tokens=raw["completion_tokens"],
            cost_usd=cost,
            latency_ms=latency,
            reasoning=str(raw.get("reasoning", "") or ""),
            tool_calls=list(raw.get("tool_calls", []) or []),
            finish_reason=str(raw.get("finish_reason", "") or ""),
        )

    async def _rate_limit(self, entry: ModelEntry) -> None:
        """按模型 RPM 限流（注册表 rate_limit_rpm）。"""
        rpm = max(entry.rate_limit_rpm, 1)
        window = self._rate_state.setdefault(entry.model, [])
        now = time.monotonic()
        while True:
            window[:] = [t for t in window if now - t < 60.0]
            if len(window) < rpm:
                window.append(now)
                return
            await asyncio.sleep(max(60.0 - (now - window[0]), 0.05))
            now = time.monotonic()

    # ------------------------------------------------------------ 状态

    def usage_report(self) -> dict:
        return {
            "used_tokens": self.budget.used_tokens,
            "used_usd": round(self.budget.used_usd, 6),
            "per_model_tokens": dict(self.budget.per_model_tokens),
            "per_mode_tokens": dict(self.budget.per_mode_tokens),
            "mode": self.budget.mode,
            "call_series": self.budget.call_series(),
            "cache": self.budget.cache_snapshot(),
        }


class AgentBoundGateway:
    """按 Agent 绑定模型的网关包装（Web 编队页分配）。

    chat 未显式给 model 时注入该 Agent 被指派的模型；模型为空 = 不干预
    （维持档位路由现状）。其余属性（budget/usage_report/...）全部透传内层网关，
    预算计量、限流、主备切换、降级语义不变——本包装只改「谁来答」，不改治理。

    session_first=True 用于**主 Agent 车道**：会话页选的模型优先于编队里给
    灵枢的指派（用户当场改的选择压过全局配置），每次调用现取，改造即生效。
    """

    def __init__(self, inner: ModelGateway, model: str = "", *,
                 session_first: bool = False) -> None:
        self._inner = inner
        self._model = model
        self._session_first = session_first

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def _bound(self) -> str:
        if self._session_first:
            current = self._inner.session_model()
            if current:
                return current
        return self._model

    async def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> ChatResponse:
        bound = self._bound()
        if bound and not kwargs.get("model"):
            kwargs["model"] = bound
        return await self._inner.chat(messages, **kwargs)

    def context_budget(self, **kwargs: Any) -> int | None:
        """容量查询也必须遵从编队绑定，不能错用注册表第一个模型。"""
        bound = self._bound()
        if bound and not kwargs.get("model"):
            kwargs["model"] = bound
        return self._inner.context_budget(**kwargs)

    def resolve_model(self, task_type: str = "execution", *,
                      model: str | None = None) -> str:
        """预览时也要带上绑定：否则界面显示的模型与真正调用的不一致。"""
        bound = self._bound()
        return self._inner.resolve_model(task_type, model=model or bound or None)

    def context_identity(self, **kwargs: Any) -> dict[str, str]:
        if self._model and not kwargs.get("model"):
            kwargs["model"] = self._model
        return self._inner.context_identity(**kwargs)
