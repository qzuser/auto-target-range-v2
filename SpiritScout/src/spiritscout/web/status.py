"""会话的两个派生状态：提炼中 / 询问中。

它们不是持久化 ``status``：提炼是会话收尾之后的附加动作（常常已经 completed），
询问是运行中挂起等用户作答。这里按进程内登记表与待答队列现算，会话列表、详情
和前端徽标共用同一口径，免得各页各写一套判断。
"""
from __future__ import annotations

from typing import Any

from spiritscout.core import distill_state

DISTILLING = "distilling"
ASKING = "asking"
TERMINAL = frozenset({"completed", "failed", "stopped", "interrupted"})


def derived(session: Any) -> dict[str, Any]:
    """给 brief 的两个附加字段（前端据此换徽标，不猜）。"""
    questions = session.questions.view() if getattr(session, "questions", None) else []
    return {"distilling": distill_state.active(getattr(session, "session_id", "")),
            "pending_questions": len(questions)}


def display_status(session: Any) -> str:
    """徽标口径：提炼中 > 询问中 > 持久化状态。

    提炼中放最前：自动提炼就发生在会话收尾之后，这时按 status 显示「已完成」会
    让用户以为已经彻底收工。询问中只对未结束的会话生效——终态会话残留的待答
    记录不该让它一直显示「询问中」。
    """
    status = str(getattr(session, "status", "") or "")
    fields = derived(session)
    if fields["distilling"]:
        return DISTILLING
    if fields["pending_questions"] and status not in TERMINAL:
        return ASKING
    return status
