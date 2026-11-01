"""会话经验的共享存储与检索。

会话结束后提炼适用场景和经验，保存在 experience.root/experience.db。
独立于会话工作区，供后续会话检索。"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from spiritscout.core.audit import NullAuditLogger
from spiritscout.core.exceptions import SpiritScoutError
from spiritscout.core.ids import new_id
from spiritscout.knowledge import merge as merge_mod

_INSIGHT_CAP = 600
_CONTEXT_CAP = 300

_COLUMNS = ["insight_id", "insight", "context", "tags",
            "source_session", "source_model", "ts",
            # 二次提炼（合并压缩）的溯源：merged_into 指向合并后的条目，
            # merged_from 记着被吸收的原件 id。原件不删，只隐藏，可还原。
            "merged_into", "merged_from"]
_MERGE_COLUMNS = {"merged_into": "TEXT DEFAULT ''", "merged_from": "TEXT DEFAULT '[]'"}


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """老库补列：读路径仍按缺列降级，写入前先把列补齐。"""
    have = {row[1] for row in conn.execute("PRAGMA table_info(insights)")}
    for name, ddl in _MERGE_COLUMNS.items():
        if name not in have:
            conn.execute(f"ALTER TABLE insights ADD COLUMN {name} {ddl}")
    conn.commit()


def _has_column(conn: sqlite3.Connection, name: str) -> bool:
    try:
        return any(row[1] == name for row in conn.execute("PRAGMA table_info(insights)"))
    except sqlite3.Error:
        return False


def experience_db_path(root: str, workspace: str) -> Path:
    """经验库文件路径：root 非空用 root，否则跟随工作区（CLI 兼容语义）。"""
    base = Path(root) if str(root or "").strip() else Path(workspace)
    return base / "experience.db"


def absorb_session_dbs(target: str | Path, sessions_dir: str | Path) -> int:
    """把旧版本落在各会话目录里的经验并进共享库，返回并入条数。

    0.30.0 及以前，手动提炼读的是会话级配置，``experience.root`` 为空时
    ``experience_db_path`` 会退化成 ``<会话目录>/experience.db``——条目写进了
    会话自己的库，而「经验库」页和开工召回读的是共享库，于是「提炼了却查不到」。
    这里做一次性并库：目标库已有的同文洞察按重复跳过（``ExperienceStore.add``
    自带去重），所以重复执行无副作用。
    """
    target_path = Path(target)
    source_dir = Path(sessions_dir)
    if not source_dir.is_dir():
        return 0
    merged = 0
    store: ExperienceStore | None = None
    try:
        for legacy in sorted(source_dir.glob("*/experience.db")):
            if not legacy.is_file() or legacy.resolve() == target_path.resolve():
                continue
            rows = _read_all(legacy)
            if not rows:
                continue
            if store is None:
                store = ExperienceStore(target_path)
            for row in rows:
                if store.add(str(row.get("insight") or ""),
                             context=str(row.get("context") or ""),
                             tags=[str(tag) for tag in (row.get("tags") or [])],
                             source_session=str(row.get("source_session") or ""),
                             source_model=str(row.get("source_model") or "")):
                    merged += 1
    finally:
        if store is not None:
            store.close()
    return merged


def _read_all(db_path: Path) -> list[dict[str, Any]]:
    """全量读取一个经验库文件；损坏或没有表一律当空库。"""
    try:
        conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            rows = conn.execute("SELECT * FROM insights").fetchall()
        finally:
            conn.close()
    except (sqlite3.Error, OSError):
        return []
    return [_normalize(tuple(row)) for row in rows]


def _normalize(row: tuple[Any, ...]) -> dict[str, Any]:
    """行 → 字典；tags 从 JSON 串还原为列表（坏数据按空列表处理）。

    老库可能没有合并相关的两列：多退少补，缺的按「没被合并」处理。
    """
    item = dict(zip(_COLUMNS, row, strict=False))
    for name in _COLUMNS:
        item.setdefault(name, [] if name == "merged_from" else "")
    try:
        tags = json.loads(item.get("tags") or "[]")
    except (TypeError, ValueError):
        tags = []
    item["tags"] = [str(tag) for tag in tags] if isinstance(tags, list) else []
    raw_from = item.get("merged_from")
    try:
        merged_from = json.loads(raw_from or "[]") if isinstance(raw_from, str) else []
    except (TypeError, ValueError):
        merged_from = []
    item["merged_from"] = [str(x) for x in merged_from] if isinstance(merged_from, list) else []
    item["merged"] = bool(str(item.get("merged_into") or "").strip())
    return item


def format_insights(items: list[dict[str, Any]], *, max_insight: int = 240,
                    max_context: int = 120, max_source: int = 60) -> list[str]:
    """召回格式：``[标签] 洞察（适用：场景；来源：目标）``——标签帮模型判断同场景。"""
    lines: list[str] = []
    for item in items:
        text = str(item.get("insight") or "").strip()
        if not text:
            continue
        tags = "、".join(str(tag) for tag in (item.get("tags") or [])[:3])
        line = f"[{tags}] {text[:max_insight]}" if tags else text[:max_insight]
        extras: list[str] = []
        context = str(item.get("context") or "").strip()
        if context:
            extras.append(f"适用：{context[:max_context]}")
        source = str(item.get("source_session") or "").strip()
        if source:
            extras.append(f"来源：{source[:max_source]}")
        if extras:
            line += "（" + "；".join(extras) + "）"
        lines.append(line)
    return lines


def _active_clause(conn: sqlite3.Connection) -> str:
    """已合并的条目默认不参与展示与召回；老库没有该列时不做过滤。"""
    return " WHERE COALESCE(merged_into, '') = ''" if _has_column(conn, "merged_into") else ""


def read_recent(db_path: str | Path, *, limit: int = 6) -> dict[str, Any]:
    """只读快照（面板/状态展示用）：不建表、不写盘，缺失或损坏返回空。

    已被二次提炼合并掉的条目不再计入——压缩的意义就是别让同一件事重复出现。
    """
    path = Path(db_path)
    if not path.exists():
        return {"total": 0, "items": []}
    try:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            clause = _active_clause(conn)
            total = conn.execute(
                f"SELECT COUNT(*) FROM insights{clause}").fetchone()[0]
            rows = conn.execute(
                f"SELECT * FROM insights{clause} ORDER BY ts DESC LIMIT ?",
                (max(1, int(limit)),)).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return {"total": 0, "items": []}
    return {"total": int(total), "items": [_normalize(row) for row in rows]}


def read_page(db_path: str | Path, *, q: str = "", tag: str = "",
              limit: int = 50, offset: int = 0,
              include_merged: bool = False) -> dict[str, Any]:
    """经验提炼页数据：过滤分页 + 标签分布/来源统计（只读，坏库返回空态）。

    q 关键词命中 insight/context/tags 任意字段；tag 精确匹配一个标签
    （标签以 JSON 数组存储，LIKE 匹配带引号串避免前缀误命中）。
    include_merged=True 才把「已被二次提炼合并」的原件也列出来（默认只看有效
    经验）；merged_total 恒报被合并的条数，页面据此显示「已合并 N 条」。
    """
    empty: dict[str, Any] = {"total": 0, "items": [], "has_more": False,
                             "tags": [], "sources": 0, "last_ts": None,
                             "merged_total": 0}
    path = Path(db_path)
    if not path.exists():
        return empty
    try:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            has_merge = _has_column(conn, "merged_into")
            where, args = [], []
            if not include_merged and has_merge:
                where.append("COALESCE(merged_into, '') = ''")
            if q.strip():
                where.append("(insight LIKE ? OR context LIKE ? OR tags LIKE ?)")
                like = f"%{q.strip()}%"
                args += [like, like, like]
            if tag.strip():
                where.append("tags LIKE ?")
                args += [f'%"{tag.strip()}"%']
            clause = f" WHERE {' AND '.join(where)}" if where else ""
            total = conn.execute(
                f"SELECT COUNT(*) FROM insights{clause}", args).fetchone()[0]
            rows = conn.execute(
                f"SELECT * FROM insights{clause}"
                " ORDER BY ts DESC LIMIT ? OFFSET ?",
                [*args, max(1, int(limit)), max(0, int(offset))]).fetchall()
            # 标签分布与来源数对「有效经验」全量统计（关键词过滤只作用于列表）
            active = _active_clause(conn)
            tag_rows = conn.execute(
                f"SELECT tags FROM insights{active}").fetchall()
            src_row = conn.execute(
                "SELECT COUNT(DISTINCT source_session), MAX(ts)"
                f" FROM insights{active}").fetchone()
            merged_total = (conn.execute(
                "SELECT COUNT(*) FROM insights"
                " WHERE COALESCE(merged_into, '') <> ''").fetchone()[0]
                if has_merge else 0)
        finally:
            conn.close()
    except sqlite3.Error:
        return empty
    counter: dict[str, int] = {}
    for (raw,) in tag_rows:
        try:
            tags = json.loads(raw or "[]")
        except (TypeError, ValueError):
            tags = []
        if isinstance(tags, list):
            for item in tags:
                counter[str(item)] = counter.get(str(item), 0) + 1
    items = [_normalize(row) for row in rows]
    return {
        "total": int(total), "items": items,
        "merged_total": int(merged_total or 0),
        "has_more": offset + len(items) < int(total),
        "tags": [{"tag": t, "count": c} for t, c in
                 sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))],
        "sources": int(src_row[0] or 0),
        "last_ts": float(src_row[1]) if src_row and src_row[1] else None,
    }


def delete_insight(db_path: str | Path, insight_id: str, *,
                   audit: Any = None) -> dict[str, Any] | None:
    """人工审核删除：按 ID 删一条经验，返回被删快照（未命中返回 None）。

    经验是模型产出、用户随时可审的仓库——提炼跑偏（如把单题解题步骤
    当成可复用事实）时用户可就地清理；删除动作经 audit 留痕（actor=user）。
    库故障（锁/损坏）显式抛出：不能假装「未命中」，让用户以为条目已删。
    """
    path = Path(db_path)
    if not path.exists() or not str(insight_id or "").strip():
        return None
    try:
        conn = sqlite3.connect(str(path))
        try:
            with conn:
                row = conn.execute(
                    "SELECT * FROM insights WHERE insight_id = ?",
                    (insight_id,)).fetchone()
                if row is None:
                    return None
                item = _normalize(row)
                for child in item.get("merged_from") or []:
                    conn.execute(
                        "UPDATE insights SET merged_into = '' WHERE insight_id = ?",
                        (str(child),))
                conn.execute("DELETE FROM insights WHERE insight_id = ?",
                             (insight_id,))
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise SpiritScoutError(
            f"经验库操作失败（{type(exc).__name__}）: {str(exc)[:200]}") from exc
    item = _normalize(row)
    if audit is not None:
        audit.log("experience.deleted", "user", {
            "insight_id": insight_id,
            "insight": str(item.get("insight") or "")[:200]})
    return item


class ExperienceStore:
    """全局经验库：写入（灵枢提炼）+ 检索（智能体查询）。"""

    def __init__(self, db_path: str | Path, *, audit=None):
        self.db_path = str(db_path)
        self.audit = audit or NullAuditLogger()
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute("""CREATE TABLE IF NOT EXISTS insights (
            insight_id TEXT PRIMARY KEY,
            insight TEXT NOT NULL,
            context TEXT DEFAULT '',
            tags TEXT DEFAULT '[]',
            source_session TEXT DEFAULT '',
            source_model TEXT DEFAULT '',
            ts REAL NOT NULL
        )""")
        _ensure_columns(self._conn)      # 老库补 merged_into / merged_from
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_insights_ts ON insights(ts DESC)")
        self._conn.commit()

    def add(self, insight: str, *, context: str = "",
            tags: list[str] | None = None,
            source_session: str = "", source_model: str = "") -> str:
        """写入一条经验；完全重复的洞察直接跳过（返回空串）。"""
        text = insight.strip()[:_INSIGHT_CAP]
        if not text:
            return ""
        dup = self._conn.execute(
            "SELECT insight_id FROM insights WHERE insight = ? LIMIT 1",
            (text,)).fetchone()
        if dup:
            self.audit.log("experience.duplicate", "master", {
                "insight_id": dup[0], "insight": text[:200]})
            return ""
        eid = new_id("exp")
        self._conn.execute(
            "INSERT OR IGNORE INTO insights (insight_id, insight, context, tags,"
            " source_session, source_model, ts) VALUES (?,?,?,?,?,?,?)",
            (eid, text, context.strip()[:_CONTEXT_CAP],
             json.dumps([str(tag) for tag in (tags or [])][:8], ensure_ascii=False),
             source_session[:200], source_model, time.time()))
        self._conn.commit()
        self.audit.log("experience.added", "master", {
            "insight_id": eid, "insight": text[:200]})
        return eid

    def search(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        """关键词检索（简化版 FTS：LIKE 匹配 context + insight + tags）。"""
        q = f"%{query.strip()}%"
        rows = self._conn.execute(
            "SELECT * FROM insights WHERE COALESCE(merged_into, '') = '' AND ("
            "insight LIKE ? OR context LIKE ? OR tags LIKE ?)"
            " ORDER BY ts DESC LIMIT ?",
            (q, q, q, limit)).fetchall()
        return [_normalize(row) for row in rows]

    def recent(self, *, limit: int = 10) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM insights WHERE COALESCE(merged_into, '') = ''"
            " ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
        return [_normalize(row) for row in rows]

    def count(self, *, include_merged: bool = False) -> int:
        clause = "" if include_merged else " WHERE COALESCE(merged_into, '') = ''"
        return int(self._conn.execute(
            f"SELECT COUNT(*) FROM insights{clause}").fetchone()[0])

    def close(self):
        self._conn.close()

# ---------------------------------------------------------------- 二次提炼（合并）

def _load_conn(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    _ensure_columns(conn)
    return conn


def _row(conn: sqlite3.Connection, insight_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM insights WHERE insight_id = ?",
                       (insight_id,)).fetchone()
    return _normalize(row) if row else None


def merge_candidates(db_path: str | Path, *,
                     threshold: float = merge_mod.DEFAULT_THRESHOLD,
                     limit: int = 20) -> list[dict[str, Any]]:
    """给出可以合并的组（整组两两相似度都达标才算）。

    只读、不建库：库不存在或坏掉时返回空列表，页面按「没有可合并项」处理。
    """
    path = Path(db_path)
    if not path.exists():
        return []
    try:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            rows = [_normalize(row) for row in conn.execute(
                "SELECT * FROM insights").fetchall()]
        finally:
            conn.close()
    except sqlite3.Error:
        return []
    groups = merge_mod.build_groups(rows, threshold=threshold, limit=limit)
    out: list[dict[str, Any]] = []
    for group in groups:
        items = group["items"]
        out.append({
            "ids": [str(item.get("insight_id") or "") for item in items],
            "score": group["score"],
            "items": [{"insight_id": str(item.get("insight_id") or ""),
                       "insight": str(item.get("insight") or ""),
                       "tags": list(item.get("tags") or [])} for item in items],
            "preview": group["preview"],
        })
    return out


def merge_insights(db_path: str | Path, ids: list[str], *, audit: Any = None,
                   threshold: float = merge_mod.DEFAULT_THRESHOLD
                   ) -> dict[str, Any]:
    """把 ids 合并成一条新经验，并把原件标记为「已合并」——原件不删。

    服务端自己再比一次相似度：前端传什么都要复检，避免把不相干的条目压掉。
    冲突（条目不存在 / 已被合并 / 相似度不足）一律显式报错，不动库。
    """
    wanted: list[str] = []
    for raw in ids or []:
        key = str(raw or "").strip()
        if key and key not in wanted:
            wanted.append(key)
    if len(wanted) < 2:
        raise SpiritScoutError("二次提炼至少要选两条经验")
    path = Path(db_path)
    if not path.exists():
        raise SpiritScoutError("经验库还不存在，没有可合并的条目")
    conn = _load_conn(path)
    try:
        rows: list[dict[str, Any]] = []
        for key in wanted:
            row = _row(conn, key)
            if row is None:
                raise SpiritScoutError(f"经验不存在: {key}")
            if str(row.get("merged_into") or "").strip():
                raise SpiritScoutError(f"这条经验已经合并过: {key}")
            rows.append(row)
        low = min(merge_mod.similarity(str(a.get("insight") or ""),
                                       str(b.get("insight") or ""))
                  for index, a in enumerate(rows) for b in rows[index + 1:])
        if low < float(threshold):
            raise SpiritScoutError(
                f"这几条不够相似（最低 {low:.2f} < 阈值 {float(threshold):.2f}），"
                "为免丢掉有用信息，不合并")
        composed = merge_mod.compose(rows)
        merged_id = new_id("exp")
        with conn:
            conn.execute(
                "INSERT INTO insights (insight_id, insight, context, tags,"
                " source_session, source_model, ts, merged_from)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (merged_id, composed["insight"], composed["context"],
                 json.dumps(composed["tags"], ensure_ascii=False),
                 composed["source_session"], "merge", time.time(),
                 json.dumps(composed["merged_from"], ensure_ascii=False)))
            conn.executemany(
                "UPDATE insights SET merged_into = ? WHERE insight_id = ?",
                [(merged_id, key) for key in wanted])
    except sqlite3.Error as exc:
        raise SpiritScoutError(
            f"经验库操作失败（{type(exc).__name__}）: {str(exc)[:200]}") from exc
    finally:
        conn.close()
    if audit is not None:
        audit.log("experience.merged", "user", {
            "merged_id": merged_id, "absorbed": len(wanted),
            "insight": composed["insight"][:200]})
    return {"merged_id": merged_id, "absorbed": wanted,
            "insight": composed["insight"], "context": composed["context"],
            "tags": composed["tags"]}


def restore_merge(db_path: str | Path, merged_id: str, *,
                  audit: Any = None) -> dict[str, Any] | None:
    """还原一次合并：原件全部解封，派生的合并条目移除（它随时可再生）。"""
    path = Path(db_path)
    if not path.exists() or not str(merged_id or "").strip():
        return None
    conn = _load_conn(path)
    try:
        parent = _row(conn, str(merged_id))
        if parent is None or not parent.get("merged_from"):
            return None
        children = [str(key) for key in parent["merged_from"]]
        with conn:
            conn.executemany(
                "UPDATE insights SET merged_into = '' WHERE insight_id = ?",
                [(key,) for key in children])
            conn.execute("DELETE FROM insights WHERE insight_id = ?", (str(merged_id),))
    except sqlite3.Error as exc:
        raise SpiritScoutError(
            f"经验库操作失败（{type(exc).__name__}）: {str(exc)[:200]}") from exc
    finally:
        conn.close()
    if audit is not None:
        audit.log("experience.merge_restored", "user", {
            "merged_id": str(merged_id), "restored": len(children)})
    return {"merged_id": str(merged_id), "restored": children}
