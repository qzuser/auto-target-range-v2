"""黑板存储：SQLite 强一致 + 版本号乐观锁 + 写入权限分级 + 事件发布。

设计书 6.1 一致性机制：
- 全局唯一 ID + 版本号控制（写入校验版本，避免脏数据覆盖）；
- 写入统一经汇聚引擎校验通过后才发布事件（6.9 写入校验）；
- 事件携带「黑板层 + 数据 ID + 版本」，消费方幂等。
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import tempfile
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from spiritscout.blackboard.layers import can_write
from spiritscout.bus.base import EventBus
from spiritscout.core.exceptions import PolicyViolation, VersionConflict
from spiritscout.core.models import AgentType, BlackboardLayer, Event
from spiritscout.core.sqlite_ro import ro_uri

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bb_records (
    layer       TEXT NOT NULL,
    record_id   TEXT NOT NULL,
    version     INTEGER NOT NULL,
    dedup_key   TEXT NOT NULL DEFAULT '',
    data        TEXT NOT NULL,
    updated_by  TEXT NOT NULL DEFAULT '',
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (layer, record_id)
);
CREATE INDEX IF NOT EXISTS idx_bb_dedup ON bb_records(layer, dedup_key);
CREATE TABLE IF NOT EXISTS bb_record_history (
    layer TEXT NOT NULL, record_id TEXT NOT NULL, version INTEGER NOT NULL,
    data TEXT NOT NULL, updated_by TEXT NOT NULL, updated_at TEXT NOT NULL,
    PRIMARY KEY(layer, record_id, version)
);
CREATE TABLE IF NOT EXISTS bb_event_outbox (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    event_json TEXT NOT NULL,
    delivered INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_bb_outbox_pending ON bb_event_outbox(sequence) WHERE delivered=0;
"""


class Blackboard:
    """结构化分层黑板（8 层）。线程安全；事件发布走环形总线。"""

    def __init__(self, db_path: str | Path, bus: EventBus | None = None, *, readonly: bool = False):
        self._path = Path(db_path)
        if not readonly:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            ro_uri(self._path) if readonly else str(self._path),
            uri=readonly, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        if not readonly:
            #：WAL + busy_timeout——Web 控制台/CLI status 等读进程与
            # 运行中写提交并发时不再瞬态 database is locked（读写不互堵，写等待 5s）
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            if (self._conn.execute("SELECT 1 FROM sqlite_master WHERE name='bb_records'").fetchone()
                    and not self._conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE name='bb_event_outbox'").fetchone()):
                self._backup_before_upgrade()
            if (self._conn.execute("SELECT 1 FROM sqlite_master WHERE name='bb_records'").fetchone()
                    and not self._conn.execute("SELECT 1 FROM sqlite_master WHERE name='bb_record_history'").fetchone()):
                self._backup_before_upgrade("pre-history-v1")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
        self._lock = threading.Lock()
        self._bus = bus
        self._outbox_task: asyncio.Task | None = None
        self.asset_observer = None
        self.record_observer = None

    def _backup_before_upgrade(self, suffix: str = "pre-runtime-v1") -> None:
        """旧库首次增表前做 SQLite 在线备份，包含 WAL 中已提交的数据。"""
        backup = self._path.with_name(self._path.name + f".{suffix}.bak")
        if backup.exists():
            return
        fd, name = tempfile.mkstemp(prefix=".bb-backup-", dir=self._path.parent)
        os.close(fd)
        try:
            target = sqlite3.connect(name)
            try:
                self._conn.backup(target)
            finally:
                target.close()
            with suppress(FileExistsError):
                os.link(name, backup)
        finally:
            Path(name).unlink(missing_ok=True)

    # ------------------------------------------------------------ 基础读写

    @property
    def database_path(self) -> Path:
        """用于核对数据库实际执行权，调用方不依赖私有连接属性。"""
        return self._path.resolve()

    def backup_before_upgrade(self, version: int) -> None:
        """执行台账增量迁移前复用在线备份，不能直接复制含 WAL 的主文件。"""
        with self._lock:
            self._backup_before_upgrade(f"pre-execution-v{version}")

    @contextmanager
    def transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        """共用连接与写锁；读后写可先锁住跨连接事务，确保版本检查原子化。"""
        with self._lock, self._conn:
            if immediate:
                self._conn.execute("BEGIN IMMEDIATE")
            yield self._conn

    def write(
        self,
        layer: BlackboardLayer,
        record_id: str,
        data: dict[str, Any],
        *,
        agent_type: AgentType = AgentType.MASTER,
        updated_by: str = "",
        dedup_key: str = "",
        expected_version: int | None = None,
        priority: int = 5,
    ) -> int:
        """写入记录并发布事件，返回新版本号。

                - 写权限分级：agent_type 无该层写权限 → PolicyViolation；
                - 乐观锁：expected_version 与库中不一致 → VersionConflict。
                """
        if not can_write(agent_type, layer):
            raise PolicyViolation(f"{agent_type.value} 无黑板层 {layer.value} 写入权限")
        now = datetime.now(UTC).isoformat()
        payload = json.dumps(data, ensure_ascii=False)
        # Web 入口短连接与运行态并发写：先取得数据库写锁，再读当前版本。
        with self.transaction(immediate=True):
            if dedup_key:
                # 同层同 dedup_key 只存一条：后续写入升级既有记录（版本
                # 递增、历史留痕）而不是追加新条——「同一发现只存一条」
                # 在此落实，否则同一 URL 的重复观察会刷满发现组。
                # 排序口径与读取方（find_by_dedup_key/query）一致：历史
                # 重复时两边都落在最近更新的一条，否则收敛写回撞版本冲突
                hit = self._conn.execute(
                    "SELECT record_id FROM bb_records WHERE layer=? AND dedup_key=?"
                    " ORDER BY updated_at DESC LIMIT 1",
                    (layer.value, dedup_key)).fetchone()
                if hit:
                    record_id = hit["record_id"]
            row = self._conn.execute(
                "SELECT version FROM bb_records WHERE layer=? AND record_id=?",
                (layer.value, record_id),
            ).fetchone()
            current = row["version"] if row else 0
            if expected_version is not None and expected_version != current:
                raise VersionConflict(layer.value, record_id, expected_version, current)
            # 首次升级时先保存已有现值，后续在同一事务留存每个版本。
            self._conn.execute(
                "INSERT OR IGNORE INTO bb_record_history SELECT layer,record_id,version,data,updated_by,updated_at "
                "FROM bb_records WHERE layer=? AND record_id=?", (layer.value, record_id))
            new_version = current + 1
            self._conn.execute(
                "INSERT INTO bb_record_history VALUES(?,?,?,?,?,?)",
                (layer.value, record_id, new_version, payload, updated_by, now))
            self._conn.execute(
                """INSERT INTO bb_records(layer, record_id, version, dedup_key, data, updated_by, updated_at)
                   VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(layer, record_id) DO UPDATE SET
                       version=excluded.version, dedup_key=excluded.dedup_key,
                       data=excluded.data, updated_by=excluded.updated_by,
                       updated_at=excluded.updated_at""",
                (layer.value, record_id, new_version, dedup_key, payload, updated_by, now),
            )
            event = Event(event_id=f"evt-{uuid.uuid4().hex}", topic=f"bb.{layer.value}",
                          layer=layer, data_id=record_id, version=new_version,
                          priority=priority, source=updated_by, payload=data)
            # 通知仅携带定位信息；黑板记录与 outbox 在同一事务提交。
            self._conn.execute("INSERT INTO bb_event_outbox(event_json) VALUES(?)",
                               (event.model_dump_json(),))
        self._wake_outbox()
        if layer == BlackboardLayer.ASSET and self.asset_observer is not None:
            self.asset_observer(record_id, new_version, data)
        if self.record_observer is not None:
            self.record_observer(layer,record_id,new_version,data)
        return new_version

    def status_counts(self, layer: BlackboardLayer) -> dict[str, int]:
        """完整状态统计独立于展示页采样。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT COALESCE(json_extract(data, '$.status'),'candidate'),COUNT(*) "
                "FROM bb_records WHERE layer=? GROUP BY 1", (layer.value,)).fetchall()
        return {str(row[0]): row[1] for row in rows}

    def read(self, layer: BlackboardLayer, record_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT data FROM bb_records WHERE layer=? AND record_id=?",
                (layer.value, record_id),
            ).fetchone()
        return json.loads(row["data"]) if row else None

    def read_versioned(self, layer: BlackboardLayer, record_id: str) -> tuple[dict[str, Any], int] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT data, version FROM bb_records WHERE layer=? AND record_id=?",
                (layer.value, record_id),
            ).fetchone()
        return (json.loads(row["data"]), row["version"]) if row else None

    def query(
        self,
        layer: BlackboardLayer,
        *,
        dedup_key: str | None = None,
        limit: int = 1000,
        data_filter: tuple[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        sql = "SELECT record_id, version, data, updated_by, updated_at FROM bb_records WHERE layer=?"
        params: list[Any] = [layer.value]
        if dedup_key is not None:
            sql += " AND dedup_key=?"
            params.append(dedup_key)
        if data_filter is not None:
            field, value = data_filter
            if not field.isidentifier():
                raise ValueError("黑板筛选字段必须为标识符")
            sql += " AND json_extract(data, ?)=?"
            params.extend((f'$.{field}', value))
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [
            {
                "record_id": r["record_id"],
                "version": r["version"],
                "data": json.loads(r["data"]),
                "updated_by": r["updated_by"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]

    def find_by_dedup_key(self, layer: BlackboardLayer, dedup_key: str) -> dict[str, Any] | None:
        results = self.query(layer, dedup_key=dedup_key, limit=1)
        return results[0] if results else None

    def count(self, layer: BlackboardLayer) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS c FROM bb_records WHERE layer=?", (layer.value,)
            ).fetchone()
        return int(row["c"])

    def purge(self, layer: BlackboardLayer, *, keep: tuple[str, ...] = ()) -> int:
        """清掉该层除 `keep` 之外的记录（含历史版本），返回删除条数。

        用途是切断跨题关联：换了题目以后，资产、线索、漏洞、凭据、拓扑和
        任务状态都只对上一题成立，留着会被新题当成既有事实沿用。`keep`
        留给那些描述"谁授权、这次是哪道题"的记录——它们随会话走，不随
        题目变。删除只动这一层的行，方向键、事件流、其他层都不受影响。
        """
        sql = "SELECT record_id FROM bb_records WHERE layer=?"
        params: list[Any] = [layer.value]
        if keep:
            sql += " AND record_id NOT IN (" + ",".join("?" * len(keep)) + ")"
            params.extend(keep)
        with self.transaction(immediate=True) as conn:
            ids = [row["record_id"] for row in conn.execute(sql, params)]
            if not ids:
                return 0
            marks = ",".join("?" * len(ids))
            conn.execute(
                "DELETE FROM bb_records WHERE layer=? AND record_id IN (" + marks + ")",
                (layer.value, *ids))
            conn.execute(
                "DELETE FROM bb_record_history WHERE layer=? AND record_id IN (" + marks + ")",
                (layer.value, *ids))
        return len(ids)

    def close(self) -> None:
        if self._outbox_task is not None:
            self._outbox_task.cancel()
        with self._lock:
            self._conn.close()

    async def aclose(self) -> None:
        """先收口通知协程，再关闭数据库；未送达事件留待下次启动。"""
        if self._outbox_task is not None:
            self._outbox_task.cancel()
            await asyncio.gather(self._outbox_task, return_exceptions=True)
        self.close()

    async def flush_outbox(self, limit: int = 100) -> int:
        """至少一次通知；发布成功后才能标记，重复通知由 event_id 去重。"""
        if self._bus is None:
            return 0
        with self._lock:
            rows = self._conn.execute("SELECT sequence,event_json FROM bb_event_outbox"
                                      " WHERE delivered=0 ORDER BY sequence LIMIT ?",
                                      (max(1, min(limit, 1000)),)).fetchall()
        delivered = 0
        for row in rows:
            await self._bus.publish(Event.model_validate_json(row["event_json"]))
            with self.transaction() as conn:
                conn.execute("UPDATE bb_event_outbox SET delivered=1 WHERE sequence=?",
                             (row["sequence"],))
            delivered += 1
        return delivered

    def start_notifications(self) -> None:
        """启动时补送历史 outbox，断线后后台重试；不影响已提交的黑板。"""
        self._wake_outbox()

    def _wake_outbox(self) -> None:
        if self._bus is None or (self._outbox_task and not self._outbox_task.done()):
            return
        with suppress(RuntimeError):
            self._outbox_task = asyncio.get_running_loop().create_task(self._deliver_outbox())

    async def _deliver_outbox(self) -> None:
        while True:
            try:
                await self.flush_outbox()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001, S110
                # 发布失败不能删除记录，Redis 恢复后继续投递。
                pass
            await asyncio.sleep(0.5)
