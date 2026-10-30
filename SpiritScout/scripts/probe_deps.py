#!/usr/bin/env python
"""检查灵枢的运行依赖是否装齐。

给启动脚本用的轻量探针：按 `pyproject.toml` 里声明的**分发名**查
`importlib.metadata`，不导入任何模块——导入 litellm 一个就要好几秒，
启动自检不该付这个代价。

用法::

    python scripts/probe_deps.py            # 运行依赖，缺的逐行打印，退出码 1
    python scripts/probe_deps.py --toolkit  # 附带检查可选工具包
    python scripts/probe_deps.py --json     # 给脚本消费的结构化输出
"""

from __future__ import annotations

import argparse
import json
import sys
from importlib.metadata import PackageNotFoundError, version

# 与 pyproject.toml 的 [project].dependencies 对齐（分发名，不是 import 名）
RUNTIME = [
    "pydantic", "pyyaml", "jinja2", "httpx", "litellm", "langgraph",
    "langchain-core", "fastapi", "uvicorn", "cryptography", "mcp", "tzdata",
]

# [project.optional-dependencies].toolkit —— 缺了不影响启动，只影响 CTF 工具链
TOOLKIT = [
    "pwntools", "pycryptodome", "pillow", "sympy", "gmpy2", "z3-solver",
    "scapy", "exifread", "stegano", "olefile", "binwalk", "sqlmap",
]


def probe(names: list[str]) -> tuple[list[str], dict[str, str]]:
    """返回（缺失的分发名，已装的名字→版本）。"""
    missing: list[str] = []
    found: dict[str, str] = {}
    for name in names:
        try:
            found[name] = version(name)
        except PackageNotFoundError:
            missing.append(name)
        except Exception:                      # 元数据损坏也当作不可用
            missing.append(name)
    return missing, found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="检查灵枢的运行依赖")
    parser.add_argument("--toolkit", action="store_true", help="附带检查可选工具包")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)

    runtime_missing, runtime_found = probe(RUNTIME)
    toolkit_missing: list[str] = []
    if args.toolkit:
        toolkit_missing, _ = probe(TOOLKIT)

    if args.json:
        print(json.dumps({
            "python": "%d.%d.%d" % sys.version_info[:3],
            "runtime_missing": runtime_missing,
            "toolkit_missing": toolkit_missing,
        }, ensure_ascii=False))
        return 1 if runtime_missing else 0

    if runtime_missing:
        print(f"缺运行依赖 {len(runtime_missing)} 个：{' '.join(runtime_missing)}")
        return 1
    print(f"运行依赖齐全（{len(runtime_found)} 个，Python "
          f"{sys.version_info.major}.{sys.version_info.minor}）")
    if toolkit_missing:
        print(f"可选工具包缺 {len(toolkit_missing)} 个：{' '.join(toolkit_missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
