"""把经验快照压成一份人读的摘要，随发行包一起发出去。

为什么要塞进包里：经验库是这个项目最值钱的部分，装完就想知道「它到底攒了多少、
都是些什么」。所以每次打包都从 `experience-export/experience-insights.json`
生成一份 `EXPERIENCE.md`（外加机读的 `experience.json`），一起放进 wheel /
sdist / zip——不依赖用户再去仓库里翻。

两种来源都认：仓库里那份老的 `spiritscout-experience-insights`（`insights` 字段）
与同步用的 `spiritscout.experience/v1`（`items` 字段），归一化交给
`knowledge/sync.py` 的 `read_export`。
"""

from __future__ import annotations

import argparse
import shutil
import time
from pathlib import Path
from typing import Any, Sequence

from spiritscout.knowledge.sync import read_export, write_export

# 生成的文件名：包根一份、包内数据目录一份、仓库根一份（给 zip 用）
DIGEST_NAME = "EXPERIENCE.md"
DATA_JSON = "experience.json"
DATA_MD = "experience.md"
PACKAGE_DATA_DIR = Path("src/spiritscout/knowledge/data")


def _stamp(value: Any) -> str:
    """把 epoch / ISO 时间都写成 `2026-11-10 18:35` 这种能看的本地时间。"""
    if value in (None, ""):
        return ""
    stamp: float
    if isinstance(value, (int, float)):
        stamp = float(value)
    else:
        text = str(value).replace("Z", "+00:00")
        try:
            from datetime import datetime

            parsed = datetime.fromisoformat(text)
        except ValueError:
            return str(value)[:16]
        stamp = parsed.timestamp()
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(stamp))


def _one_line(text: Any, limit: int = 160) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def collect_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """取条目列表：兼容 `items`（v1）与老清单归一化后的结果。"""
    items = payload.get("items")
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def tag_ranking(items: Sequence[dict[str, Any]], limit: int = 12) -> list[tuple[str, int]]:
    """按标签统计条数，大的在前；同数按字母序，保证输出稳定可 diff。"""
    counts: dict[str, int] = {}
    for item in items:
        for tag in item.get("tags") or []:
            name = str(tag).strip()
            if name:
                counts[name] = counts.get(name, 0) + 1
    ranked = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    return ranked[:limit]


def digest_markdown(payload: dict[str, Any], *, limit: int = 60, inbox_files: int = 0) -> str:
    """生成 `EXPERIENCE.md` 正文。"""
    items = collect_items(payload)
    total = int(payload.get("count") or len(items))
    lines = [
        "# 做题经验速览",
        "",
        "这个包除了代码，还带了灵枢攒下来的做题经验——共 "
        f"**{total} 条**，随包生成的这份摘要是给人看的；",
        f"机读版在 `knowledge/data/{DATA_JSON}`（条目字段与仓库清单一致）。",
        "",
        f"- 生成时间：{_stamp(payload.get('exported_at')) or time.strftime('%Y-%m-%d %H:%M')}",
        f"- 摘要收录：最近 {min(limit, len(items))} 条（共 {len(items)} 条）",
    ]
    if inbox_files:
        lines.append(f"- 另有人人可提的投稿 {inbox_files} 份，在仓库 `experience-export/inbox/`")
    lines += ["", "## 标签分布", "", "| 标签 | 条数 |", "| --- | --- |"]
    ranked = tag_ranking(items)
    if ranked:
        lines += [f"| `{name}` | {count} |" for name, count in ranked]
    else:
        lines.append("| — | 还没有标签 |")

    lines += ["", f"## 最近 {min(limit, len(items))} 条", ""]
    for index, item in enumerate(items[:limit], start=1):
        lines.append(f"### {index}. {_one_line(item.get('insight'), 120)}")
        context = _one_line(item.get("context"), 120)
        if context:
            lines.append(f"- 场景：{context}")
        tags = " · ".join(str(tag) for tag in item.get("tags") or [] if str(tag).strip())
        if tags:
            lines.append(f"- 标签：{tags}")
        meta = [part for part in (
            f"来源模型 `{item.get('source_model')}`" if item.get("source_model") else "",
            f"记录于 {_stamp(item.get('captured_at') or item.get('ts'))}"
            if item.get("captured_at") or item.get("ts") else "",
        ) if part]
        if meta:
            lines.append("- " + " · ".join(meta))
        lines.append("")
    if len(items) > limit:
        lines += [f"（其余 {len(items) - limit} 条见 `knowledge/data/{DATA_JSON}`）", ""]
    lines += [
        "---",
        "",
        "经验来自真实做题回合，已在导出时脱敏（目标地址、IP、flag、密钥都换成了标记）。",
        "想贡献一条：控制台「经验」页点「提交」，或直接往仓库 `experience-export/inbox/` 放一份 JSON。",
        "",
    ]
    return "\n".join(lines)


def write_bundle(repo: Path, package_dir: Path, *, limit: int = 60,
                 source: Path | None = None) -> dict[str, Path]:
    """在仓库与包目录里各写一份摘要，返回写出的文件路径。

    - `<repo>/EXPERIENCE.md`：给 zip / 直接看
    - `<package>/EXPERIENCE.md`：进 sdist
    - `<package>/src/spiritscout/knowledge/data/experience.{json,md}`：进 wheel
    """
    snapshot = source or (repo / "experience-export" / "experience-insights.json")
    payload = read_export(snapshot) if snapshot.is_file() else {
        "format": "spiritscout.experience/v1", "count": 0, "items": []}
    inbox = repo / "experience-export" / "inbox"
    inbox_files = len(list(inbox.glob("*.json"))) if inbox.is_dir() else 0
    markdown = digest_markdown(payload, limit=limit, inbox_files=inbox_files)

    written: dict[str, Path] = {}
    top = repo / DIGEST_NAME
    top.write_text(markdown, encoding="utf-8")
    written["repo"] = top

    pkg_md = package_dir / DIGEST_NAME
    pkg_md.write_text(markdown, encoding="utf-8")
    written["package"] = pkg_md

    data_dir = package_dir / PACKAGE_DATA_DIR
    data_dir.mkdir(parents=True, exist_ok=True)
    if snapshot.is_file():
        json_target = data_dir / DATA_JSON
        write_export(json_target, payload)
        written["json"] = json_target
        shutil.copyfile(pkg_md, data_dir / DATA_MD)
        written["md"] = data_dir / DATA_MD
    return written


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m spiritscout.knowledge.digest",
        description="生成随包发布的经验摘要（EXPERIENCE.md 与 experience.json）")
    parser.add_argument("--repo", default=".", help="仓库根（含 experience-export/）")
    parser.add_argument("--package", default="SpiritScout", help="包目录（含 pyproject.toml）")
    parser.add_argument("--limit", type=int, default=60, help="摘要里列出多少条")
    parser.add_argument("--source", default="", help="指定快照文件（默认用仓库里那份）")
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    package_dir = Path(args.package).resolve()
    if not (package_dir / "pyproject.toml").is_file():
        print(f"{package_dir} 看起来不是包目录（没有 pyproject.toml）")
        return 2
    written = write_bundle(repo, package_dir, limit=max(1, args.limit),
                           source=Path(args.source).resolve() if args.source else None)
    for name, path in written.items():
        print(f"[经验摘要] {name}: {path} ({path.stat().st_size} 字节)")
    return 0


if __name__ == "__main__":  # pragma: no cover - 手工运行入口
    raise SystemExit(main())
