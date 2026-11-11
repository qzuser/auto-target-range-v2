# -*- coding: utf-8 -*-
"""清掉测试跑出来的临时目录残留。

Windows 上 `TemporaryDirectory` 的清理经常失败（SQLite/日志句柄还没放），
`ignore_cleanup_errors=True` 会把异常吞掉，于是仓库里越堆越多：
实测一次跑完留了 1441 个 `tmpXXXXXXXX`、86 MB。这个脚本负责把它们扫掉，
只动这些明确的模式，别的目录一概不碰。

用法：
    python SpiritScout/scripts/clean_temp_dirs.py          # 真删
    python SpiritScout/scripts/clean_temp_dirs.py --dry-run # 只看不删
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

# 只认这几种模式：测试临时目录、跑挂了的同名残骸、以及构建期留下的空壳
PATTERNS = ("tmp*", "spiritscout-tests-*", ".stale-*", "pip-install-*", "pip-target-*",
            "pip-ephem-wheel-cache-*", "pip-build-tracker-*")
SKIP = {".git", ".venv", "node_modules", "skills", "workspace", "workspaces"}


def targets(root: Path) -> list[Path]:
    found: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_dir():
            continue
        if any(part in SKIP for part in path.parts):
            continue
        if path.name == "__pycache__":
            continue
        if any(path.match(pattern) for pattern in PATTERNS):
            found.append(path)
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="清掉测试留下的临时目录")
    parser.add_argument("--dry-run", action="store_true", help="只列出来，不删")
    parser.add_argument("--root", default="", help="仓库根（默认按脚本位置推断）")
    args = parser.parse_args(argv)

    root = Path(args.root) if args.root else Path(__file__).resolve().parents[1]
    found = targets(root)
    total = 0
    for path in found:
        size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
        total += size
        if args.dry_run:
            print(f"[干跑] {path}  {size / 1024:.1f} KB")
            continue
        shutil.rmtree(path, ignore_errors=True)
        print(f"已删 {path}  {size / 1024:.1f} KB")
    print(f"{'会删' if args.dry_run else '已删'} {len(found)} 个目录，共 {total / 1048576:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())