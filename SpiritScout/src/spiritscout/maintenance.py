"""可回收缓存盘点与清理。

只删「放久了没用、丢了还能重建、丢了不影响下次开工」的东西：旧会话工作区
（靶机产物、沙箱目录、浏览器输出）、暂存上传、构建产物、解释器缓存。

**绝不删**：本地工具（`.tools` 里装好的二进制）、虚拟环境、配置、密钥与密钥库、
管理员库、经验库、资源目录、源码与测试。名单是白名单式的——只认下面
`_targets()` 里显式列出的路径，删之前再校验一次「解引用后仍在工作区内」。
"""
from __future__ import annotations

import os
import shutil
import time
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path

#: 这些目录名出现在路径任何一层都不许动（工具、虚拟环境、依赖、配置、源码、版本库）
PROTECTED_DIRS = frozenset({
    ".tools", ".venv", "venv", "node_modules", ".git", ".github", "configs",
    "src", "tests", "docs", "deploy", "resources",
})

#: 找 `__pycache__` 时连下都不下的目录——里面的字节码也是工具的一部分
_HARD_SKIP = frozenset({".tools", ".venv", "venv", "node_modules", ".git"})

#: 这些文件名或后缀一律不碰：密钥、账号、经验、资源索引
PROTECTED_FILES = frozenset({
    "vault.db", "vault.key", "admin.db", "auth.key", "preferences.json",
    "experience.db", "catalog.db", "models.yaml", "agent_models.yaml",
})
PROTECTED_SUFFIXES = (".key", ".pem")

#: 会话状态里这些算「还在跑」，任何年龄都不清
ACTIVE_STATES = frozenset({"created", "running", "queued", "pausing", "paused"})

DEFAULT_DAYS = 30
_MIN_DAYS = 1
_MAX_DAYS = 3650


@dataclass(frozen=True)
class CacheItem:
    """一条可回收目标：给人看的账目，不是删除指令。"""

    key: str                 # sessions / staging / build / dev-cache
    label: str
    path: str
    bytes: int
    files: int
    last_used: float         # 最近一次写入的 epoch 秒；没有文件就是目录 mtime
    removable: bool
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "key": self.key, "label": self.label, "path": self.path,
            "bytes": self.bytes, "files": self.files,
            "last_used": _iso(self.last_used),
            "removable": self.removable, "reason": self.reason,
        }


@dataclass
class CachePlan:
    days: int
    items: list[CacheItem] = field(default_factory=list)
    protected: list[str] = field(default_factory=list)

    @property
    def total_bytes(self) -> int:
        return sum(item.bytes for item in self.items)

    @property
    def removable(self) -> list[CacheItem]:
        return [item for item in self.items if item.removable]

    @property
    def removable_bytes(self) -> int:
        return sum(item.bytes for item in self.removable)

    def as_dict(self) -> dict[str, object]:
        return {
            "days": self.days,
            "items": [item.as_dict() for item in self.items],
            "protected": list(self.protected),
            "total_bytes": self.total_bytes,
            "total_files": sum(item.files for item in self.items),
            "removable_bytes": self.removable_bytes,
            "removable_count": len(self.removable),
        }


def _iso(epoch: float) -> str:
    if not epoch:
        return ""
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(epoch))
    except (OSError, OverflowError, ValueError):
        return ""


def _clamp_days(days: int) -> int:
    try:
        value = int(days)
    except (TypeError, ValueError):
        return DEFAULT_DAYS
    return max(_MIN_DAYS, min(_MAX_DAYS, value))


def _measure(path: Path) -> tuple[int, int, float]:
    """(字节, 文件数, 最近写入时间)；不跟随符号链接。"""
    if path.is_file() and not path.is_symlink():
        try:
            stat = path.stat()
        except OSError:
            return 0, 0, 0.0
        return stat.st_size, 1, stat.st_mtime
    total, count, newest = 0, 0, 0.0
    for base, _dirs, files in os.walk(path, followlinks=False):
        for name in files:
            child = Path(base) / name
            try:
                stat = child.stat() if not child.is_symlink() else None
            except OSError:
                continue
            if stat is None:
                continue
            total += stat.st_size
            count += 1
            newest = max(newest, stat.st_mtime)
    if not newest:
        try:
            newest = path.stat().st_mtime
        except OSError:
            newest = 0.0
    return total, count, newest


def _session_state(path: Path) -> str:
    """从 meta.json 读状态；读不出就当未知（未知按活会话处理，宁可不删）。"""
    import json

    try:
        payload = json.loads((path / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(payload.get("status") or "")


def _is_protected(path: Path) -> bool:
    # 字节码缓存是唯一住在受保护目录里的例外：能随时重建，删了只是慢一次导入
    if path.name == "__pycache__" or path.name.endswith(".pyc"):
        return False
    if any(part in PROTECTED_DIRS for part in path.parts):
        return True
    name = path.name.lower()
    if name in PROTECTED_FILES:
        return True
    return name.endswith(PROTECTED_SUFFIXES)


def _project_root(root: Path) -> Path | None:
    """工作区是 `<项目>/.spiritscout` 时返回项目目录，否则 None（不猜）。"""
    return root.parent if root.name == ".spiritscout" else None


def _age_cutoff(days: int, now: float) -> float:
    return now - days * 86400


def _dir_target(key: str, label: str, path: Path, *, cutoff: float,
                protected_reason: str = "") -> CacheItem:
    size, count, newest = _measure(path)
    old_enough = newest and newest <= cutoff
    if protected_reason:
        removable, reason = False, protected_reason
    elif not count and not size:
        removable, reason = True, "空目录"
    elif old_enough:
        removable, reason = True, ""
    else:
        removable, reason = False, "还在保留期内"
    return CacheItem(key=key, label=label, path=str(path), bytes=size,
                     files=count, last_used=newest, removable=removable,
                     reason=reason)


def plan_cache(root: str | Path, *, days: int = DEFAULT_DAYS,
               now: float | None = None) -> CachePlan:
    """盘点可回收项；不改动任何文件。"""
    base = Path(root).expanduser()
    plan = CachePlan(days=_clamp_days(days))
    if not base.exists():
        return plan
    now = time.time() if now is None else now
    cutoff = _age_cutoff(plan.days, now)
    project = _project_root(base)

    sessions = base / "sessions"
    if sessions.is_dir():
        for child in sorted(sessions.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue                    # .execution-locks 之类的运行时目录
            if _is_protected(child):
                plan.protected.append(str(child))
                continue
            state = _session_state(child)
            if state in ACTIVE_STATES:
                size, count, newest = _measure(child)
                plan.items.append(CacheItem(
                    key="sessions", label=f"会话 {child.name}", path=str(child),
                    bytes=size, files=count, last_used=newest, removable=False,
                    reason=f"会话还在跑（{state}）"))
                continue
            plan.items.append(_dir_target("sessions", f"会话 {child.name}",
                                          child, cutoff=cutoff))

    staging = base / "uploads-staging"
    if staging.is_dir():
        for child in sorted(staging.iterdir()):
            if _is_protected(child):
                plan.protected.append(str(child))
                continue
            plan.items.append(_dir_target("staging", f"暂存 {child.name}",
                                          child, cutoff=cutoff))

    if project is not None:
        build = project / "build"
        if build.is_dir():
            plan.items.append(_dir_target("build", "构建产物 build/", build,
                                          cutoff=cutoff))
        for cache_dir in (project / ".ruff_cache",):
            if cache_dir.is_dir():
                plan.items.append(_dir_target("dev-cache", "ruff 缓存",
                                              cache_dir, cutoff=cutoff))
        for pycache in _pycache_dirs(project):
            plan.items.append(_dir_target("dev-cache", f"字节码缓存 {pycache.name}",
                                          pycache, cutoff=cutoff))
    return plan


def _pycache_dirs(project: Path) -> list[Path]:
    """项目内的 `__pycache__`；工具、venv、依赖树整棵跳过，其余字节码都能重建。"""
    found: list[Path] = []
    for base, dirs, _files in os.walk(project, followlinks=False):
        dirs[:] = [d for d in dirs if d not in _HARD_SKIP]
        if Path(base).name == "__pycache__":
            found.append(Path(base))
            dirs[:] = []
    return found


def _assert_deletable(path: Path, base: Path, project: Path | None) -> None:
    """删之前再验一遍：不是符号链接、解引用后仍在工作区（或项目）里。"""
    if path.is_symlink():
        raise ValueError(f"拒绝删除符号链接：{path}")
    resolved = path.resolve()
    roots = [base.resolve()]
    if project is not None:
        roots.append(project.resolve())
    if not any(resolved == root or root in resolved.parents for root in roots):
        raise ValueError(f"拒绝删除工作区之外的路径：{resolved}")
    if _is_protected(resolved):
        raise ValueError(f"拒绝删除受保护路径：{resolved}")


def purge_cache(root: str | Path, *, days: int = DEFAULT_DAYS, keys: list[str] | None = None,
                now: float | None = None) -> dict[str, object]:
    """按盘点结果删除；返回释放的字节与逐项结果。"""
    base = Path(root).expanduser()
    project = _project_root(base)
    plan = plan_cache(base, days=days, now=now)
    selected = set(keys or [])
    removed: list[dict[str, object]] = []
    kept: list[dict[str, object]] = []
    freed = 0
    for item in plan.items:
        if not item.removable or (selected and item.key not in selected):
            kept.append(item.as_dict())
            continue
        path = Path(item.path)
        try:
            _assert_deletable(path, base, project)
        except ValueError as exc:
            entry = item.as_dict()
            entry["reason"] = str(exc)
            kept.append(entry)
            continue
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)   # Windows 上 WAL 偶尔占着
        else:
            with suppress(OSError):
                path.unlink()
        still_there = path.exists()
        entry = item.as_dict()
        if still_there:
            entry["reason"] = "删除时被占用，稍后再试"
            kept.append(entry)
            continue
        freed += item.bytes
        removed.append(entry)
    return {
        "days": plan.days,
        "freed_bytes": freed,
        "removed": removed,
        "kept": kept,
        "before_bytes": plan.total_bytes,
        "protected": list(plan.protected),
    }
