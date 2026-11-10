"""只读打开 SQLite 的统一入口。

各处原本都写 ``sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)``。
``Path.resolve()`` 在 Windows 上是一次 ``GetFinalPathName`` 系统调用（长路径上
约 0.2–0.3 ms），而状态面、仪表盘、交付物这些接口每轮会打开同一个库好几次——
纯为了拼 URI 就反复付这笔钱。这里按路径字符串记住归一化结果，同一路径只
resolve 一次；路径在工作区里不会变，URI 也就不会失效。
"""
from __future__ import annotations

import threading
from pathlib import Path

_LOCK = threading.Lock()
_URIS: dict[str, str] = {}
_MAX_ENTRIES = 4096


def ro_uri(path: Path | str) -> str:
    """返回 ``file:...?mode=ro`` 形式的只读 URI（按路径记忆）。"""
    key = str(path)
    uri = _URIS.get(key)
    if uri is not None:
        return uri
    try:
        resolved = Path(key).resolve()
    except OSError:                    # 还没建出来的库按原样拼，连不上再报错
        resolved = Path(key)
    uri = resolved.as_uri() + "?mode=ro"
    with _LOCK:
        if len(_URIS) >= _MAX_ENTRIES:  # 长期运行的工作区不会无限长，仍留一道闸
            _URIS.clear()
        _URIS[key] = uri
    return uri
