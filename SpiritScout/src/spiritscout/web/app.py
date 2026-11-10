"""FastAPI 控制台：会话、配置、状态快照、SSE 和静态页面。

启动请求由 launch.prepare_launch 校验，运行期测试边界由模型结合用户上下文维护。"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import (
    HTMLResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from spiritscout import __version__
from spiritscout.config.settings import ModelEntry, SystemConfig
from spiritscout.core.audit import AuditLogger
from spiritscout.core.exceptions import (
    ConfigurationError,
    SpiritScoutError,
)
from spiritscout.web import auth as web_auth
from spiritscout.web import vault
from spiritscout.web.routes.auth import mount_auth
from spiritscout.web.routes.local_tools import mount_local_tools
from spiritscout.web.routes.maintenance import mount_maintenance
from spiritscout.web.routes.models import mount_models
from spiritscout.web.routes.notify import mount_notify
from spiritscout.web.routes.preferences import mount_preferences
from spiritscout.web.routes.session_detail import mount_session_detail
from spiritscout.web.routes.sessions import make_require, mount_sessions
from spiritscout.web.routes.usage import mount_usage
from spiritscout.web.sessions import (
    SessionManager,
)

_STATIC = Path(__file__).parent / "static" / "index.html"
_STATIC_DIR = Path(__file__).parent / "static"
_LOGIN = _STATIC_DIR / "login.html"


class MergePayload(BaseModel):
    """二次提炼：选定条目 + 相似度阈值（服务端会再复检一次）。

    阈值默认 0.90（九成相似），页面上可改；越界的值由库层按 0.5–1.0 收口。
    ids 不再设「一次 20 条」的上限：页面上「全选」勾的是整库可提炼条目，
    分批的活由用户自己决定，后端只在复检时按两两相似度判合不合法。
    """

    ids: list[str] = Field(min_length=2, max_length=2000)
    threshold: float = Field(default=0.90, ge=0.5, le=1.0)


class AbsorbPlanPayload(BaseModel):
    """合并（交给模型）：勾选的条数没有上限，模型自己决定有没有可并入的分组。"""

    ids: list[str] = Field(min_length=1, max_length=2000)


class AbsorbApplyPayload(BaseModel):
    """合并落库：只带用户确认过的分组；落库层保证只更新、不删除。"""

    groups: list[dict[str, Any]] = Field(default_factory=list)


class MergeRestorePayload(BaseModel):
    """还原一次合并：给合并后的条目 id。"""

    merged_id: str = Field(min_length=1, max_length=80)


class ExperienceSyncPushPayload(BaseModel):
    """把经验推到仓库：提交信息可留空（按条数自动写一条）。"""

    message: str = Field(default="", max_length=200)


def _iso_ts(value: Any) -> str:
    """经验库里存的是 Unix 秒，前端按 ISO 字符串截前 19 位显示，统一转过去。"""
    try:
        return datetime.fromtimestamp(float(value), tz=UTC).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return ""









def create_app(cfg: SystemConfig, models: list[ModelEntry], *,
               max_concurrent: int = 4) -> FastAPI:
    loopback = cfg.web.host in ("127.0.0.1", "localhost", "::1")
    # 先把环境变量凭据导入管理员库，再判断是否启用登录——首次带 .env
    # 启动的非回环部署才不会误报“没有管理员”。
    admin_store = web_auth.AdminStore(cfg.workspace.root)
    admin_store.sync_from_env(cfg.web.password_env,
                              cfg.web.admin_username_env,
                              cfg.web.admin_password_env)
    auth_mode = cfg.web.auth_mode
    has_admins = admin_store.has_admins()
    # 登录只由 auth_mode 决定：none 就真的不拦（本机工作台默认直接进），
    # 库里残留的管理员账号不会把控制台重新锁上。
    auth_enabled = auth_mode == "password" and has_admins
    if cfg.web.remote_auth_required and not loopback and not auth_enabled:
        raise ConfigurationError(
            f"Web 控制台绑定 {cfg.web.host} 时必须启用管理员登录：把配置里的 "
            f"web.auth_mode 设为 password，并在 .env 中设置 "
            f"{cfg.web.admin_username_env} 与 "
            f"{cfg.web.admin_password_env}（旧版 {cfg.web.password_env} 也兼容）；"
            "只想本机用就把 host 改回 127.0.0.1，或把 remote_auth_required 设为 false")
    limiter = web_auth.LoginRateLimiter()
    vault.configure(cfg.workspace.root)   # 密钥库落在工作区（vault.db/vault.key）
    from spiritscout.resources.assistant import ResourceAssistant
    from spiritscout.resources.store import ResourceStore, resource_root
    from spiritscout.web.projects import mount_projects
    from spiritscout.web.resources import mount_resources

    # 先建 store 再建 manager：两者共用同一迁移实例，避免并发跑一次性迁移
    resource_store = ResourceStore(resource_root(cfg), cfg.resources.freshness_hours)
    manager = SessionManager(cfg, models, max_concurrent=max_concurrent,
                             resources=resource_store)
    resource_assistant = ResourceAssistant(cfg, resource_store)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # 监督协程在 lifespan 内启动（不隶属任何请求任务组），
        # 关停时停掉所有未终态会话，避免孤儿任务
        manager.start()
        resource_assistant.start()
        # 自定义技能的真源在版本库（configs/skills.yaml）：启动时同步进资源库。
        # 工作区重建会带走 catalog.db，技能不能只活在里面（仓库里没有第二份）。
        with suppress(OSError, ValueError, sqlite3.Error):
            from spiritscout.resources.skill_sync import sync_skills

            sync_skills(resource_store, cfg.resources.skills_config)
        # 旧版本把手动提炼写进了会话目录里的 experience.db：启动时并回共享库，
        # 否则「经验库」页永远看不到那次提炼（并库幂等，目标库已有同文即跳过）
        with suppress(OSError, sqlite3.Error):
            from spiritscout.knowledge.experience import (
                absorb_session_dbs,
                shared_db_path,
            )

            absorb_session_dbs(
                shared_db_path(cfg),
                Path(cfg.workspace.root) / "sessions")
        # 读取已存在的资产，不启动旧会话或发起网络探测。
        for path in (Path(cfg.workspace.root)/"sessions").glob("sess-*"):
            with suppress(OSError, ValueError, sqlite3.Error):
                resource_store.import_session(path)
        yield
        await resource_assistant.close()
        await manager.aclose()

    app = FastAPI(title="灵枢 SpiritScout 控制台", version=__version__,
                  lifespan=lifespan)
    app.state.manager = manager
    app.state.auth = admin_store
    app.state.auth_enabled = auth_enabled
    mount_resources(app, cfg, resource_store, resource_assistant)
    mount_projects(app, resource_store, manager)
    app.state.resources = resource_store
    mount_auth(app, admin_store=admin_store, auth_enabled=auth_enabled,
               limiter=limiter, loopback=loopback)
    mount_maintenance(app, cfg=cfg)
    mount_usage(app, cfg=cfg)

    # ------------------------------------------------------------ 前端

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        # 控制台外壳不进缓存：改完前端重启即生效，不用让人手动硬刷新
        return HTMLResponse(_STATIC.read_text(encoding="utf-8"),
                            headers={"Cache-Control": "no-store, must-revalidate"})

    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    # 会话创建 / Agent 编队 / 会话列表在 web/routes/sessions.py
    _require = make_require(manager)
    mount_sessions(app, manager=manager, cfg=cfg, require=_require)
    mount_models(app, cfg=cfg)
    mount_notify(app, manager=manager)
    mount_preferences(app, cfg=cfg)
    mount_local_tools(app, cfg=cfg)
    mount_session_detail(app, manager=manager, cfg=cfg, require=_require)


    from spiritscout.web.dashboard import DashboardReader

    dashboard_reader = DashboardReader()

    @app.get("/api/dashboard")
    def dashboard_data(period: str = Query("today", pattern="^(hour|today|7d|30d|all)$")) -> dict[str, Any]:
        """北京时间的执行、成果、费用与缓存总览；只读，不干预调度。"""
        from spiritscout.knowledge.experience import read_recent, shared_db_path

        data = dashboard_reader.build(manager.list(), period=period,
                                      usage_root=Path(cfg.workspace.root))
        data["experience"] = read_recent(
            shared_db_path(cfg), limit=8)
        return data

    @app.get("/api/experience")
    def experience_page(q: str = "", tag: str = "",
                        limit: int = Query(50, ge=1, le=500),
                        offset: int = Query(0, ge=0),
                        include_merged: bool = False) -> dict[str, Any]:
        """经验提炼页：自我进化的全部产出（可检索/按标签过滤）+ 提炼过程记录。

        history 从各会话审计尾段提取 experience.distill 事件——含失败与
        跳过，让「学没学到、为什么没学到」对用户完全可见。
        include_merged=true 时连「旧口径只标记不删除」的原件一起给出（可还原）；
        新口径确认保留后原件已删除，不会再出现在这里。
        """
        from spiritscout.knowledge.experience import read_page, shared_db_path

        data = read_page(
            shared_db_path(cfg),
            q=q, tag=tag, limit=limit, offset=offset,
            include_merged=include_merged)
        titles = {s.session_id: s.brief(include_summary=False)["title"]
                  for s in manager.list()}
        for item in data["items"]:
            item["source_title"] = titles.get(
                str(item.get("source_session") or ""), "")
        data["history"] = _distill_history(cfg)
        return data

    @app.get("/api/experience/merge/candidates")
    def experience_merge_candidates(threshold: float = Query(0.90, ge=0.5, le=1.0),
                                    limit: int = Query(20, ge=1, le=100)
                                    ) -> dict[str, Any]:
        """二次提炼候选：只给「整组两两都极相似」的组，供用户复核后再提炼。

        threshold 是页面上的相似度（默认 90%，可自定义），服务端不做取舍。
        """
        from spiritscout.knowledge.experience import (
            merge_candidates,
            shared_db_path,
        )

        groups = merge_candidates(
            shared_db_path(cfg),
            threshold=threshold, limit=limit)
        return {"threshold": threshold, "groups": groups, "count": len(groups)}

    @app.post("/api/experience/merge/preview")
    def experience_merge_preview(payload: MergePayload) -> dict[str, Any]:
        """只算提炼结果，不动库：页面先给用户看这份稿子，确认保留才落库。"""
        from spiritscout.knowledge.experience import (
            merge_preview,
            shared_db_path,
        )

        try:
            return merge_preview(
                shared_db_path(cfg), payload.ids, threshold=payload.threshold)
        except SpiritScoutError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/experience/merge")
    def experience_merge(payload: MergePayload) -> dict[str, Any]:
        """确认保留：提炼结果写入经验库，被提炼的原件在同一事务里删除。"""
        from spiritscout.knowledge.experience import merge_insights, shared_db_path

        try:
            return merge_insights(
                shared_db_path(cfg),
                payload.ids, threshold=payload.threshold, confirm=True,
                audit=AuditLogger(cfg.audit_log_path))
        except SpiritScoutError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/experience/merge/restore")
    def experience_merge_restore(payload: MergeRestorePayload) -> dict[str, Any]:
        """还原一次旧口径的「标记式」合并：原件解封，派生的合并条目移除。

        新口径（确认保留后原件已删）没有可还原的东西，库里查不到原件就回 404。
        """
        from spiritscout.knowledge.experience import (
            restore_merge,
            shared_db_path,
        )

        try:
            result = restore_merge(
                shared_db_path(cfg),
                payload.merged_id, audit=AuditLogger(cfg.audit_log_path))
        except SpiritScoutError as exc:
            raise HTTPException(500, str(exc)) from exc
        if result is None:
            raise HTTPException(404, f"没有这条合并记录: {payload.merged_id}")
        return result

    @app.post("/api/experience/absorb/preview")
    async def experience_absorb_preview(payload: AbsorbPlanPayload) -> dict[str, Any]:
        """合并（交给模型）：这些经验能不能并进已有的某一条。**不写库、不删任何条目。**

        与「二次提炼」不同：提炼是组内极相似→压成一条并删原件；合并只是把内容
        并进一条已有经验，被勾选的条目原样保留。
        """
        from spiritscout.config import load_model_config
        from spiritscout.knowledge.absorb import plan_absorb
        from spiritscout.knowledge.experience import shared_db_path
        from spiritscout.web import vault as key_vault
        from spiritscout.web.session_experience import _usable_models
        from spiritscout.web.sessions import _conversation_gateway

        try:
            entries = key_vault.apply_keys(load_model_config(cfg.models_config_path))
        except Exception:              # noqa: BLE001 —— 读不到配置就用启动快照
            entries = list(models or [])
        usable = _usable_models(entries)
        if not usable:
            raise HTTPException(
                400, "没有配了 API Key 的渠道：先到「模型」页配一个，再回来合并")
        audit = AuditLogger(cfg.audit_log_path)
        gateway = _conversation_gateway(cfg, usable, audit)
        timeout = int(getattr(cfg.experience, "distill_timeout_seconds", 90) or 90)
        try:
            return await plan_absorb(
                gateway, shared_db_path(cfg), payload.ids,
                timeout_seconds=timeout, audit=audit)
        except SpiritScoutError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/experience/absorb/apply")
    def experience_absorb_apply(payload: AbsorbApplyPayload) -> dict[str, Any]:
        """确认合并：只更新目标条目正文，**一行都不删**（删除即报错回滚）。"""
        from spiritscout.knowledge.absorb import apply_absorb
        from spiritscout.knowledge.experience import shared_db_path

        try:
            return apply_absorb(
                shared_db_path(cfg), payload.groups,
                audit=AuditLogger(cfg.audit_log_path))
        except SpiritScoutError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/experience/sync")
    def experience_sync_status() -> dict[str, Any]:
        """经验同步现状：本地多少条、仓库里的主清单与提交目录在哪、用哪个分支。"""
        from spiritscout.knowledge.experience import shared_db_path
        from spiritscout.knowledge.sync import (
            DEFAULT_BRANCH,
            DEFAULT_INBOX,
            DEFAULT_SYNC_PATH,
            export_payload,
            project_root,
        )

        rel = str(getattr(cfg.experience, "sync_path", "") or DEFAULT_SYNC_PATH)
        inbox = str(getattr(cfg.experience, "sync_inbox", "") or DEFAULT_INBOX)
        repo = str(getattr(cfg.experience, "sync_repo", "") or "")
        branch = str(getattr(cfg.experience, "sync_branch", "") or DEFAULT_BRANCH)
        root = Path(repo).expanduser() if repo.strip() else project_root()
        file = root / rel
        return {"local_count": export_payload(shared_db_path(cfg))["count"],
                "repo": str(root), "path": str(file), "inbox": str(root / inbox),
                "exists": file.is_file(), "branch": branch,
                "synced_at": file.stat().st_mtime if file.is_file() else 0}

    @app.post("/api/experience/sync/pull")
    def experience_sync_pull() -> dict[str, Any]:
        """拉取：把远端主清单 + 所有人提交的经验并进本地库——只补缺，不改不删。"""
        from spiritscout.knowledge.experience import shared_db_path
        from spiritscout.knowledge.sync import (
            DEFAULT_BRANCH,
            DEFAULT_INBOX,
            DEFAULT_SYNC_PATH,
            pull,
        )

        try:
            return pull(
                shared_db_path(cfg),
                repo=str(getattr(cfg.experience, "sync_repo", "") or ""),
                sync_path=str(getattr(cfg.experience, "sync_path", "") or DEFAULT_SYNC_PATH),
                inbox=str(getattr(cfg.experience, "sync_inbox", "") or DEFAULT_INBOX),
                branch=str(getattr(cfg.experience, "sync_branch", "") or DEFAULT_BRANCH),
                audit=AuditLogger(cfg.audit_log_path))
        except SpiritScoutError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/experience/sync/push")
    def experience_sync_push(payload: ExperienceSyncPushPayload | None = None) -> dict[str, Any]:
        """提交：本地经验导成自己一个文件放进 inbox → 提交 → 推送到远端。

        写成「每人一个文件」而不是改主清单：任何人有写权限就能提，不会互相冲突。
        """
        from spiritscout.knowledge.experience import shared_db_path
        from spiritscout.knowledge.sync import (
            DEFAULT_BRANCH,
            DEFAULT_INBOX,
            submit,
        )

        try:
            return submit(
                shared_db_path(cfg),
                repo=str(getattr(cfg.experience, "sync_repo", "") or ""),
                inbox=str(getattr(cfg.experience, "sync_inbox", "") or DEFAULT_INBOX),
                branch=str(getattr(cfg.experience, "sync_branch", "") or DEFAULT_BRANCH),
                message=(payload.message if payload else ""),
                user=str(getattr(cfg.experience, "sync_user", "") or ""),
                audit=AuditLogger(cfg.audit_log_path))
        except SpiritScoutError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.delete("/api/experience/{insight_id}")
    def delete_experience(insight_id: str) -> dict[str, Any]:
        """人工审核：删除一条提炼跑偏的经验（如把单题步骤当成可复用事实）。

        经验库是模型产出、用户可审可清；删除在系统审计留痕（actor=user），
        被删内容不参与后续会话召回。
        """
        from spiritscout.knowledge.experience import delete_insight, shared_db_path

        try:
            item = delete_insight(
                shared_db_path(cfg),
                insight_id, audit=AuditLogger(cfg.audit_log_path))
        except SpiritScoutError as exc:
            raise HTTPException(500, str(exc)) from exc
        if item is None:
            raise HTTPException(404, f"经验不存在: {insight_id}")
        return {"deleted": insight_id}

    def _distill_history(cfg: SystemConfig, *, limit: int = 12) -> list[dict[str, Any]]:
        """最近提炼记录（成功/空/失败/跳过）。

        只管审计日志是不够的：提炼产出的经验落在全局 experience.db，而会话一旦
        被删，``sessions/<id>/audit.jsonl`` 会跟着消失——经验库里还留着那次提炼
        产出的条目，页面上却显示「暂无提炼记录」。所以两个来源合并：

        1. 经验库按 ``source_session`` 聚合，给每个产出过经验的会话补一条「成功」；
        2. 现存会话的审计尾段仍然首选——失败、跳过、无新增这些没产出经验的结论
           只写在日志里，从经验库反推不出来。

        同一会话以审计日志为准（字段更全），日志里没出现过的才用库里的补。
        """
        audited: dict[str, list[dict[str, Any]]] = {}
        sessions_dir = Path(cfg.workspace.root) / "sessions"
        if sessions_dir.is_dir():
            for audit_path in sorted(sessions_dir.glob("*/audit.jsonl")):
                sid = audit_path.parent.name
                try:
                    with audit_path.open("rb") as fh:
                        fh.seek(0, 2)
                        size = fh.tell()
                        fh.seek(max(0, size - 131072))     # 提炼在收尾：只看尾段 128KB
                        tail = fh.read().decode("utf-8", "ignore")
                except OSError:
                    continue
                for line in tail.splitlines():
                    if '"experience.distill"' not in line:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if rec.get("type") != "experience.distill":
                        continue
                    audited.setdefault(sid, []).append(
                        {"session_id": sid, "ts": rec.get("ts", ""),
                         **(rec.get("detail") or {})})

        events: list[dict[str, Any]] = [e for rows in audited.values() for e in rows]

        try:
            from spiritscout.knowledge.experience import shared_db_path

            conn = sqlite3.connect(
                str(shared_db_path(cfg)))
            try:
                rows = conn.execute(
                    "SELECT source_session, COUNT(*), MAX(ts) FROM insights "
                    "WHERE source_session != '' GROUP BY source_session").fetchall()
            finally:
                conn.close()
        except (sqlite3.Error, OSError, ImportError):
            rows = []
        for sid, count, last_ts in rows:
            if sid in audited:
                continue        # 日志里记了这次提炼，以它为准
            events.append({"session_id": sid, "ts": _iso_ts(last_ts), "result": "ok",
                           "insights": int(count), "outcome": "从本会话提炼出经验"})

        events.sort(key=lambda e: str(e.get("ts", "")), reverse=True)
        return events[:limit]

    return app
