"""本机目录选择：给控制台的「选择文件夹」按钮配一个原生对话框。

对话框由子进程弹（Tk 必须在主线程、且不能卡住 Web 的事件循环）。子进程只做一件事：
把选中的绝对路径写到 stdout；用户取消就什么都不写。父进程据此区分
「取消」（返回 ``None``）和「失败」（抛 :class:`PickerError`）。

限制：

- 只在有桌面会话的机器上有意义（本机控制台默认如此）；无图形环境时
  :func:`available` 直接返回 ``False``，前端退回手填路径。
- 对话框可能被浏览器盖住，子进程会把窗口置顶并短暂抢一次焦点——这是本机
  单人控制台的合理取舍；不想被打断就别点那个按钮。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

DEFAULT_TIMEOUT = 180.0
_CHILD = "spiritscout.tools.dir_picker_child"
NO_GUI = "no-gui:"
NO_GUI_EXIT = 3


class PickerError(RuntimeError):
    """对话框起不来或异常退出。"""


def available() -> bool:
    """本机能不能弹原生对话框（tkinter 可导入即可，不真的开窗口）。"""
    try:
        import tkinter  # noqa: F401
    except Exception:
        return False
    return True


def _normalize(initial: str | None) -> str:
    """``initialdir`` 只接受真实存在的目录，否则对话框会跑到默认位置。"""
    text = str(initial or "").strip().strip('"')
    if not text:
        return ""
    try:
        path = Path(text).expanduser()
    except (OSError, ValueError):
        return ""
    return str(path) if path.is_dir() else ""


def pick_directory(initial: str | None = None, *,
                   timeout: float = DEFAULT_TIMEOUT) -> str | None:
    """弹一个「选择文件夹」对话框。

    返回选中的绝对路径；用户取消返回 ``None``；起不来则抛 :class:`PickerError`。
    """
    if not available():
        raise PickerError("这台机器没有可用的图形界面（缺少 tkinter），请手填目录")

    command = [sys.executable, "-X", "utf8", "-m", _CHILD, _normalize(initial)]
    try:
        done = subprocess.run(command, capture_output=True, timeout=timeout,
                              check=False)
    except subprocess.TimeoutExpired as exc:
        raise PickerError(f"对话框 {int(timeout)} 秒没有响应，已关闭") from exc
    except OSError as exc:
        raise PickerError(f"对话框启动失败：{exc}") from exc

    err = (done.stderr or b"").decode("utf-8", "replace").strip()
    if done.returncode == NO_GUI_EXIT or err.startswith(NO_GUI):
        detail = err.split(NO_GUI, 1)[-1].strip() or "缺少 tkinter"
        raise PickerError(f"这台机器弹不出文件夹对话框：{detail}")
    text = (done.stdout or b"").decode("utf-8", "replace").strip()
    if not text:
        # 关窗口、按取消、Esc 都走这里：用户没选，不是故障
        return None
    path = Path(text)
    if not path.is_absolute() or not path.is_dir():
        raise PickerError(f"选中的路径不可用：{text}")
    return str(path)
