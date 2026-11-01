"""提醒接口：把「有什么值得叫醒用户」推给前端。

一条只读 GET，数据源在 :mod:`spiritscout.web.notify`：解出的题来自会话目录的
``flags.json``，待答问题来自会话内的提问队列。前端按 ``id`` 去重，因此这里
既不需要「已读」标记，也不需要写盘——多开几个标签页，两个屏幕各取所需。

鉴权由 ``routes/auth`` 的中间件统一收口（登录启用时 ``/api/*`` 一律要 Cookie
或 Basic），这里不再重复判一次。
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from spiritscout.web.notify import snapshot


def mount_notify(app: FastAPI, *, manager: Any) -> None:
    """挂提醒接口：前端轮询它决定要不要弹系统通知。"""

    @app.get("/api/notifications")
    def notifications() -> dict[str, Any]:
        """当前待提醒条目（新的在前）、分类计数与可比 revision。

        ``manager.list()`` 先复制会话表再遍历：本端点在线程池执行，与事件
        循环里的会话创建/删除并发也不会撞「dictionary changed size」。
        """
        return snapshot(manager.list())
