#!/usr/bin/env python
"""检查灵枢的运行依赖是否装齐。

给启动脚本用的轻量探针：按 `pyproject.toml` 里声明的**分发名**查
`importlib.metadata`，不导入任何模块——导入 litellm 一个就要好几秒，
启动自检不该付这个代价。

除依赖外还报三件事，因为它们同样让 `python -m spiritscout` 起不来、
却不会以缺包的形式表现出来：本体有没有装进当前环境（`self_version`），
以及这个环境里还有没有 `pip` 可用（`pip`，缺了就没法补装）。另外
`source_version` 单独给出仓库源码里声明的版本——editable 安装的 `.dist-info`
是当初 `pip install -e` 打的快照，源码一路往前它不动，两者经常不一致。

用法::

    python scripts/probe_deps.py            # 运行依赖，缺的逐行打印，退出码 1
    python scripts/probe_deps.py --toolkit  # 附带检查可选工具包
    python scripts/probe_deps.py --json     # 给脚本消费的结构化输出
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

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


def source_version() -> str | None:
    """不导入包，直接从 `src/spiritscout/__init__.py` 读 `__version__`。

    只在仓库工作树里跑得出来；从别处调用（探针被拷走）就返回 None，
    调用方按「没有可比对象」处理，不当成错误。
    """
    init_py = Path(__file__).resolve().parents[1] / "src" / "spiritscout" / "__init__.py"
    try:
        text = init_py.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', text, re.M)
    return match.group(1) if match else None


def environment() -> dict[str, object]:
    """本体与 pip 的状态。

    一个刚 `py -3.11 -m venv` 出来、还什么都没装的环境，和被人手动删过
    `site-packages` 的半残环境，光看依赖列表都像是「缺依赖」，但补装的
    命令不一样：前者要装本体，后者可能连 pip 都没了，只能重建 venv。
    """
    try:
        self_version = version("spiritscout")
    except Exception:
        self_version = None
    try:
        pip_ok = importlib.util.find_spec("pip") is not None
    except Exception:
        pip_ok = False
    return {"self_version": self_version, "pip": pip_ok,
            "source_version": source_version()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="检查灵枢的运行依赖")
    parser.add_argument("--toolkit", action="store_true", help="附带检查可选工具包")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)

    runtime_missing, runtime_found = probe(RUNTIME)
    toolkit_missing: list[str] = []
    if args.toolkit:
        toolkit_missing, _ = probe(TOOLKIT)
    env = environment()
    # 本体没装或 pip 没了，光补依赖也起不来服务，一并算「不可用」
    usable = not runtime_missing and bool(env["self_version"]) and bool(env["pip"])

    if args.json:
        print(json.dumps({
            "python": "%d.%d.%d" % sys.version_info[:3],
            "runtime_missing": runtime_missing,
            "toolkit_missing": toolkit_missing,
            "self_version": env["self_version"],
            "source_version": env["source_version"],
            "pip": env["pip"],
        }, ensure_ascii=False))
        return 0 if usable else 1

    if runtime_missing:
        print(f"缺运行依赖 {len(runtime_missing)} 个：{' '.join(runtime_missing)}")
    if not env["self_version"]:
        print("灵枢本体未装进当前环境（在仓库根执行 pip install -e \"SpiritScout\"）")
    if not env["pip"]:
        print("当前环境没有 pip，无法补装（重建 venv 或 python -m ensurepip --upgrade）")
    if not usable:
        return 1
    print(f"运行依赖齐全（{len(runtime_found)} 个，Python "
          f"{sys.version_info.major}.{sys.version_info.minor}，"
          f"源码 {env['source_version'] or '未知'}／已装 {env['self_version']}）")
    if (env["source_version"] and env["self_version"]
            and env["source_version"] != env["self_version"]):
        # editable 装的 .pth 指向 src/，跑的是源码；元数据落后只是不好读
        print("提示：安装元数据落后于源码（起服务用 src/ 下的当前代码，不影响启动）")
    if toolkit_missing:
        print(f"可选工具包缺 {len(toolkit_missing)} 个：{' '.join(toolkit_missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
