"""会话创建、旁路会话与 Agent 编队路由。

第二刀，接着 `routes.auth`：这一组是"开会话 / 看会话列表 / 给 Agent 指派模型"，
依赖面只有 manager 与 cfg，搬出来之后 `create_app` 里那段最长的手写路由块
（近百行）变成一次 `mount_sessions(...)`。

`make_require` 单独导出：后面还有几十个会话子资源路由要用"取不到就 404"，
与其在 `create_app` 里留一个闭包，不如就地生成一份。
"""
from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from spiritscout.config.settings import SystemConfig
from spiritscout.core.exceptions import RuleConflictError, SpiritScoutError
from spiritscout.core.models import RunMode
from spiritscout.launch import LaunchRequest, prepare_launch
from spiritscout.web import agentcfg
from spiritscout.web.sessions import Session, SessionManager


class AgentSideSessionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actor: str = Field(min_length=1, max_length=120)
    task_id: str = Field(min_length=1, max_length=120)
    mission: str = Field(min_length=1, max_length=4000)


class SessionCreatePayload(BaseModel):
    """完整校验创建流程消费的字段，拒绝在搬附件或建会话后才发现类型错误。"""

    model_config = ConfigDict(extra="forbid")

    mode: str | None = None
    mission: str | None = None
    target: str | None = None
    scope: list[str] = Field(default_factory=list)
    upload_ids: list[str] = Field(default_factory=list, max_length=20)
    platform: str | None = None
    flag_format: str | None = None
    challenges_yaml: str | None = None
    platform_yaml: str | None = None
    rules_yaml: str | None = None
    contest_type: str | None = None
    title: str = Field(default="", max_length=80)
    project_id: str = Field(default="", max_length=64)
    no_llm: StrictBool = False
    authorized: StrictBool = True
    budget_tokens: StrictInt | None = None
    rps: float = Field(default=10.0, gt=0, allow_inf_nan=False)
    allow_sensitive: StrictBool = False
    accept_rule_conflicts: StrictBool = False


class SessionModelPayload(BaseModel):
    """会话级模型选择：空串 = 回到「模型」页排的优先级链。"""

    model_config = ConfigDict(extra="forbid")
    model: str = Field(default="", max_length=120)


def make_require(manager: SessionManager) -> Callable[[str], Session]:
    """生成"取会话，取不到就 404"的取用器。"""

    def _require(session_id: str) -> Session:
        session = manager.get(session_id)
        if session is None:
            raise HTTPException(404, f"会话不存在: {session_id}")
        return session

    return _require


def resolve_staged_uploads(payload: dict[str, Any],
                           workspace_root: str | Path) -> list[Path]:
    """校验并收集任务下达携带的暂存附件（路径全部收窄在暂存区内）。"""
    ids = [str(u).strip() for u in (payload.get("upload_ids") or [])
           if str(u).strip()]
    if not ids:
        return []
    if len(ids) > 20:
        raise HTTPException(422, "一次最多携带 20 个上传附件")
    staging = (Path(workspace_root) / "uploads-staging").resolve()
    out: list[Path] = []
    for uid in ids:
        if "/" in uid or "\\" in uid or uid in (".", ".."):
            raise HTTPException(422, "上传标识不合法")
        updir = staging / uid
        if not updir.is_dir():
            raise HTTPException(422, "上传不存在或已过期，请重新选择文件")
        out.extend(sorted(p for p in updir.iterdir() if p.is_file()))
    return out


def mount_sessions(app: FastAPI, *, manager: SessionManager, cfg: SystemConfig,
                   require: Callable[[str], Session]) -> None:
    """挂会话创建与 Agent 编队路由。"""

    def _agents_view() -> dict[str, Any]:
        from spiritscout.agents.roster import roster_view
        from spiritscout.config import load_model_config

        models = [{"model": m.model, "provider": m.provider_ref,
                   "capabilities": list(m.capabilities),
                   "context_window": m.context_window}
                  for m in load_model_config(cfg.models_config_path)]
        return {"roster": roster_view(),
                "assignments": agentcfg.read_assignments(cfg.agent_models_path),
                "models": models,
                "path": cfg.agent_models_path}

    @app.post("/api/sessions", status_code=201)
    async def create_session(payload: SessionCreatePayload) -> dict[str, Any]:
        # 安全相关布尔/数值在请求模型处强类型校验；其余字段透传。
        # 授权模型：Web 在场即声明（G1 语义不变、勾选摩擦去除）——
        # 创建行为本身即授权确认，human_confirmed 照旧落审计
        payload = {**payload.model_dump(), "authorized": True}
        # 智能模式：不传 mode / 传 auto → None，由 LLM 路由按任务描述裁决
        raw_mode = str(payload.get("mode") or "").strip().lower()
        if raw_mode in ("", "auto"):
            mode = None
        else:
            try:
                mode = RunMode(raw_mode)
            except ValueError:
                raise HTTPException(422, f"未知模式: {payload.get('mode')}") from None
        staged = resolve_staged_uploads(payload, cfg.workspace.root)
        try:
            plan = prepare_launch(LaunchRequest(
                mode=mode,
                target=payload.get("target") or None,
                extra_scope=list(payload.get("scope") or []),
                platform=payload.get("platform") or None,
                allow_sensitive=bool(payload.get("allow_sensitive", False)),
                rps=float(payload.get("rps", 10.0)),
                flag_format=payload.get("flag_format") or None,
                challenges_yaml=payload.get("challenges_yaml") or None,
                platform_yaml=payload.get("platform_yaml") or None,
                rules_yaml=payload.get("rules_yaml") or None,
                contest_type=payload.get("contest_type"),
                accept_rule_conflicts=bool(
                    payload.get("accept_rule_conflicts", False)),
                mission=payload.get("mission") or None,
                # 有附件就看附件，不挑类型：赛题附件本来多是 zip/rar/7z 这类压缩包，
                # 按后缀设白名单只会把正常题目挡在外面。请求里带了 upload_ids 就
                # 认账——即便暂存已过期、解析不出文件，也该在材料化那一步报「附件
                # 失效」，而不是让用户看到「CTF 模式需要赛题清单」这种驴唇不对马嘴
                # 的提示。
                has_uploads=bool(staged) or bool(payload.get("upload_ids")),
            ))
        except RuleConflictError as exc:
            # 结构化冲突清单：前端据此弹出即时确认对话，确认后带
            # accept_rule_conflicts 重发（合规门从表单前移到触发时刻）
            raise HTTPException(422, {"code": "rule_conflict",
                                      "message": str(exc),
                                      "conflicts": exc.conflicts}) from exc
        except SpiritScoutError as exc:
            raise HTTPException(422, str(exc)) from exc
        # 智能模式：会话先按装配兜底模式登记，LLM 路由改判后由执行体更新
        normalized = dict(payload, mode=plan.authorization.mode.value,
                          mode_auto=plan.mode_auto)
        try:
            session = await manager.create(normalized, plan, staged_files=staged)
        except SpiritScoutError as exc:   # 模型注册表为空/损坏（热加载）
            raise HTTPException(422, str(exc)) from exc
        return {**session.brief(), "request": session.request}

    @app.post("/api/sessions/{session_id}/agent-sessions", status_code=201)
    async def create_agent_session(session_id: str,
                                   payload: AgentSideSessionPayload) -> dict[str, Any]:
        from spiritscout.web.workbench import side_session_source

        parent = require(session_id)
        try:
            context = side_session_source(parent, payload.actor, payload.task_id)
            mission = payload.mission.strip()
            if not mission:
                raise SpiritScoutError("请填写旁路任务")
            plan = copy.deepcopy(parent.plan or manager._rebuild_plan(parent))
            if plan is None:
                raise SpiritScoutError("无法恢复原会话授权，请先恢复原会话")
            if plan.authorization.mode.value != parent.mode:
                raise SpiritScoutError("原会话模式与授权不一致，无法创建旁路")
            plan.mission, plan.mode_auto, plan.needs_mode_routing = mission, False, False
            request = {**copy.deepcopy(parent.launch_request), "mode": parent.mode,
                       "mode_auto": False, "mission": mission,
                       "target": parent.launch_request.get("target") or parent.target,
                       "project_id": parent.project_id,
                       "title": "旁路 · " + mission[:60], "side_agent": context["agent"],
                       "side_context": context, "standing_rules": parent.standing_rules,
                       "no_llm": False}
            session = await manager.create(request, plan)
        except (SpiritScoutError, ValueError, KeyError) as exc:
            raise HTTPException(422, str(exc)) from exc
        return {**session.brief(), "request": session.request}

    @app.get("/api/agents")
    async def list_agents() -> dict[str, Any]:
        return _agents_view()

    @app.put("/api/agents/{agent_key}")
    async def assign_agent_model(agent_key: str,
                                 payload: dict[str, Any]) -> dict[str, Any]:
        """给 Agent 分配模型（空串 = 清除分配，回到档位路由）。"""
        from spiritscout.agents.profiles import PROFILE_BY_KEY
        from spiritscout.config import load_model_config

        model = str(payload.get("model") or "").strip()
        profile = PROFILE_BY_KEY.get(agent_key)
        if profile is None or not profile.configurable:
            raise HTTPException(422, f"Agent 不支持模型指派: {agent_key}")
        valid = {m.model for m in load_model_config(cfg.models_config_path)}
        try:
            agentcfg.set_assignment(cfg.agent_models_path, agent_key, model, valid)
        except SpiritScoutError as exc:
            raise HTTPException(422, str(exc)) from exc
        return _agents_view()

    @app.post("/api/sessions/{session_id}/model")
    async def select_session_model(session_id: str,
                                   payload: SessionModelPayload) -> dict[str, Any]:
        """把本会话的模型定成指定条目（空 = 撤销，跟随全局优先级）。

        只影响这一个会话：灵枢车道与未在编队页指派的子 Agent 立刻改用它；
        编队页给具体子 Agent 的指派仍然优先。保存即生效，运行中改也认。
        """
        require(session_id)
        try:
            session = manager.set_model(session_id, payload.model)
        except SpiritScoutError as exc:
            raise HTTPException(422, str(exc)) from exc
        if session is None:
            raise HTTPException(404, f"会话不存在: {session_id}")
        return {**session.brief(), "request": session.request}

    @app.get("/api/sessions")
    def list_sessions() -> dict[str, Any]:
        return {"sessions": [s.brief(include_summary=False)
                             for s in manager.list()]}
