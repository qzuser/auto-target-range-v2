"""`local_tool` 内置工具：在用户设置的目录里找工具、看说明、跑一次。

三个操作，一个入口：

- ``operation=search``：按关键词在索引里找（名字或路径命中），分页返回；
- ``operation=describe``：看某个工具的路径、大小、所在目录；
- ``operation=run``：交给运行器执行——复制到暂存目录、跑完核对并恢复原目录、
  销毁副本，结果里带 ``clean``（是否与运行前完全一致）。

索引关着的时候三个操作都直接回绝并说明去哪儿打开，避免模型自己猜路径乱跑。
运行需要 ``action`` 行为声明（与 shell/python 同一套审计口径）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from spiritscout.tools import local_index, local_runner
from spiritscout.tools.spec import (
    ActionCategory,
    RiskLevel,
    ToolKind,
    ToolResult,
    ToolSpec,
)

LOCAL_TOOL_SPEC = ToolSpec(
    name="local_tool",
    kind=ToolKind.BUILTIN,
    risk=RiskLevel.READONLY,
    action_required=True,
    # 本地工具的副作用发生在暂存副本里，重放等于再跑一次别人的程序：不自动重试
    automatic_replay=False,
    timeout_seconds=600,
    description="在用户设置的目录里检索并运行本地工具（跑完恢复原目录、不留残留）",
    allowed_params={"operation", "query", "name", "args", "timeout", "action"},
    target_params=(),
)


def _root(cfg: Any, workspace: Any) -> Path:
    """配置与索引都在工作区根目录：优先用 cfg（全局），退回传进来的 workspace。"""
    if cfg is not None:
        root = getattr(getattr(cfg, "workspace", None), "root", None)
        if root:
            return Path(str(root))
    if workspace is not None:
        return Path(str(workspace))
    raise local_runner.LocalToolError("缺少工作区，无法定位本地工具配置")


async def local_tool(operation: str = "search", query: str = "", name: str = "",
                     args: list[str] | None = None, timeout: float | None = None,
                     action: str | None = None, *, cfg: Any = None,
                     workspace: Any = None, **kwargs: Any) -> ToolResult:
    """检索/说明/运行本地工具；运行在副本里做，结束时还原原目录。"""
    tool_name = "local_tool"
    try:
        root = _root(cfg, workspace)
    except local_runner.LocalToolError as exc:
        return ToolResult(tool=tool_name, ok=False, error=str(exc), returncode=-1)
    config = local_index.load(root)
    if not config["enabled"]:
        return ToolResult(
            tool=tool_name, ok=False, returncode=-1,
            error="本地工具索引未启用：请先在控制台「设置 → 本地工具」里打开，"
                  "并添加存放工具的目录。")
    if not config["dirs"]:
        return ToolResult(
            tool=tool_name, ok=False, returncode=-1,
            error="还没有设置存放本地工具的目录：请先在控制台「设置 → 本地工具」里添加。")

    index = local_index.LocalToolIndex(root)
    op = str(operation or "search").strip().lower()

    if op in {"search", "describe"}:
        tools = index.ensure(config).get("tools") or []
        if op == "describe":
            entry = local_index.LocalToolIndex.find(tools, name)
            if entry is None:
                return ToolResult(tool=tool_name, ok=False, returncode=-1,
                                  error=f"索引里没有 {name or '(缺少 name)'}；"
                                        "可先用 operation=search 查一下")
            return ToolResult(tool=tool_name, ok=True,
                              stdout=json.dumps(entry, ensure_ascii=False),
                              parsed={"tool": entry["name"], "path": entry["path"]})
        hits = local_index.LocalToolIndex.search(tools, query, limit=20)
        payload = {"query": query, "count": len(hits), "tools": hits,
                   "notice": "operation=describe 看详情，operation=run 执行（跑完自动恢复原目录）"}
        return ToolResult(tool=tool_name, ok=True,
                          stdout=json.dumps(payload, ensure_ascii=False),
                          parsed={"count": len(hits)})

    if op != "run":
        return ToolResult(tool=tool_name, ok=False, returncode=-1,
                          error=f"未知 operation: {operation}（可选 search / describe / run）")

    category = action or ActionCategory.ANALYSIS.value
    if category not in {item.value for item in ActionCategory}:
        return ToolResult(tool=tool_name, ok=False, returncode=-4,
                          error="action 行为类别未知，请如实声明："
                                + ", ".join(item.value for item in ActionCategory))
    tools = index.ensure(config).get("tools") or []
    entry = local_index.LocalToolIndex.find(tools, name)
    if entry is None:
        return ToolResult(tool=tool_name, ok=False, returncode=-1,
                          error=f"索引里没有 {name or '(缺少 name)'}；"
                                "先 operation=search 找到名字再运行")
    if not isinstance(args, list) or any(not isinstance(a, (str, int, float)) for a in args):
        return ToolResult(tool=tool_name, ok=False, returncode=-1,
                          error="args 必须是字符串数组（按命令行参数逐个给）")
    budget = float(timeout or config["timeout_seconds"])
    try:
        result = local_runner.run_local_tool(
            entry, [str(a) for a in args or []], workspace=root,
            roots=config["dirs"], timeout=budget,
            max_stage_mb=config["max_stage_mb"])
    except local_runner.LocalToolError as exc:
        return ToolResult(tool=tool_name, ok=False, returncode=-1, error=str(exc))
    except OSError as exc:
        return ToolResult(tool=tool_name, ok=False, returncode=-1,
                          error=f"{type(exc).__name__}: {exc}")

    stdout = str(result.get("stdout") or "")
    stderr = str(result.get("stderr") or "")
    clean = bool(result.get("clean"))
    heading = ("运行结束，目录已还原为运行前状态"
               if clean else "运行结束，但目录未能完全还原（见 restored / unrestored）")
    lines = [heading,
             f"工具: {result.get('tool')} · 退出码 {result.get('returncode')}"
             f"{' · 已超时终止' if result.get('timed_out') else ''}"
             f" · 耗时 {result.get('duration_ms')} ms",
             f"清理: 新增残留 {len(result.get('removed') or [])} 项已删除，"
             f"还原 {len(result.get('restored') or [])} 项，暂存副本"
             f"{'已删除' if result.get('stage_removed') else '未删除'}"]
    if result.get("diff"):
        diff = result["diff"]
        if diff.get("added") or diff.get("changed") or diff.get("missing"):
            lines.append(f"差异: {json.dumps(diff, ensure_ascii=False)}")
    if stdout:
        lines.append("--- stdout ---\n" + stdout)
    if stderr:
        lines.append("--- stderr ---\n" + stderr)
    return ToolResult(
        tool=tool_name, ok=bool(result.get("ok")) and clean,
        returncode=int(result.get("returncode") or 0),
        stdout="\n".join(lines), stderr=stderr,
        timed_out=bool(result.get("timed_out")),
        duration_ms=float(result.get("duration_ms") or 0.0),
        parsed={
            "tool": result.get("tool"), "clean": clean,
            "removed": result.get("removed") or [],
            "restored": result.get("restored") or [],
            "unrestored": result.get("unrestored") or [],
            "exit_code": result.get("returncode"),
            "stage_removed": bool(result.get("stage_removed")),
            "timed_out": bool(result.get("timed_out")),
        },
        error="" if clean else "目录未能完全还原为运行前状态",
    )
