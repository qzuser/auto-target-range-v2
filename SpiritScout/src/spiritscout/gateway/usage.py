"""逐笔用量持久化和按文件版本缓存的读取视图；旧 usage.json 保持可读。"""

from __future__ import annotations

import copy
import json
import os
import sqlite3
import threading
import uuid
from contextlib import closing, suppress
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from spiritscout.core.sqlite_ro import ro_uri
from spiritscout.gateway.cache import cache_summary


class UsageCall(BaseModel):
    ts: float = Field(allow_inf_nan=False)
    tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0, ge=0, allow_inf_nan=False)
    model: str = ""
    mode: str = ""
    call_id: str = ""
    runtime_version: str = ""
    patch_optimization_enabled: bool | None = None
    sdk_attempts: int | None = Field(default=None, ge=0)
    unreported_attempts: int | None = Field(default=None, ge=0)
    reported_attempt_input_tokens: int | None = Field(default=None, ge=0)
    reported_attempt_output_tokens: int | None = Field(default=None, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    cache_write_tokens: int | None = Field(default=None, ge=0)
    first_delta_ms: float | None = Field(default=None, ge=0)
    task_type: str = ""
    actor: str = ""
    request_bytes: int | None = Field(default=None, ge=0)
    reused_prefix_bytes: int | None = Field(default=None, ge=0)
    new_suffix_bytes: int | None = Field(default=None, ge=0)
    context_parts: dict[str, int] = Field(default_factory=dict)
    cache_scope: str = ""
    task_id: str = ""
    route_id: str = ""
    estimated_cost_cny_min: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    estimated_cost_cny_max: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    pricing_version: str = ""
    pricing_period: str = ""


class UsageSnapshot(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    used_tokens: int = Field(ge=0)
    used_usd: float = Field(default=0, ge=0)
    cache: dict[str, Any] = Field(default_factory=dict)
    per_model_tokens: dict[str, int] = Field(default_factory=dict)
    per_mode_tokens: dict[str, int] = Field(default_factory=dict)
    call_series: list[UsageCall] = Field(default_factory=list)
    calls: int = Field(default=0, ge=0)
    mode: str = ""


def file_version(path: Path) -> tuple[int, ...]:
    try:
        stat = path.stat()
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns
    except FileNotFoundError:
        return ()


class UsageLedger:
    """一笔调用一个事务；崩溃恢复不依赖摘要刷新，重复调用 ID 不重复计量。"""

    def __init__(self, path: Path, legacy: Path | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=10)) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("CREATE TABLE IF NOT EXISTS baseline(id INTEGER PRIMARY KEY CHECK(id=1),data TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS calls(seq INTEGER PRIMARY KEY,call_id TEXT NOT NULL UNIQUE,data TEXT NOT NULL)")
            if not conn.execute("SELECT 1 FROM baseline WHERE id=1").fetchone():
                baseline: dict[str, Any] = {"used_tokens": 0}
                if legacy and legacy.is_file():
                    with suppress(OSError, ValueError):
                        baseline = UsageSnapshot.model_validate_json(legacy.read_bytes()).model_dump()
                conn.execute("INSERT OR IGNORE INTO baseline VALUES(1,?)", (json.dumps(baseline),))
            conn.commit()
        os.chmod(self.path, 0o600)

    def append(self, entry: dict[str, Any]) -> bool:
        """记一笔；返回是否真的新增（同 call_id 重复写返回 False，用于并库计数）。"""
        row = UsageCall.model_validate({**entry, "call_id": entry.get("call_id") or uuid.uuid4().hex}).model_dump()
        with closing(sqlite3.connect(self.path, timeout=10)) as conn, conn:
            conn.execute("PRAGMA synchronous=FULL")
            cur = conn.execute("INSERT OR IGNORE INTO calls(call_id,data) VALUES(?,?)",
                               (row["call_id"], json.dumps(row, ensure_ascii=False, separators=(",", ":"))))
        return cur.rowcount > 0

    def read(self) -> dict[str, Any]:
        return read_usage(self.path.with_suffix(".json"), ledger=self.path) or {"used_tokens": 0}


def _load_ledger(path: Path) -> dict[str, Any]:
    with closing(sqlite3.connect(ro_uri(path), uri=True)) as conn:
        conn.execute("BEGIN")
        base = UsageSnapshot.model_validate_json(conn.execute("SELECT data FROM baseline WHERE id=1").fetchone()[0]).model_dump()
        rows = [UsageCall.model_validate_json(row[0]).model_dump()
                for row in conn.execute("SELECT data FROM calls ORDER BY seq")]
    for row in rows:
        base["used_tokens"] += row["tokens"]
        base["used_usd"] += row["cost_usd"]
        model, mode = row["model"], row["mode"]
        base["per_model_tokens"][model] = base["per_model_tokens"].get(model, 0) + row["tokens"]
        if mode:
            base["per_mode_tokens"][mode] = base["per_mode_tokens"].get(mode, 0) + row["tokens"]
        base["mode"] = mode
    base["call_series"].extend(rows)
    base["calls"] = max(base["calls"], len(base["call_series"]) - len(rows)) + len(rows)
    return base


@lru_cache(maxsize=512)
def _cache_key(path: Path) -> str:
    """账本缓存键：真实路径字符串。

    ``Path.resolve()`` 在 Windows 上要一次系统调用；同一个账本会被反复读，
    这里按原始路径记住归一化结果（工作区内路径不会变）。
    """
    try:
        return str(path.resolve())
    except OSError:                     # 还没建出来的账本按原样当键
        return str(path)


class _FileCache:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.version: tuple[Any, ...] | None = None
        self.snapshot: dict[str, Any] | None = None


@lru_cache(maxsize=256)
def _file_cache(path: str, ledger: bool) -> _FileCache:
    # 只为每个文件保留最新快照，不能按每次调用的版本积累整份历史。
    return _FileCache()


def _cached_read(path: str, ledger: bool, version: tuple[Any, ...]) -> dict[str, Any]:
    cache = _file_cache(path, ledger)
    with cache.lock:
        if cache.version != version or cache.snapshot is None:
            snapshot = (_load_ledger(Path(path)) if ledger else
                        UsageSnapshot.model_validate_json(Path(path).read_bytes()).model_dump())
            snapshot["cache"] = cache_summary(snapshot["call_series"])
            cache.snapshot, cache.version = snapshot, version
        return cache.snapshot


def read_usage(legacy: Path, *, ledger: Path | None = None,
               readonly: bool = False) -> dict[str, Any] | None:
    """原子替换、WAL 追加和同长度改写都会失效；默认不让调用方修改缓存本体。

    ``readonly=True`` 直接把缓存本体交出去，**调用方不得改动返回值**（也不要嵌进
    会被后续修改的结构里）。深拷贝一份上百笔的调用序列要 8 ms 左右，而统计页、
    仪表盘、状态面这些地方只是读一遍就序列化——纯读的地方传 ``readonly=True``，
    轮询时的开销从毫秒级掉到微秒级。会长期持有或改写的调用（如把结果存进会话
    摘要）必须用默认的拷贝语义。
    """
    ledger = ledger or legacy.with_suffix(".db")
    # 先看新式账本，没有再退回旧 JSON：每次只 stat 该 stat 的那个文件，
    # 附加的 -wal 也只在账本存在时才去量（轮询时的系统调用能省一半）
    version = file_version(ledger)
    if version:
        version = (version, file_version(Path(str(ledger) + "-wal")))
        path, is_ledger = ledger, True
    else:
        legacy_version = file_version(legacy)
        if not legacy_version:
            return None
        path, version, is_ledger = legacy, (legacy_version,), False
    try:
        snapshot = _cached_read(_cache_key(path), is_ledger, version)
        return snapshot if readonly else copy.deepcopy(snapshot)
    except (OSError, ValueError, sqlite3.Error, TypeError):
        return None


def bind_usage(gateway: Any, legacy: Path) -> UsageLedger:
    ledger = UsageLedger(legacy.with_suffix(".db"), legacy)
    gateway.budget.restore(ledger.read())
    def record(entry: dict[str, Any]) -> None:
        try:
            ledger.append(entry)
        except (OSError, ValueError, sqlite3.Error) as exc:
            gateway.audit.log("usage.persist_failed", "gateway", {"error": str(exc)[:300]})
    gateway.budget.on_call = record
    return ledger


def shared_ledger_path(cfg: Any) -> Path:
    """用量账本落点：**基础工作区**，不是会话工作区。

    会话工作区（``sessions/<id>/``）随会话归档与清理一起消失；账本落在里面，
    「用量」页读的共享库就永远是 0——题型跑完、token 花掉，页面上什么都没有。
    ``_session_cfg`` 已经把基础工作区写在 ``workspace.guard_root``（它本来就要
    指控制面根，好让沙箱连 vault、兄弟会话、审计一起遮），这里直接用它；
    单机 CLI 没有这层重定向时退回 ``workspace.root``。
    """
    ws = getattr(cfg, "workspace", None)
    base = str(getattr(ws, "guard_root", "") or "").strip()
    return Path(base or str(getattr(ws, "root", "") or ".")) / "usage.json"


def absorb_session_ledgers(target: str | Path, sessions_dir: str | Path) -> int:
    """把会话目录里遗留的账本并进共享库，返回并入笔数。

    0.36.5 及以前 ``runtime`` 把账本绑在会话工作区，于是解题的调用记在
    ``sessions/<id>/usage.db``，而页面读共享库——同一批 token 两处都看不到；
    会话被清理后文件也没了。这里做一次性并库，``append`` 按 ``call_id``
    去重（``INSERT OR IGNORE``），重复执行无副作用。

    ``target`` 是**旧式 json 路径**（和 ``bind_usage`` 同口径），真正的库是
    同名 ``.db``。0.36.6 曾直接拿 ``target`` 当库路径，于是在工作区里多出一个
    名叫 ``usage.json`` 的 SQLite 文件——读取侧优先认 ``.db``，那两个库谁都
    看不到对方，合并结果等于白做。
    """
    shared = UsageLedger(Path(target).with_suffix(".db"))
    source_dir = Path(sessions_dir)
    merged = 0
    if not source_dir.is_dir():
        return 0
    for legacy in sorted(source_dir.glob("*/usage.db")):
        if not legacy.is_file() or legacy.resolve() == shared.path.resolve():
            continue
        for row in _read_ledger_rows(legacy):
            if shared.append(row):
                merged += 1
    return merged


def _read_ledger_rows(path: Path) -> list[dict[str, Any]]:
    """读一本旧账本里的逐笔记录；读不动就当没有（不拖累启动）。"""
    rows: list[dict[str, Any]] = []
    try:
        with closing(sqlite3.connect(ro_uri(path), uri=True)) as conn:
            for (data,) in conn.execute("SELECT data FROM calls ORDER BY seq"):
                try:
                    entry = json.loads(data)
                except (TypeError, ValueError):
                    continue
                if isinstance(entry, dict):
                    rows.append(entry)
    except (OSError, sqlite3.Error):
        return []
    return rows
