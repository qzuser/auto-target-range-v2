"""自定义技能库的仓库侧真源：``configs/skills.yaml``。

技能原本只存在资源库的 ``settings`` 表里（``kind='skill'``），而资源库在
``.spiritscout/resources/catalog.db``——工作区一重建，攒下的技能连同上一次
导入的 markdown 一起没了，仓库里也找不到第二份（``security_skills.json``
只是内置的 206 条，不含用户自己的）。这里把自定义技能搬进版本库：

- 启动时 ``sync_skills`` 把 ``configs/skills.yaml`` 同步进资源库（幂等，
  同内容不重复写、每次写都抬版本号）；
- ``import`` 把一堆带 frontmatter 的 ``SKILL.md`` 收进 yaml，``export`` 把
  资源库里现有条目倒回 yaml，两条路都落到同一个文件，跟着提交与打包走。

字段与「技能」页一致：``skill_id`` / ``domain`` / ``description`` / ``body`` /
``severity`` / ``cwe`` / ``tools`` / ``source`` / ``path`` / ``enabled``。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

#: 自定义技能清单的默认位置（相对仓库/应用根；与 models.yaml 同目录）
DEFAULT_PATH = "configs/skills.yaml"

_HEADER = """\
# 自定义技能库（版本库里的真源；启动时同步进资源库，不随工作区重建丢失）。
# 每条字段与「技能」页一致：skill_id / domain / description / body /
# severity / cwe / tools / source / path / enabled。
# 批量导入：python -m spiritscout.resources.skill_sync import <目录>
# 反向导出：python -m spiritscout.resources.skill_sync export
# 内置的 206 条安全技能在 src/spiritscout/knowledge/data/security_skills.json，
# 不写在这里——这里只放你自己加的。
"""

_FIELDS = ("skill_id", "domain", "description", "body", "severity", "cwe",
           "tools", "source", "path", "enabled")


def _clean(item: dict[str, Any]) -> dict[str, Any]:
    """只留认识的字段，并把列表型字段压成字符串（与内置条目的形态一致）。"""
    out: dict[str, Any] = {}
    for key in _FIELDS:
        if key not in item:
            continue
        value = item[key]
        if key == "enabled":
            out[key] = bool(value)
        elif key in ("cwe", "tools") and isinstance(value, list):
            out[key] = "[" + ", ".join(str(v) for v in value) + "]"
        else:
            out[key] = "" if value is None else str(value)
    return out


def read_skills(path: str | Path) -> list[dict[str, Any]]:
    """读清单。兼容顶层是列表或 ``{skills: [...]}``；文件不存在当作空。"""
    p = Path(path)
    if not p.is_file():
        return []
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        print(f"[skills] 读不动 {p}: {exc}", file=sys.stderr)
        return []
    items = raw.get("skills") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return []
    return [_clean(item) for item in items if isinstance(item, dict)]


def write_skills(path: str | Path, items: list[dict[str, Any]]) -> Path:
    """写清单（带表头注释；空列表也写，让文件始终存在且可 diff）。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump({"skills": [_clean(i) for i in items]},
                          allow_unicode=True, sort_keys=False, width=100)
    p.write_text(_HEADER + body, encoding="utf-8")
    return p


def sync_skills(store: Any, path: str | Path) -> dict[str, int]:
    """把清单同步进资源库；返回 ``added/updated/unchanged/total``。

    只增改、不删：清单里没有的条目留在库里，避免一次手滑就从页面消失。
    内容与库里一致时跳过，所以每次启动都跑也没有写入放大。
    """
    items = read_skills(path)
    stats = {"added": 0, "updated": 0, "unchanged": 0, "total": len(items)}
    if not items:
        return stats
    existing = {row["id"]: row for row in store.settings("skill")}
    for item in items:
        key = str(item.get("skill_id") or "").strip()
        if not key:
            continue
        current = existing.get(key)
        if current is None:
            store.save("skill", key, item, 0)
            stats["added"] += 1
        elif current.get("data") != item:
            store.save("skill", key, item, int(current.get("version", 0)))
            stats["updated"] += 1
        else:
            stats["unchanged"] += 1
    return stats


def export_skills(store: Any) -> list[dict[str, Any]]:
    """把资源库里现有的自定义技能倒出来（不含内置）。"""
    return [_clean({**row["data"], "skill_id": row["id"]})
            for row in store.settings("skill")]


def parse_markdown(path: Path) -> dict[str, Any] | None:
    """解析一份 ``SKILL.md``：``---`` frontmatter + 正文。"""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    meta: dict[str, Any] = {}
    body = text
    if text.lstrip().startswith("---"):
        lines = text.lstrip().splitlines()
        end = None
        for i, line in enumerate(lines[1:], start=1):
            if line.strip() in ("---", "..."):
                end = i
                break
        if end is not None:
            try:
                loaded = yaml.safe_load("\n".join(lines[1:end])) or {}
                meta = loaded if isinstance(loaded, dict) else {}
            except yaml.YAMLError:
                meta = {}
            body = "\n".join(lines[end + 1:])
    skill_id = str(meta.get("skill_id") or meta.get("name") or "").strip()
    if not skill_id:
        # 形如 skills/<domain>/<skill>/SKILL.md：用倒数第二段当 id
        parent = path.parent.name
        skill_id = "" if parent.lower() in ("skills", "") else parent
    if not skill_id:
        skill_id = path.stem
    item = {**meta, "skill_id": skill_id, "body": body.strip()}
    item.setdefault("source", str(path.parent.name))
    item.setdefault("path", str(path.as_posix()))
    return _clean(item)


def import_markdown(source: str | Path, target: str | Path = DEFAULT_PATH) -> dict[str, int]:
    """把目录（或单个文件）里的 markdown 技能收进清单；同 id 以新文件为准。"""
    src = Path(source)
    files = sorted(src.rglob("*.md")) if src.is_dir() else ([src] if src.is_file() else [])
    items = [i for i in (parse_markdown(f) for f in files) if i]
    merged: dict[str, dict[str, Any]] = {i["skill_id"]: i for i in read_skills(target)}
    added = 0
    for item in items:
        if item["skill_id"] not in merged:
            added += 1
        merged[item["skill_id"]] = item
    write_skills(target, list(merged.values()))
    return {"scanned": len(files), "parsed": len(items), "added": added,
            "total": len(merged)}


def _store(cfg_path: str | None) -> Any:
    from spiritscout.config import load_system_config
    from spiritscout.resources.store import ResourceStore, resource_root

    cfg = load_system_config(cfg_path) if cfg_path else None
    if cfg is None:
        from spiritscout.config.settings import SystemConfig

        cfg = SystemConfig()
    return ResourceStore(resource_root(cfg), cfg.resources.freshness_hours)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="skill_sync", description="自定义技能库与仓库清单互转")
    parser.add_argument("action", choices=("import", "export", "sync"))
    parser.add_argument("source", nargs="?", default="", help="import：目录或 SKILL.md")
    parser.add_argument("--target", default=DEFAULT_PATH, help="清单路径")
    parser.add_argument("--config", default="", help="system.yaml 路径（读资源库用）")
    args = parser.parse_args(argv)

    if args.action == "import":
        if not args.source:
            print("需要给一个目录或 SKILL.md 路径", file=sys.stderr)
            return 2
        print(import_markdown(args.source, args.target))
        return 0
    if args.action == "export":
        store = _store(args.config or None)
        items = export_skills(store)
        write_skills(args.target, items)
        print(f"导出 {len(items)} 条 -> {args.target}")
        return 0
    store = _store(args.config or None)
    print(sync_skills(store, args.target))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
