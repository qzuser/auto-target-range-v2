"""会话读取、协作与上传路由。

第四刀：`/api/sessions/{id}` 下面那一整套（详情、对话、补丁、黑板状态、成果、
漏洞、轨迹、执行台账、审计页与事件流、停止/暂停/续传、审批与提问、消息、附件、
报告与审计下载），连同它自己的只读快照器 `_read_state`/`_read_challenge_progress`
和三个请求模型，一起搬出 `create_app`。

这些端点都是"取会话 → 读它的一面 → 回 JSON"的薄壳，依赖只有 manager、cfg 和
取用器 `require`；留在 `create_app` 里既撑大装配函数，也让"读接口改了行为"
和"装配改了依赖"两类改动混在同一个 diff 里。

`_read_state` 本身仍长（160 行左右）——它是一份扁平快照字典，字段逐个来自会话
对象；拆它需要先有分组约定，等下一刀再说，先别为行数硬切。
"""
from __future__ import annotations

import copy
import json
import shutil
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    StreamingResponse,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    model_validator,
)

from spiritscout.blackboard import Blackboard
from spiritscout.config.settings import SystemConfig
from spiritscout.core.audit import AuditLogger, tool_preview
from spiritscout.core.exceptions import SpiritScoutError
from spiritscout.core.models import BlackboardLayer
from spiritscout.web import wp_profile
from spiritscout.web.events import (
    read_activity_page,
    read_audit_page,
    stream_audit,
)
from spiritscout.web.sessions import (
    TERMINAL_STATES,
    Session,
    SessionManager,
    _conversation_gateway,  # 同包内部协作：写手类功能共用同一份模型通道构造
)


class ApprovalDecision(BaseModel):
    """审批裁决体：allow 必须是真布尔——字符串 "false"/"0" 等真值文本
    一律 422（安全布尔不做隐式转换）。"""

    allow: StrictBool


class QuestionAnswerPayload(BaseModel):
    """回答及显式扩围目标；拒绝把空答复或错误类型吞成已作答。

    choice=单选下标；choices=多选下标；text 在多选问题里作为补充说明。
    """

    model_config = ConfigDict(extra="forbid")
    choice: StrictInt | None = None
    choices: list[StrictInt] | None = Field(default=None, max_length=6)
    text: str = Field(default="", max_length=1000)
    add_targets: list[str] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def require_answer(self) -> QuestionAnswerPayload:
        if self.choice is not None and self.choices:
            raise ValueError("choice 与 choices 只能二选一")
        if self.choice is None and not self.choices and not self.text.strip() \
                and not self.add_targets:
            raise ValueError("请选择选项或填写答复")
        return self


class SessionPatchPayload(BaseModel):
    """会话局部更新：用字段集合区分「未传」与「传空串」。"""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=80)
    project_id: str | None = Field(default=None, max_length=64)


class WriteUpTeam(BaseModel):
    """WP 信息页里的团队信息。全部可空——不填就按材料里的事实生成。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="", max_length=120)
    members: list[str] = Field(default_factory=list, max_length=20)
    affiliation: str = Field(default="", max_length=120)
    contest: str = Field(default="", max_length=120)
    notes: str = Field(default="", max_length=1000)


class WriteUpRequest(BaseModel):
    """生成 WP 时随请求带上的人工信息：团队信息 + 手改的题目分章。

    `directions` 的键是题目 id，值是七个分章之一（也接受 web/pwn 这类别名，
    服务端会归一）。不在表里的题按题面自动判定。
    """

    model_config = ConfigDict(extra="forbid")

    team: WriteUpTeam | None = None
    directions: dict[str, str] = Field(default_factory=dict, max_length=200)

def _read_challenge_progress(session: Session) -> dict[str, Any] | None:
    """只读平台进度快照，刷新页面和重开历史会话沿用同一份完成标记。"""
    if session.mode != "competition":
        return None
    try:
        progress = json.loads((session.workspace / "competition_progress.json").read_text(
            encoding="utf-8"))
    except (OSError, ValueError):
        progress = (session.summary.get("run") or {}).get("platform")
    if not isinstance(progress, dict) or "solved_ids" not in progress:
        return None
    solved, unsolved = progress.get("solved_ids"), progress.get("unsolved_ids")
    if not isinstance(solved, list) or not isinstance(unsolved, list):
        return None
    solved_ids = sorted({str(cid) for cid in solved if isinstance(cid, (str, int))})
    unsolved_ids = sorted({str(cid) for cid in unsolved
                           if isinstance(cid, (str, int))} - set(solved_ids))
    return {"total_challenges": len(solved_ids) + len(unsolved_ids),
            "solved_ids": solved_ids, "unsolved_ids": unsolved_ids,
            "updated_at": progress.get("updated_at")}


def _read_state(session: Session) -> dict[str, Any]:
    """数据面快照：短连接只读打开会话黑板（WAL 下与写入侧不互堵）。

    查询配方复用 monitor.panel 的只读组合（层计数 / TASK_STATE / VULN /
    flags.json），输出 JSON 而非文本面板。
    """
    from spiritscout.tools.journal import read_recovery_view
    from spiritscout.web.process_graph import read_process_graph

    run_summary: dict[str, Any] = session.summary.get("run", {})
    # 实时用量：运行中由网关逐笔持久化（usage.db，兼容旧 usage.json），终态回退运行汇总
    live_usage = session.model_usage()
    state: dict[str, Any] = {
        "session": session.brief(include_summary=False),
        "recovery": read_recovery_view(session.bb_path, include_inflight=session.status != "running"),
        "layers": {}, "tasks": [],
        "vulns": {"by_status": {}, "items": []},
        "flags": None,
        "challenge_progress": _read_challenge_progress(session),
        "pending_approvals": session.approvals.view(),
        "pending_questions": session.questions.view(),
        "ring": session.ring.snapshot(),
        "user_opinions": session.opinions[-8:],
        "round_views": run_summary.get("round_views", []),
        "model_usage": live_usage or run_summary.get("model_usage"),
        "verify": session.summary.get("verify"),
        "business_context": None,
        "topology": {"dag_nodes": [], "tasks": [],
                     "process": read_process_graph(session.audit_path)},
    }
    if not session.bb_path.exists():
        # 黑板未建（排队中）：终态摘要兜底（重开历史会话）
        state["topology"]["dag_nodes"] = run_summary.get("dag_nodes", [])
        return state
    bb = Blackboard(session.bb_path, bus=None, readonly=True)
    try:
        for layer in BlackboardLayer:
            state["layers"][layer.value] = bb.count(layer)
        for rec in bb.query(BlackboardLayer.TASK_STATE, limit=100):
            data = rec["data"]
            if "dag_snapshot" in data:
                # 主 Agent 每轮落盘的 DAG 快照（拓扑数据源，非任务记录）
                state["topology"]["dag_nodes"] = data["dag_snapshot"]
                continue
            t = data.get("task", {})
            state["tasks"].append({
                "task_id": t.get("task_id"), "task_type": t.get("task_type"),
                "agent_type": t.get("agent_type"), "status": t.get("status"),
                "round_no": t.get("round_no"),
                "challenge_id": str(((t.get("payload") or {}).get("challenge") or {}).get("id") or ""),
                "result_summary": str(t.get("result_summary") or "")[:200],
                "parent_dag_node": t.get("parent_dag_node"),
                "routes": [
                    {"route_id": r.get("route_id"),
                     "name": r.get("name"), "status": r.get("status"),
                     "health": r.get("health"), "progress": r.get("progress"),
                     "value_score": r.get("value_score"),
                     "risk_score": r.get("risk_score"),
                     "steps_executed": r.get("steps_executed"),
                     "note": (r.get("notes") or [""])[-1][:200]}
                    for r in data.get("routes", [])
                ],
            })
            state["topology"]["tasks"].append({
                "task_id": t.get("task_id"), "task_type": t.get("task_type"),
                "agent_type": t.get("agent_type"), "status": t.get("status"),
                "round_no": t.get("round_no"),
                "parent_dag_node": t.get("parent_dag_node"),
                "routes_done": sum(1 for r in data.get("routes", [])
                                   if r.get("status") == "done"),
                "routes_total": len(data.get("routes", [])),
                "steps": sum(int(r.get("steps_executed") or 0)
                             for r in data.get("routes", [])),
                "routes": [
                    {"route_id": r.get("route_id"),
                     "name": r.get("name"), "status": r.get("status"),
                     "progress": r.get("progress"),
                     "note": (r.get("notes") or [""])[-1][:200]}
                    for r in data.get("routes", [])
                ],
            })
        if not state["topology"]["dag_nodes"]:
            # 终态会话兜底：摘要中的最终 DAG（如快照记录被清理）
            state["topology"]["dag_nodes"] = run_summary.get("dag_nodes", [])
        state["business_context"] = bb.read(
            BlackboardLayer.TOPOLOGY, "business-context")
        state["observed_evidence"] = [
            {"url": tool_preview({"url": rec["data"].get("value", "")}),
             "record_id": rec["record_id"],
             "method": (rec["data"].get("attrs") or {}).get("method", "GET"),
             "status_code": (rec["data"].get("attrs") or {}).get("status_code"),
             "note": "已观测登记，待业务分析整理"}
            for rec in bb.query(BlackboardLayer.ASSET, limit=100)
            if rec["data"].get("asset_type") in {"endpoint", "app"}]
        by_status: dict[str, int] = {}
        for rec in bb.query(BlackboardLayer.VULN, limit=50):
            d = rec["data"]
            status = str(d.get("status", "candidate"))
            by_status[status] = by_status.get(status, 0) + 1
            state["vulns"]["items"].append({
                "vuln_id": d.get("vuln_id"), "title": d.get("title"),
                "vuln_type": d.get("vuln_type"), "severity": d.get("severity"),
                "status": status, "cvss_score": d.get("cvss_score"),
                "poc_verified": d.get("poc_verified"),
                "verification": d.get("verification", {}),
                "false_positive_reason": d.get("false_positive_reason"),
                "endpoint": d.get("endpoint"),
            })
        state["vulns"]["by_status"] = bb.status_counts(BlackboardLayer.VULN)
        state["vulns"]["total"] = bb.count(BlackboardLayer.VULN)
        state["vulns"]["has_more"] = state["vulns"]["total"] > len(state["vulns"]["items"])
        # 灵枢应答流：拓扑「你 → 灵枢」节点的回执展示
        replies = []
        topology_records = bb.query(BlackboardLayer.TOPOLOGY, limit=400)
        for rec in topology_records:
            d = rec["data"]
            if isinstance(d, dict) and d.get("kind") == "reply":
                replies.append(d)
        replies.sort(key=lambda d: float(d.get("ts") or 0))
        state["master_replies"] = replies[-8:]
        # 发现台账：拓扑「发现」组数据源（共享笔记/入口/Flag 落黑板，跨轮持久）
        findings: list[dict[str, Any]] = []
        for rec in topology_records:
            d = rec["data"]
            if isinstance(d, dict) and d.get("kind") == "finding":
                findings.append({**d, "finding_id": rec["record_id"]})
        findings.sort(key=lambda d: float(d.get("ts") or 0))
        state["findings"] = findings[-80:]
        if session.flags_path.exists():
            try:
                flags = json.loads(
                    session.flags_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                flags = []
            state["flags"] = {
                "total": len(flags),
                "submitted": sum(1 for f in flags if f.get("submitted")),
                "accepted": sum(1 for f in flags if f.get("accepted")),
                "items": [
                    {"value": f.get("value"), "challenge_id": f.get("challenge_id"),
                     "submitted": f.get("submitted"), "accepted": f.get("accepted")}
                    for f in flags[:50]
                ],
            }
    finally:
        bb.close()
    # 黑板保留历次续传记录；状态页以当前 DAG 为准，历史任务仍可在审计中查。
    current_task_ids = {
        str(task_id)
        for node in state["topology"]["dag_nodes"]
        for task_id in node.get("task_ids", [])
    }
    if current_task_ids:
        state["tasks"] = [
            task for task in state["tasks"]
            if str(task.get("task_id")) in current_task_ids
        ]
        state["topology"]["tasks"] = [
            task for task in state["topology"]["tasks"]
            if str(task.get("task_id")) in current_task_ids
        ]
    return state


def mount_session_detail(app: FastAPI, *, manager: SessionManager,
                         cfg: SystemConfig,
                         require: Any) -> None:
    """挂会话详情、协作与上传路由。"""

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str) -> dict[str, Any]:
        session = require(session_id)
        detail = session.brief()
        detail["request"] = session.request
        return detail

    @app.get("/api/sessions/{session_id}/conversation")
    def agent_conversation(session_id: str) -> dict[str, Any]:
        """旁路栏只读取对话与待办，不重建主会话黑板快照。"""
        session = require(session_id)
        if not session.request.get("side_agent"):
            raise HTTPException(422, "该会话不是子 Agent 旁路会话")
        return {"session": session.brief(include_summary=False),
                "messages": copy.deepcopy(session.dialogue_history),
                "pending_approvals": session.approvals.view(),
                "pending_questions": session.questions.view()}

    @app.patch("/api/sessions/{session_id}")
    async def patch_session(session_id: str,
                            payload: SessionPatchPayload) -> dict[str, Any]:
        """局部更新会话：只处理请求里显式出现的字段。

        空标题 = 恢复自动摘要名；空 project_id = 移入未分类。两个字段
        互不牵连——只移动项目不会顺手清掉用户自定义标题。
        """
        session = require(session_id)
        fields = payload.model_fields_set
        if not fields:
            raise HTTPException(422, "未提供要修改的字段")
        if "title" in fields:
            manager.rename(session_id, str(payload.title or ""))
        if "project_id" in fields:
            try:
                manager.set_project(session_id, str(payload.project_id or ""))
            except SpiritScoutError as exc:
                raise HTTPException(422, str(exc)) from exc
        return session.brief(include_summary=False)

    @app.get("/api/sessions/{session_id}/state")
    def session_state(session_id: str) -> dict[str, Any]:
        return _read_state(require(session_id))

    @app.get("/api/sessions/{session_id}/deliverables")
    def session_deliverables(session_id: str, kind: str = "all",
                             q: str = Query("", max_length=200),
                             offset: int = Query(0, ge=0),
                             limit: int = Query(60, ge=1, le=200)) -> dict[str, Any]:
        from spiritscout.web.deliverables import read_deliverables

        try:
            return read_deliverables(require(session_id).workspace, kind=kind,
                                     query=q, offset=offset, limit=limit)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/sessions/{session_id}/vulnerabilities")
    def session_vulnerabilities(session_id: str, offset: int = Query(0, ge=0),
                                limit: int = Query(50, ge=1, le=200)) -> JSONResponse:
        from spiritscout.web.deliverables import read_vulnerability_page

        return JSONResponse(read_vulnerability_page(require(session_id).workspace, offset, limit),
                            headers={"Cache-Control": "no-store"})

    @app.get("/api/sessions/{session_id}/record-history")
    def session_record_history(session_id: str, layer: str = Query(..., max_length=40),
                               record_id: str = Query(..., max_length=300),
                               before: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=50)) -> JSONResponse:
        from spiritscout.web.deliverables import read_record_history

        page = read_record_history(require(session_id).workspace, layer, record_id, before, limit)
        return JSONResponse(page, headers={"Cache-Control": "no-store"})

    @app.get("/api/sessions/{session_id}/artifacts/download")
    def session_artifact(session_id: str, path: str = Query(..., max_length=1000)) -> StreamingResponse:
        from spiritscout.web.deliverables import open_artifact

        try:
            file = open_artifact(require(session_id).workspace, path)
        except (OSError, ValueError) as exc:
            # NUL 等非法路径字符抛 ValueError——按「不存在」404 处理而非 500
            raise HTTPException(404, "产出文件不存在或不在本会话产出目录中") from exc

        def chunks() -> Iterator[bytes]:
            with file:
                while chunk := file.read(65536):
                    yield chunk

        return StreamingResponse(chunks(), media_type="application/octet-stream", headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(Path(path).name)}"})

    @app.get("/api/sessions/{session_id}/executions")
    async def session_executions(session_id: str, after: int = Query(0, ge=0),
                                  limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
        """执行元数据分页；不返回参数、凭据或原始工具输出。"""
        from spiritscout.tools.journal import read_execution_page

        return read_execution_page(require(session_id).bb_path, after=after, limit=limit)

    @app.get("/api/sessions/{session_id}/tool-parameters")
    def session_tool_parameters(session_id: str, tool: str = Query(..., max_length=300),
                               digest: str = Query(..., pattern=r"^[0-9a-f]{64}$")) -> JSONResponse:
        from spiritscout.web.tool_parameters import read_tool_parameters

        result = read_tool_parameters(require(session_id).workspace, tool, digest)
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    @app.get("/api/sessions/{session_id}/recovery")
    async def session_recovery(session_id: str) -> dict[str, Any]:
        from spiritscout.tools.journal import read_recovery_view

        session = require(session_id)
        return read_recovery_view(session.bb_path, include_inflight=session.status != "running")

    @app.get("/api/sessions/{session_id}/execution-events")
    async def session_execution_events(session_id: str, after: int = Query(0, ge=0),
                                        limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
        """数据库事件游标独立于原 JSONL SSE 的行号，断线后可补读。"""
        from spiritscout.tools.journal import read_execution_page

        page = read_execution_page(require(session_id).bb_path, events=True,
                                   after=after, limit=limit)
        return {"cursor_version": "execution-v1", **page}

    @app.get("/api/sessions/{session_id}/audit-page")
    def session_audit_page(session_id: str, before: int | None = Query(None, ge=0),
                           limit: int = Query(160, ge=1, le=250),
                           activity: bool = False) -> dict[str, Any]:
        reader = read_activity_page if activity else read_audit_page
        return reader(require(session_id).audit_path, before=before, limit=limit)

    @app.get("/api/sessions/{session_id}/events")
    async def session_events(session_id: str, request: Request) -> StreamingResponse:
        session = require(session_id)
        try:
            # ?last=N 供前端看门狗显式断点续传（EventSource 自动重连走头部）
            last = int(request.query_params.get("last")
                       or request.headers.get("last-event-id", "0") or 0)
        except ValueError:
            last = 0
        byte_mode = request.query_params.get("cursor") == "bytes"
        try:
            offset = int(request.headers.get("last-event-id")
                         or request.query_params.get("offset", "0")) if byte_mode else None
        except ValueError:
            offset = 0
        return StreamingResponse(
            stream_audit(session.audit_path, last,
                         byte_offset=offset,
                         is_terminal=lambda: session.status in TERMINAL_STATES),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/sessions/{session_id}/stop")
    async def stop_session(session_id: str) -> dict[str, Any]:
        session = await manager.stop(session_id)
        if session is None:
            raise HTTPException(404, f"会话不存在: {session_id}")
        return session.brief(include_summary=False)

    @app.post("/api/sessions/{session_id}/pause")
    async def pause_session(session_id: str) -> dict[str, Any]:
        """协作式暂停：灵枢图节点与子 Agent 步骤在检查点挂起（在途动作跑完）。"""
        session = await manager.set_paused(session_id, True)
        if session is None:
            raise HTTPException(404, f"会话不存在: {session_id}")
        return session.brief(include_summary=False)

    @app.post("/api/sessions/{session_id}/resume")
    async def resume_paused_session(session_id: str) -> dict[str, Any]:
        """从暂停继续（与「续传」不同：会话从未停止，只是检查点放行）。"""
        session = await manager.set_paused(session_id, False)
        if session is None:
            raise HTTPException(404, f"会话不存在: {session_id}")
        return session.brief(include_summary=False)

    @app.post("/api/sessions/{session_id}/approvals/{approval_id}")
    async def decide_approval(session_id: str, approval_id: str,
                              payload: ApprovalDecision) -> dict[str, Any]:
        """高风险动作即时确认裁决：{"allow": true|false}（严格布尔）。

        允许 = 本次会话内该动作放行（后续同动作不再询问）；
        拒绝 = 本次调用按策略违规拒绝（分支留痕后继续）。
        """
        session = manager.get(session_id)
        if session is None:
            raise HTTPException(404, f"会话不存在: {session_id}")
        allow = payload.allow
        if not session.approvals.decide(approval_id, allow):
            raise HTTPException(409, f"待确认项不存在或已裁决: {approval_id}")
        return {"approval_id": approval_id, "allow": allow}

    @app.post("/api/sessions/{session_id}/questions/{question_id}")
    async def answer_question(session_id: str, question_id: str,
                              payload: QuestionAnswerPayload) -> dict[str, Any]:
        """回答模型发起的提问：{"choice": 选项下标} 或 {"choices": [多选下标]}
        或 {"text": 自由输入}，{"add_targets": [...]} 为用户勾选的扩围目标
        （写入会话批准集）。"""
        session = manager.get(session_id)
        if session is None:
            raise HTTPException(404, f"会话不存在: {session_id}")
        try:
            ok = session.questions.answer(
                question_id, choice=payload.choice, choices=payload.choices,
                text=payload.text, add_targets=payload.add_targets)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if not ok:
            raise HTTPException(409, f"待答问题不存在或已作答: {question_id}")
        return {"question_id": question_id, "answered": True}

    # ------------------------------------------------------------ 会话协作（用户 → 灵枢）

    _MAX_UPLOAD_BYTES = 50 * 1024 * 1024

    def _clean_upload_name(name: str) -> str:
        """附件名安全化：只留 basename，拒绝路径分隔符/控制字符/超长。"""
        clean = Path(name.replace("\\", "/")).name.strip()
        if (not clean or clean in (".", "..") or len(clean) > 200
                or any(ord(c) < 32 for c in clean)):
            raise HTTPException(422, "附件名不合法")
        return clean

    def _gc_staging(root: Path, *, max_age_s: float = 86400.0) -> None:
        """暂存区惰性回收：超过 24h 未被会话创建带走的上传整目录清除。"""
        now = time.time()
        for d in root.iterdir():
            try:
                if d.is_dir() and now - d.stat().st_mtime > max_age_s:
                    shutil.rmtree(d, ignore_errors=True)
            except OSError:
                continue

    @app.post("/api/uploads")
    async def stage_upload(request: Request, name: str = Query(...)) -> dict[str, Any]:
        """任务下达前暂存附件（初始会话的附件上传）。

        请求体为文件原始字节，?name= 携带文件名。返回 upload_id，创建会话
        时随 upload_ids 一并材料化进会话工作区；未被带走的暂存 24h 后惰性回收。
        """
        clean = _clean_upload_name(name)
        body = await request.body()
        if not body:
            raise HTTPException(422, "附件内容为空")
        if len(body) > _MAX_UPLOAD_BYTES:
            raise HTTPException(
                413, f"附件过大（上限 {_MAX_UPLOAD_BYTES // (1024 * 1024)}MB）")
        staging = Path(cfg.workspace.root) / "uploads-staging"
        staging.mkdir(parents=True, exist_ok=True)
        _gc_staging(staging)
        updir = staging / uuid.uuid4().hex[:12]
        updir.mkdir()
        dest = updir / clean
        if dest.exists():                      # 单目录内同名（理论不可达）不覆盖
            stem, suffix, n = dest.stem, dest.suffix, 2
            while dest.exists():
                dest = updir / f"{stem}-{n}{suffix}"
                n += 1
        dest.write_bytes(body)
        return {"upload_id": updir.name, "name": dest.name, "size": len(body)}

    @app.post("/api/sessions/{session_id}/messages")
    async def post_message(session_id: str,
                           payload: dict[str, Any]) -> dict[str, Any]:
        """会话任意时刻给灵枢发消息：入会话收件箱 + 落对话史 + 审计留痕。

        灵枢在最近的决策点取走消费：派发期督导（~2s 节拍，化为对子 Agent
        的方向建议）或轮末复盘；消费动作有审计事件，意见不重不漏。
        会话已终态时消息即这一轮对话的输入（对话史末尾接着聊）——灵枢带着
        同一工作区、审计与 Flag 库和全部上下文继续，提问即回答，
        布置新方向即派工，与网页版大模型对话同一形态。
        """
        session = require(session_id)
        content = str(payload.get("content") or "").strip()
        if not content:
            raise HTTPException(422, "意见内容为空")
        if len(content) > 4000:
            raise HTTPException(422, "意见过长（≤4000 字）")
        session.user_inbox.append(session.remember_user_message(content))
        # 拓扑图/状态面展示用：历史意见（收件箱是消费语义，另一份不可变留档）
        session.opinions.append({"text": content, "ts": time.time()})
        del session.opinions[:-8]
        # 保存消息后再通知执行通道，确保续传可恢复对话。
        manager._persist(session)
        AuditLogger(session.audit_path).log(
            "user.message", "user", {"content": content})
        resumed = False
        if session.status in TERMINAL_STATES:
            try:
                await manager.resume(session_id)
                resumed = True
            except SpiritScoutError as exc:
                raise HTTPException(409, str(exc)) from exc
            except Exception as exc:
                # 续传失败必须可读，不能以 internal error 蒙用户
                # （会话状态由 resume 自身保证不翻转）
                raise HTTPException(
                    503, f"续传未完成：{type(exc).__name__}: {exc}") from exc
        return {"queued": True, "resumed": resumed}

    @app.post("/api/sessions/{session_id}/attachments")
    async def upload_attachment(session_id: str, request: Request,
                                name: str = Query(...)) -> dict[str, Any]:
        """会话区上传附件（请求体为文件原始字节，?name= 携带文件名）。

        落到会话工作区 attachments/——file_analyze 的允许目录、沙箱工作区
        的子目录，两类工具通道都能直接读取；审计留痕后由灵枢在下一决策点
        知会各 Agent（督导建议里带文件路径）。终态会话也可上传：
        附件随下一次续传（发消息触发）进入决策环。
        """
        session = require(session_id)
        clean = _clean_upload_name(name)
        body = await request.body()
        if not body:
            raise HTTPException(422, "附件内容为空")
        if len(body) > _MAX_UPLOAD_BYTES:
            raise HTTPException(
                413, f"附件过大（上限 {_MAX_UPLOAD_BYTES // (1024 * 1024)}MB）")
        dest_dir = session.workspace / "attachments"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / clean
        if dest.exists():                      # 同名不覆盖：追加序号
            stem, suffix, n = dest.stem, dest.suffix, 2
            while dest.exists():
                dest = dest_dir / f"{stem}-{n}{suffix}"
                n += 1
        dest.write_bytes(body)
        AuditLogger(session.audit_path).log("user.attachment", "user", {
            "name": dest.name, "size": len(body), "path": str(dest)})
        return {"name": dest.name, "size": len(body), "path": str(dest)}

    @app.delete("/api/sessions/{session_id}")
    async def delete_session(session_id: str,
                             confirm: bool = Query(False)) -> dict[str, Any]:
        try:
            session = await manager.delete(session_id, confirm=confirm)
        except SpiritScoutError as exc:
            raise HTTPException(409, str(exc)) from exc
        if session is None:
            raise HTTPException(404, f"会话不存在: {session_id}")
        return {"deleted": session_id}

    @app.get("/api/sessions/{session_id}/report")
    async def session_report(session_id: str) -> dict[str, Any]:
        session = require(session_id)
        report = session.report_path()
        if report is None:
            raise HTTPException(404, "报告尚未生成（任务完成后可用）")
        return {"path": str(report),
                "markdown": report.read_text(encoding="utf-8")}

    @app.get("/api/sessions/{session_id}/report/download")
    async def session_report_download(session_id: str) -> FileResponse:
        """报告文件下载（Web 功能补全）。"""
        report = require(session_id).report_path()
        if report is None:
            raise HTTPException(404, "报告尚未生成（任务完成后可用）")
        return FileResponse(report, media_type="text/markdown",
                            filename=report.name)

    # ------------------------------------------------------ CTF 解题思路（WP）

    def _writable_models(cfg: SystemConfig, manager: SessionManager) -> list[Any]:
        """写手用的模型清单：现读配置并解出密钥。

        `manager.models` 是控制台启动那一刻的快照；用户在控制台改过密钥之后它
        就不再带 key，直接拿它建通道会静默退化成提纲。所以按跑任务的方式现读
        一遍，只有连配置都读不到时才回落到启动快照。
        """
        from spiritscout.config import load_model_config
        from spiritscout.web import vault as key_vault

        try:
            return key_vault.apply_keys(load_model_config(cfg.models_config_path))
        except Exception:  # noqa: BLE001 —— 读不到配置就用启动时的清单兜底
            return list(manager.models or [])

    def _wp_dir(session: Session) -> Path:
        """WP 独立目录：不与 reports/*.md 混放（报告取最新一份，混放会串）。"""
        return session.workspace / "writeup"

    def _latest_wp(session: Session) -> Path | None:
        folder = _wp_dir(session)
        if not folder.is_dir():
            return None
        files = sorted(folder.glob("wp-*.md"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        return files[0] if files else None

    def _wp_payload(session: Session) -> dict[str, Any]:
        path = _latest_wp(session)
        if path is None:
            return {"path": None, "markdown": None, "updated_at": None}
        return {
            "path": str(path),
            "markdown": path.read_text(encoding="utf-8"),
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S",
                                        time.localtime(path.stat().st_mtime)),
        }

    def _session_challenges(session: Session, *,
                            flags: list[Any] | None = None) -> list[dict[str, Any]]:
        """题目清单，逐级回退：计划 → 落盘题面 YAML → 从 Flag 反推的单题。

        第三级是给"任务原文里就一道题、没有结构化题面"的会话用的——那种会话
        解完只在 `flags.json` 里留下 `mission-1`，不该因此写不出 WP。
        """
        plan = session.plan
        challenges = [c for c in (getattr(plan, "challenges", None) or [])
                      if isinstance(c, dict)]
        if challenges:
            return challenges
        yaml_text = str((session.launch_request or {}).get("challenges_yaml") or "")
        if yaml_text:
            from spiritscout.launch import parse_challenges_yaml

            try:
                rows = [c for c in parse_challenges_yaml(yaml_text)
                        if isinstance(c, dict)]
            except Exception:  # noqa: BLE001 —— 题面解析失败继续往下回退
                rows = []
            if rows:
                return rows
        return _synth_challenges_from_flags(session, flags or [])

    def _synth_challenges_from_flags(session: Session,
                                     flags: list[Any]) -> list[dict[str, Any]]:
        """没有题面时，用 Flag 上的题目 id 与任务原文拼出题目条目。"""
        from spiritscout.ctf.writeup import direction_key

        mission = str((session.request or {}).get("mission") or "").strip()
        headline = mission.splitlines()[0][:120] if mission else session.display_title()
        synthesized: dict[str, dict[str, Any]] = {}
        for flag in flags:
            cid = str(getattr(flag, "challenge_id", "") or "") or "mission-1"
            synthesized.setdefault(cid, {
                "id": cid,
                "title": headline or cid,
                "direction": direction_key(mission),
                "description": mission[:600],
            })
        return list(synthesized.values())

    def _session_flags(session: Session) -> list[Any]:
        """已登记的 Flag（flags.json）；文件缺失或损坏就是空表。"""
        from spiritscout.core.models import FlagCandidate

        path = session.workspace / "flags.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        candidates = []
        for item in raw if isinstance(raw, list) else []:
            try:
                candidates.append(FlagCandidate.model_validate(item))
            except ValueError:       # 单条坏档不拖垮整份 WP
                continue
        return candidates

    @app.get("/api/sessions/{session_id}/writeup")
    async def session_writeup(session_id: str) -> dict[str, Any]:
        """最新一份 WP；没生成过时 markdown 为 null，由前端给生成入口。"""
        return _wp_payload(require(session_id))

    @app.get("/api/sessions/{session_id}/writeup/options")
    async def session_writeup_options(session_id: str) -> dict[str, Any]:
        """生成前要确认的东西：上次填过的信息 + 每道题自动判定的方向。

        方向是给人看的草稿——用户改过的会覆盖自动判定；不改就按这里的来。
        """
        from spiritscout.ctf.writeup import WP_DIRECTIONS, direction_key

        session = require(session_id)
        if session.mode != "ctf":
            raise HTTPException(409, "解题思路（WP）只在 CTF 解题模式下提供")
        flags = _session_flags(session)
        challenges = _session_challenges(session, flags=flags)
        solved = {str(getattr(f, "challenge_id", "") or "") for f in flags
                  if getattr(f, "accepted", None) is not False}
        profile = wp_profile.load(cfg.workspace.root)
        return {
            "profile": profile,
            "first_time": wp_profile.is_empty(profile),
            "directions": list(WP_DIRECTIONS),
            "challenges": [
                {
                    "id": str(c.get("id") or ""),
                    "title": str(c.get("title") or c.get("id") or "未命名题目"),
                    "raw": str(c.get("direction") or c.get("category") or ""),
                    "chapter": direction_key(c.get("direction") or c.get("category")),
                    "solved": str(c.get("id") or "") in solved,
                }
                for c in challenges
            ],
        }

    @app.post("/api/sessions/{session_id}/writeup")
    async def session_writeup_generate(
        session_id: str, payload: WriteUpRequest | None = None,
    ) -> dict[str, Any]:
        """按赛方模板撰写解题思路：材料取自本会话的题目、笔记与 Flag。

        请求体可省：带了团队信息就记下来并即刻生效，没带就沿用上次那套；
        模型不可用时回落到结构化提纲——"点了生成就有东西"，不会空手而归。
        """
        session = require(session_id)
        if session.mode != "ctf":
            raise HTTPException(409, "解题思路（WP）只在 CTF 解题模式下提供")
        flags = _session_flags(session)
        challenges = _session_challenges(session, flags=flags)
        if not challenges:
            raise HTTPException(
                409, "这个会话没有任何解题记录（题目与 Flag 都是空的），先跑一道题再生成 WP")

        from spiritscout.ctf.writeup import (
            build_wp_digest,
            run_facts,
            wp_body,
            wp_fallback,
        )

        if payload is not None and payload.team is not None:
            # 用户在信息页确认过这套信息：记住它，下一份 WP 直接带出来
            profile = wp_profile.save(cfg.workspace.root, payload.team.model_dump())
        else:
            profile = wp_profile.load(cfg.workspace.root)
        team = dict(profile)
        team["name"] = team.get("name") or session.display_title()
        directions = dict(payload.directions) if payload else {}

        audit = AuditLogger(session.audit_path)
        digest = build_wp_digest(
            challenges=challenges,
            flags=flags,
            run_summary=session.summary or {},
            blackboard=Blackboard(session.bb_path),
            team=team,
            facts=run_facts(audit),
            direction_overrides=directions,
        )
        body = None
        models = _writable_models(cfg, manager)
        if models:
            try:
                gateway = _conversation_gateway(cfg, models, audit)
                body = await wp_body(gateway, digest=digest, audit=audit)
            except Exception as exc:  # noqa: BLE001 —— 建模失败就退回提纲
                audit.log("writeup.generate", "web",
                          {"result": "gateway_failed", "error": str(exc)[:200]})
        if not body:
            body = wp_fallback(
                digest, reason="模型暂不可用，以下按模板整理出的提纲，请补齐细节。")
        dest = _wp_dir(session) / f"wp-{time.strftime('%Y%m%d-%H%M%S')}.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(body, encoding="utf-8")
        audit.log("writeup.saved", "web",
                  {"path": str(dest), "chars": len(body)})
        return {"path": str(dest), "markdown": body,
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")}

    @app.get("/api/sessions/{session_id}/writeup/download")
    async def session_writeup_download(session_id: str) -> FileResponse:
        """WP 文件下载（Markdown）。"""
        path = _latest_wp(require(session_id))
        if path is None:
            raise HTTPException(404, "还没生成过 WP")
        return FileResponse(path, media_type="text/markdown", filename=path.name)

    @app.get("/api/sessions/{session_id}/audit/download")
    async def session_audit_download(session_id: str) -> StreamingResponse:
        """审计日志 JSONL 导出（Web 功能补全）。"""
        audit = require(session_id).audit_path
        if not audit.exists():
            raise HTTPException(404, "审计日志不存在（会话未产生事件）")
        from spiritscout.core.audit import sanitize_record

        def records() -> Iterator[str]:
            # 同步生成器由响应在线程池消费，不一次性物化整个历史文件。
            with audit.open(encoding="utf-8") as source:
                for line in source:
                    try:
                        record = sanitize_record(json.loads(line))
                    except (ValueError, TypeError, AttributeError):
                        record = {"type": "audit.invalid", "detail": {"error": "日志行无效"}}
                    yield json.dumps(record, ensure_ascii=False) + "\n"

        return StreamingResponse(records(), media_type="application/x-ndjson",
                                 headers={"Content-Disposition":
                                          f'attachment; filename="{session_id}-audit.jsonl"'})

