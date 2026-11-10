"""本地工具索引：把用户指定目录里的可执行工具编成清单交给 Agent。

三条线，缺一条这个功能就会变成"全盘乱翻"：

1. **目录由用户给**：清单在控制台的「本地工具」里设置，落在工作区
   `local-tools.json`（不进仓库、不进审计原文），没设置就是关着的。
2. **扫描有上限**：层数、文件数封顶，扫不动的目录跳过而不是让整次索引失败；
   常见工具目录动辄几万个文件，索引只关心"能跑起来的东西"。
3. **能不能跑由运行器判**：这里只负责"有什么"，真正执行前还要在同一次调用里
   校验路径落在用户设置的目录内、复制到暂存目录、跑完核对并恢复。

索引结果缓存在 `<workspace>/local-tools/index.json`：目录 mtime 变了或者过了
保鲜期就重扫，否则直接读清单——Agent 每次找工具都重扫一遍目录是不可接受的。
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

CONFIG_FILENAME = "local-tools.json"
INDEX_DIRNAME = "local-tools"
INDEX_FILENAME = "index.json"

# 认这些后缀是"能执行的工具"；不在表里的文件（文档、素材、源码）不进索引，
# 免得清单被杂物淹没。POSIX 上额外认可执行位。
RUNNABLE_EXTS: tuple[str, ...] = (
    ".exe", ".cmd", ".bat", ".com", ".ps1", ".py", ".sh",
    ".pl", ".rb", ".jar", ".vbs", ".js",
)

# 扫描时直接跳过的目录名：不是工具本体，翻进去只是浪费时间和上限
SKIP_DIRS = frozenset({
    "node_modules", "__pycache__", ".git", ".svn", ".hg",
    "site-packages", ".venv", "venv", ".cache", ".idea",
})

DEFAULTS: dict[str, Any] = {
    "enabled": False,          # 关着的时候 Agent 看不到也跑不了任何本地工具
    "dirs": [],                # 用户设置的目录（绝对路径）
    "timeout_seconds": 180,    # 单次运行上限
    "max_depth": 3,            # 从设置目录往下几层
    "max_files": 2000,         # 单个目录最多记多少条
    "max_stage_mb": 512,       # 复制到暂存目录的上限（超了就拒跑，不冒险）
}

_INDEX_LOCK = threading.Lock()
_INDEX_TTL = 120.0             # 目录 mtime 看不出来的变化（子目录里新建文件）靠它兜底


def config_path(root: str | Path) -> Path:
    return Path(root) / CONFIG_FILENAME


def index_path(root: str | Path) -> Path:
    return Path(root) / INDEX_DIRNAME / INDEX_FILENAME


def runs_dir(root: str | Path) -> Path:
    return Path(root) / INDEX_DIRNAME / "runs"


def _as_dirs(value: Any) -> list[str]:
    """目录清单：去空、去重、只留字符串，顺序保持用户给的顺序。"""
    seen: list[str] = []
    for item in value or []:
        text = str(item or "").strip()
        if not text:
            continue
        norm = os.path.normpath(os.path.expanduser(text))
        if norm not in seen:
            seen.append(norm)
    return seen


def _int(value: Any, default: int, *, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def normalize(raw: Any) -> dict[str, Any]:
    """把任意来源的配置收敛成完整、可用的形状（读的一侧永不抛异常）。"""
    data = raw if isinstance(raw, dict) else {}
    return {
        "enabled": bool(data.get("enabled", DEFAULTS["enabled"])),
        "dirs": _as_dirs(data.get("dirs")),
        "timeout_seconds": _int(data.get("timeout_seconds"), DEFAULTS["timeout_seconds"],
                                low=5, high=3600),
        "max_depth": _int(data.get("max_depth"), DEFAULTS["max_depth"], low=1, high=8),
        "max_files": _int(data.get("max_files"), DEFAULTS["max_files"], low=50, high=50000),
        "max_stage_mb": _int(data.get("max_stage_mb"), DEFAULTS["max_stage_mb"],
                             low=8, high=8192),
    }


def load(root: str | Path) -> dict[str, Any]:
    """读配置；文件缺失或写坏了都回落默认（关着），控制台不会因此打不开。"""
    try:
        raw = json.loads(config_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return normalize({})
    return normalize(raw)


def save(root: str | Path, patch: dict[str, Any]) -> dict[str, Any]:
    """合并式写回：只改传进来的字段，原子落盘，半个文件不会被下次启动读到。"""
    current = load(root)
    merged = normalize({**current, **{k: v for k, v in (patch or {}).items() if v is not None}})
    path = config_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return merged


def _runnable(entry: os.DirEntry[str]) -> bool:
    suffix = Path(entry.name).suffix.lower()
    if suffix in RUNNABLE_EXTS:
        return True
    if os.name == "nt":
        return False
    try:                       # POSIX：带可执行位的无后缀脚本也算
        return bool(entry.stat(follow_symlinks=False).st_mode & 0o111)
    except OSError:
        return False


def scan(dirs: list[str], *, max_depth: int = 3, max_files: int = 2000) -> list[dict[str, Any]]:
    """广度优先扫设置目录，返回可执行工具清单（单个目录出错只跳过，不中断）。"""
    found: list[dict[str, Any]] = []
    for raw in dirs:
        base = Path(raw)
        if not base.is_dir():
            continue
        count = 0
        queue: list[tuple[Path, int]] = [(base, 0)]
        while queue and count < max_files:      # 单个目录封顶，装满就不再往下走
            folder, depth = queue.pop(0)
            try:
                entries = list(os.scandir(folder))
            except OSError:
                continue
            entries.sort(key=lambda item: item.name.casefold())
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        name = entry.name.casefold()
                        if depth + 1 <= max_depth and name not in SKIP_DIRS and not name.startswith("."):
                            queue.append((Path(entry.path), depth + 1))
                        continue
                    if not _runnable(entry):
                        continue
                    stat = entry.stat(follow_symlinks=False)
                except OSError:      # 权限、被占用、半删除：这条跳过
                    continue
                found.append({
                    "name": Path(entry.name).stem.casefold() or Path(entry.name).name.casefold(),
                    "file": entry.name,
                    "path": os.path.normpath(entry.path),
                    "dir": os.path.normpath(str(folder)),
                    "ext": Path(entry.name).suffix.lower(),
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                })
                count += 1
                if count >= max_files:
                    break
    # 同一个名字的工具可能有好几份：按名字、路径稳定排序，让 Agent 看到一致的顺序
    found.sort(key=lambda item: (item["name"], item["path"].casefold()))
    return found


def _dir_stamps(dirs: list[str]) -> list[list[Any]]:
    stamps: list[list[Any]] = []
    for raw in dirs:
        try:
            stat = Path(raw).stat()
            stamps.append([raw, stat.st_mtime_ns, stat.st_ino])
        except OSError:
            stamps.append([raw, None, None])
    return stamps


class LocalToolIndex:
    """一份可缓存的清单：目录 mtime 没变、没过保鲜期就直接用。"""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    # ---------------------------------------------------------------- 读写

    def read(self) -> dict[str, Any]:
        try:
            data = json.loads(index_path(self.root).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"dirs": [], "stamps": [], "scanned_at": 0.0, "tools": []}
        if not isinstance(data, dict):
            return {"dirs": [], "stamps": [], "scanned_at": 0.0, "tools": []}
        tools = data.get("tools")
        return {
            "dirs": [str(d) for d in data.get("dirs") or []],
            "stamps": data.get("stamps") if isinstance(data.get("stamps"), list) else [],
            "scanned_at": float(data.get("scanned_at") or 0.0),
            "tools": [t for t in tools if isinstance(t, dict)] if isinstance(tools, list) else [],
        }

    def write(self, index: dict[str, Any]) -> dict[str, Any]:
        path = index_path(self.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
        return index

    # ---------------------------------------------------------------- 刷新

    def refresh(self, config: dict[str, Any] | None = None) -> dict[str, Any]:
        """按配置重扫一遍，落盘后返回索引（含统计信息）。"""
        cfg = normalize(config if config is not None else load(self.root))
        with _INDEX_LOCK:
            tools = scan(cfg["dirs"], max_depth=cfg["max_depth"],
                         max_files=cfg["max_files"]) if cfg["dirs"] else []
            index = {
                "dirs": cfg["dirs"],
                "stamps": _dir_stamps(cfg["dirs"]),
                "scanned_at": time.time(),
                "tools": tools,
            }
            return self.write(index)

    def ensure(self, config: dict[str, Any] | None = None,
               *, ttl: float = _INDEX_TTL) -> dict[str, Any]:
        """需要新清单时才重扫：目录集合或 mtime 变了，或者超过保鲜期。"""
        cfg = normalize(config if config is not None else load(self.root))
        index = self.read()
        if not cfg["dirs"]:
            return index
        fresh = (index["dirs"] == cfg["dirs"]
                 and index["stamps"] == _dir_stamps(cfg["dirs"])
                 and index["tools"]
                 and time.time() - index["scanned_at"] <= ttl)
        return index if fresh else self.refresh(cfg)

    # ---------------------------------------------------------------- 查询

    @staticmethod
    def search(tools: list[dict[str, Any]], query: str = "", *,
               limit: int = 20) -> list[dict[str, Any]]:
        """按名字/路径子串过滤；完全同名的排前面，空查询就是按名字浏览。"""
        words = [w for w in str(query or "").casefold().split() if w]
        hits: list[tuple[int, str, dict[str, Any]]] = []
        for tool in tools:
            name = str(tool.get("name") or "")
            path = str(tool.get("path") or "").casefold()
            text = f"{name} {path}"
            score = sum(word in text for word in words)
            if words and not score:
                continue
            rank = 0 if not words else 2 if name == words[0] else 1
            hits.append((rank, name, tool))
        hits.sort(key=lambda row: (-row[0], row[1], str(row[2].get("path", "")).casefold()))
        limit = max(1, min(int(limit or 20), 100))
        return [dict(tool) for _, _, tool in hits[:limit]]

    @staticmethod
    def find(tools: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
        """按名字找；重名时给第一个（清单已按 名字+路径 排好序，结果稳定）。"""
        wanted = str(name or "").strip().casefold()
        if not wanted:
            return None
        for tool in tools:
            if str(tool.get("name") or "") == wanted:
                return dict(tool)
        for tool in tools:                      # 退一步：允许传文件名
            if str(tool.get("file") or "").casefold() == wanted:
                return dict(tool)
        return None


def summary(index: dict[str, Any]) -> dict[str, Any]:
    """给控制台看的统计：目录数、工具数、扫描时间、各类后缀分布。"""
    tools = index.get("tools") or []
    kinds: dict[str, int] = {}
    for tool in tools:
        ext = str(tool.get("ext") or "")
        kinds[ext] = kinds.get(ext, 0) + 1
    return {
        "dirs": len(index.get("dirs") or []),
        "tools": len(tools),
        "scanned_at": index.get("scanned_at") or 0.0,
        "kinds": dict(sorted(kinds.items(), key=lambda item: (-item[1], item[0]))),
    }
