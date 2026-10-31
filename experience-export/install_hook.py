#!/usr/bin/env python3
"""把 experience-export/git-hooks/pre-commit 装进本仓库的 .git/hooks。

钩子属于本机状态，不进版本库（.git/hooks 也不会被跟踪），所以每个 clone 都要装
一次。装上之后每次提交都会把最新的经验快照一起带上。

用法：
    python experience-export/install_hook.py            # 安装/更新
    python experience-export/install_hook.py --check     # 只检查是否已装且一致
    python experience-export/install_hook.py --uninstall # 卸掉（只删我们装的那个）
"""

from __future__ import annotations

import argparse
import contextlib
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / "experience-export" / "git-hooks" / "pre-commit"

MARKER = "# 提交前把运行期跑出来的经验刷新进本次提交。"


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} 失败：{result.stderr.strip()}")
    return result.stdout.strip()


def hook_path() -> Path:
    # --git-path 能正确处理 worktree / submodule 的 hooks 目录
    return (REPO_ROOT / git("rev-parse", "--git-path", "hooks/pre-commit")).resolve()


def read_source() -> bytes:
    if not SOURCE.exists():
        raise SystemExit(f"钩子源文件不存在：{SOURCE}")
    return SOURCE.read_bytes()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="安装提交前刷新经验快照的 git 钩子")
    parser.add_argument("--check", action="store_true", help="只检查，不改动")
    parser.add_argument("--uninstall", action="store_true", help="卸载钩子")
    args = parser.parse_args(argv)

    target = hook_path()
    want = read_source()

    if args.uninstall:
        if not target.exists():
            print(f"[跳过] 没有钩子：{target}")
            return 0
        if MARKER not in target.read_text(encoding="utf-8", errors="replace"):
            print(f"[跳过] {target} 不是本工具装的，不动它")
            return 0
        target.unlink()
        print(f"[已卸载] {target}")
        return 0

    if args.check:
        if not target.exists():
            print(f"[未安装] {target}")
            return 1
        if target.read_bytes() != want:
            print(f"[已过期] {target} 与 experience-export/git-hooks/pre-commit 不一致")
            return 1
        print(f"[已安装] {target}")
        return 0

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        current = target.read_text(encoding="utf-8", errors="replace")
        if MARKER not in current and current.strip():
            backup = target.with_suffix(".pre-experience-export")
            backup.write_text(current, encoding="utf-8", newline="")
            print(f"[备份] 原钩子已存到 {backup}")
    target.write_bytes(want)
    with contextlib.suppress(OSError):
        target.chmod(0o755)
    print(f"[已安装] {target}")
    print("          之后每次 git commit 都会把最新经验快照一起提交")
    print("          临时跳过：git commit --no-verify")
    return 0


if __name__ == "__main__":
    sys.exit(main())
