"""浏览器退出时的临时档案清理。

Playwright 每起一次浏览器就在 ``browser-output/tmp`` 下落一份 Chromium 档案
（``GrShaderCache``、``BrowserMetrics-spare.pma`` 这些），单份 10–20 MB，会话
结束也不会自己走。实测五个会话攒了 35 MB，全是这一层。

这里按「累计超过阈值才动手」清理：单份留着不碍事，攒到一定量再一次性删干净。
不每次退出都删有两个好处——省掉一遍几千个文件的遍历，也不必在任务刚落幕时
去碰一个可能还被占着的目录。

只动 ``tmp``：同级还有截图、console 日志、下载文件，那些是产物，不能碰。
"""

from __future__ import annotations

import contextlib
import os
import shutil
from pathlib import Path

# 累计超过这个体积才清。单份 Chromium 档案通常 10–20 MB，留几份不碍事，
# 攒够一批再一次性删干净，省掉每次退出都遍历几千个文件。
DEFAULT_THRESHOLD_MB = 64.0

_THRESHOLD_ENV = "SPIRITSCOUT_BROWSER_TMP_PRUNE_MB"


def threshold_mb(explicit: float | None = None) -> float:
    """取阈值：显式参数 > 环境变量 > 默认值。非法值退回默认，不抛错。"""
    if explicit is not None:
        return max(0.0, float(explicit))
    raw = os.environ.get(_THRESHOLD_ENV, "").strip()
    if raw:
        with contextlib.suppress(ValueError):
            return max(0.0, float(raw))
    return DEFAULT_THRESHOLD_MB


def _entry_bytes(path: Path) -> int:
    """目录或单个文件的体积；读不到的条目按 0 算，清理不该因为权限卡住。"""
    if not path.is_dir():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for name in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
            except OSError:
                continue
    return total


def prune_browser_tmp(output_dir: Path | str, *,
                      threshold: float | None = None) -> int:
    """清掉 ``browser-output/tmp`` 下的临时档案，返回实际释放的字节数。

    累计体积没有超过阈值就一个字节都不动（返回 ``0``）。阈值见
    :func:`threshold_mb`，``0`` 表示每次都清。
    """
    tmp = Path(output_dir) / "tmp"
    if not tmp.is_dir():
        return 0
    entries = list(tmp.iterdir())
    if not entries:
        return 0
    limit = threshold_mb(threshold) * 1024 * 1024
    sizes = {entry: _entry_bytes(entry) for entry in entries}
    if sum(sizes.values()) <= limit:
        return 0
    freed = 0
    for entry, size in sizes.items():
        if entry.is_dir():
            with contextlib.suppress(OSError):
                shutil.rmtree(entry)
        else:
            with contextlib.suppress(OSError):
                entry.unlink()
        # 删干净了才算数：被占用的目录会留在原地，不该报成释放。
        if not entry.exists():
            freed += size
    return freed
