"""原生「选择文件夹」对话框的子进程端：选中就把路径写到 stdout，取消就不写。

父进程见 :mod:`spiritscout.tools.dir_picker`。这里刻意保持极简——Tk 的窗口
必须在拥有它的进程里创建，所以只能另起一个进程，别把它塞回 Web 进程里。

退出码约定（父进程据此区分「取消」和「起不来」）：

- ``0``：正常结束。stdout 有内容就是选中的路径，空就是用户取消/关掉了窗口；
- ``3``：没有可用的图形界面（缺 tkinter），stderr 以 ``no-gui:`` 开头。
"""

from __future__ import annotations

import contextlib
import sys

NO_GUI = "no-gui:"
NO_GUI_EXIT = 3


def main(argv: list[str]) -> int:
    initial = argv[1] if len(argv) > 1 else ""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:                       # 无图形界面：交给父进程报错
        sys.stderr.write(f"{NO_GUI}{exc}\n")
        sys.stderr.flush()
        return NO_GUI_EXIT

    chosen = ""
    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        with contextlib.suppress(tk.TclError):     # 窗口管理器不支持置顶，不影响选择
            root.attributes("-topmost", True)
        chosen = filedialog.askdirectory(
            parent=root,
            title="选择工具目录",
            initialdir=initial or None,
            mustexist=True,
        )
    except Exception as exc:                       # 关窗口、取消、WM 怪脾气都算「没选」
        sys.stderr.write(f"dialog-aborted: {exc}\n")
        sys.stderr.flush()
        return 0
    finally:
        if root is not None:
            with contextlib.suppress(Exception):
                root.destroy()

    if chosen:
        sys.stdout.buffer.write(str(chosen).encode("utf-8"))
        sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
