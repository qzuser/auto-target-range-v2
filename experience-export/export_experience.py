#!/usr/bin/env python3
"""把运行期经验库导出成仓库跟踪的脱敏快照。

数据源：``SpiritScout/.spiritscout/experience.db`` 的 ``insights`` 表
        （由 ``src/spiritscout/knowledge/experience.py`` 在会话收尾时写入）
产物：  ``experience-export/experience-insights.json``

合并语义：**只增不减**。
- 库里有、快照也有的 id：字段按库里覆盖，位置不动；
- 库里没有、快照里有的 id：原样保留（0.12.9 / 0.23.x 那批历史世代已随运行库
  换代消失，但它们是被提交过的沉淀，不能因为本机重建工作区就被抹掉）；
- 库里新增的 id：按 (captured_at, rowid) 追加到末尾。

内容没变化时不改写文件（``generated_at`` 也不会变），所以每次提交只在真的长出新
经验时才产生 diff。整个脚本只用标准库，钩子可以在任何解释器下直接跑。

退出码：0 = 已同步或无需更新；1 = ``--check`` 发现快照是旧的；2 = 用法/内部错误；
3 = 运行库缺失或读不了（钩子据此放行提交，只提醒）。
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sqlite3
import sys
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / "SpiritScout" / ".spiritscout" / "experience.db"
DEFAULT_OUT = REPO_ROOT / "experience-export" / "experience-insights.json"

SCHEMA = 1
KIND = "spiritscout-experience-insights"
SOURCE = "SpiritScout/.spiritscout/experience.db -> table insights"

# 与首版快照保持一致的脱敏口径（顺序即实际执行顺序）
REDACTION = [
    "http/https 链接",
    "IPv4 与端口",
    "flag 花括号字面量",
    "sk- / ghp_ / xox 形态密钥",
    "靶场主机名归一为 local-range",
]

_URL = re.compile(r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+")
_LOOPBACK = re.compile(r"\b(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])(?::\d{1,5})?")
_IPV4 = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d{1,5})?\b")
_FLAG = re.compile(r"\b[A-Za-z0-9_]{2,24}\{[^{}\s]{1,160}\}")
_SECRET = re.compile(r"\b(?:sk|ghp|xox[bap]|AKIA)[-_A-Za-z0-9]{12,}")

# 脱敏后再用同一批模式反向校验；命中即说明规则有洞，宁可失败也不提交
_LEAK_CHECKS = (_URL, _IPV4, _FLAG, _SECRET)

_LOCK_RETRIES = 5
_LOCK_SLEEP = 0.5


class ExportError(RuntimeError):
    """导出过程中的可预期失败。"""


class SourceUnavailable(ExportError):
    """运行库不存在或读不了。"""


def redact(text: str) -> str:
    """按既定口径脱敏一段文本。"""
    if not text:
        return text
    out = _URL.sub("[目标地址已脱敏]", text)
    out = _FLAG.sub("[flag值已脱敏]", out)
    out = _SECRET.sub("[密钥已脱敏]", out)
    out = _LOOPBACK.sub("local-range", out)
    out = _IPV4.sub("[IP已脱敏]", out)
    return out


def _assert_clean(value: str, *, where: str) -> None:
    for pattern in _LEAK_CHECKS:
        found = pattern.search(value)
        if found:
            raise ExportError(
                f"脱敏后仍命中敏感模式（{where}）：{pattern.pattern[:32]}…"
            )


def parse_tags(raw: Any) -> list[str]:
    """库里 tags 是 JSON 数组字符串；容错处理历史脏数据。"""
    if raw is None:
        return []
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            loaded = json.loads(text)
        except json.JSONDecodeError:
            items = [part for part in re.split(r"[,;、\s]+", text) if part]
        else:
            items = loaded if isinstance(loaded, list) else [loaded]
    else:
        items = [raw]
    return [str(item).strip() for item in items if str(item).strip()]


def iso(ts: Any) -> str:
    """epoch 秒 -> 与首版快照一致的 UTC ISO 时间。"""
    try:
        value = float(ts)
    except (TypeError, ValueError):
        value = 0.0
    return datetime.fromtimestamp(value, tz=UTC).isoformat(timespec="seconds")


def read_db(db_path: Path) -> list[dict[str, Any]]:
    """只读打开运行库，按 rowid 升序取全部条目。"""
    if not db_path.exists():
        raise SourceUnavailable(f"运行库不存在：{db_path}")
    uri = db_path.resolve().as_uri() + "?mode=ro"
    last: Exception | None = None
    for attempt in range(_LOCK_RETRIES):
        try:
            con = sqlite3.connect(uri, uri=True, timeout=2.0)
            try:
                con.row_factory = sqlite3.Row
                rows = con.execute(
                    "select insight_id, insight, context, tags, source_model, ts "
                    "from insights order by rowid"
                ).fetchall()
            finally:
                con.close()
            break
        except sqlite3.OperationalError as exc:  # 库被写锁占用时重试几次
            last = exc
            time.sleep(_LOCK_SLEEP * (attempt + 1))
    else:
        raise SourceUnavailable(f"运行库读不了（{_LOCK_RETRIES} 次重试）：{last}")

    entries: list[dict[str, Any]] = []
    for row in rows:
        entry = {
            "id": str(row["insight_id"]),
            "insight": redact(str(row["insight"] or "").strip()),
            "context": redact(str(row["context"] or "").strip()),
            "tags": [redact(tag) for tag in parse_tags(row["tags"])],
            "source_model": str(row["source_model"] or "").strip(),
            "captured_at": iso(row["ts"]),
        }
        _assert_clean(entry["insight"], where=f"{entry['id']}.insight")
        _assert_clean(entry["context"], where=f"{entry['id']}.context")
        entries.append(entry)
    return entries


def load_snapshot(out_path: Path) -> dict[str, Any]:
    if not out_path.exists():
        return {}
    try:
        return json.loads(out_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ExportError(f"现有快照不是合法 JSON：{out_path}（{exc}）") from exc


def merge(existing: Iterable[dict[str, Any]], fresh: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """历史条目不丢，库里有的覆盖字段，新条目按时间追加。"""
    merged: list[dict[str, Any]] = []
    index: dict[str, int] = {}
    for entry in existing:
        key = str(entry.get("id") or "")
        if not key or key in index:
            continue
        index[key] = len(merged)
        merged.append({k: entry.get(k) for k in
                       ("id", "insight", "context", "tags", "source_model", "captured_at")})
    for entry in fresh:
        key = entry["id"]
        if key in index:
            merged[index[key]] = entry
        else:
            index[key] = len(merged)
            merged.append(entry)
    return merged


def tag_frequency(entries: Iterable[dict[str, Any]]) -> dict[str, int]:
    counter = collections.Counter(
        str(tag) for entry in entries for tag in (entry.get("tags") or [])
    )
    ordered = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    return {tag: count for tag, count in ordered}


def build_payload(entries: list[dict[str, Any]], generated_at: str) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "kind": KIND,
        "generated_at": generated_at,
        "source": SOURCE,
        "redaction": list(REDACTION),
        "total": len(entries),
        "tag_frequency": tag_frequency(entries),
        "insights": entries,
    }


def detect_newline(path: Path) -> str:
    """沿用现有文件的换行，避免每次刷新把整份文件的行尾都改一遍。"""
    if path.exists():
        head = path.read_bytes()[:8192]
        if b"\r\n" in head:
            return "\r\n"
        if b"\n" in head:
            return "\n"
    return "\r\n" if sys.platform == "win32" else "\n"


def dump(payload: dict[str, Any], newline: str = "\n") -> str:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if not text.endswith("\n"):
        text += "\n"
    return text if newline == "\n" else text.replace("\n", newline)


def comparable(payload: dict[str, Any]) -> dict[str, Any]:
    """忽略 generated_at 后用于判断「有没有真变化」。"""
    return {k: v for k, v in payload.items() if k != "generated_at"}


# ---- 回灌：把留档快照写回运行库 ---------------------------------------------
# 快照是脱敏留档，运行时读的是 experience.db 的 insights 表，两者不会自动同步：
# 换机器、重建工作区、或者库被清空之后，「经验库」页就是空的——明明仓库里躺着条目。
# --import 负责把留档灌回运行库。去重看两条：insight_id 主键、以及 insight 原文，
# 所以同一句话即使换了 id 也不会进第二行；重复执行无副作用。
_INSIGHT_CAP = 600
_CONTEXT_CAP = 300

_TABLE_DDL = """CREATE TABLE IF NOT EXISTS insights (
    insight_id TEXT PRIMARY KEY,
    insight TEXT NOT NULL,
    context TEXT DEFAULT '',
    tags TEXT DEFAULT '[]',
    source_session TEXT DEFAULT '',
    source_model TEXT DEFAULT '',
    ts REAL NOT NULL
)"""


def _iso_to_ts(value: Any) -> float:
    """ISO 时间串转 epoch 秒；解析不了就退成现在，不让一条脏数据挡住整批。"""
    text = str(value or "").strip()
    if not text:
        return time.time()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return time.time()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """按 knowledge/experience.py 的口径建表，并补齐合并溯源两列。"""
    conn.execute(_TABLE_DDL)
    have = {row[1] for row in conn.execute("PRAGMA table_info(insights)")}
    for name, ddl in (("merged_into", "TEXT DEFAULT ''"),
                      ("merged_from", "TEXT DEFAULT '[]'")):
        if name not in have:
            conn.execute(f"ALTER TABLE insights ADD COLUMN {name} {ddl}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_insights_ts ON insights(ts DESC)")
    conn.commit()


def import_snapshot(db_path: Path, out_path: Path, *, dry_run: bool = False) -> int:
    """把快照写回运行库，返回退出码。只增不改：库里已有的条目原样保留。"""
    snapshot = load_snapshot(out_path)
    if snapshot.get("kind") != KIND:
        raise ExportError(f"快照类型不符：{snapshot.get('kind')!r}")
    entries = snapshot.get("insights") or []
    if not entries:
        print(f"[跳过] 快照里没有条目：{out_path}")
        return 0

    # 预演不落盘：库还不存在时连上去会顺手建一个空文件，那就不是「只看一眼」了
    if dry_run and not db_path.exists():
        print(f"[回灌]（预演，未写入） 快照 {len(entries)} 条：新增 {len(entries)}、"
              f"跳过 0；库还不存在 —— {db_path}")
        return 0
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # timeout：控制台可能正持有写锁，等一会儿比直接报 locked 好
    conn = sqlite3.connect(str(db_path), timeout=20)
    try:
        _ensure_schema(conn)
        have_ids = {str(row[0]) for row in conn.execute("SELECT insight_id FROM insights")}
        have_text = {str(row[0] or "").strip()
                     for row in conn.execute("SELECT insight FROM insights")}
        added = skipped = 0
        for entry in entries:
            text = str(entry.get("insight") or "").strip()[:_INSIGHT_CAP]
            insight_id = str(entry.get("id") or "")
            if not text or (insight_id and insight_id in have_ids) or text in have_text:
                skipped += 1
                continue
            if dry_run:
                added += 1
                continue
            conn.execute(
                "INSERT OR IGNORE INTO insights"
                " (insight_id, insight, context, tags, source_session,"
                "  source_model, ts) VALUES (?,?,?,?,?,?,?)",
                (insight_id or f"exp-import-{int(time.time() * 1000)}-{added}",
                 text,
                 str(entry.get("context") or "").strip()[:_CONTEXT_CAP],
                 json.dumps([str(tag) for tag in (entry.get("tags") or [])][:8],
                            ensure_ascii=False),
                 str(entry.get("source_session") or ""),
                 str(entry.get("source_model") or ""),
                 _iso_to_ts(entry.get("captured_at"))))
            have_ids.add(insight_id)
            have_text.add(text)
            added += 1
        if not dry_run:
            conn.commit()
        total = conn.execute("SELECT COUNT(*) FROM insights").fetchone()[0]
    finally:
        conn.close()

    mark = "（预演，未写入）" if dry_run else ""
    try:
        where = db_path.relative_to(REPO_ROOT)
    except ValueError:
        where = db_path
    print(f"[回灌]{mark} 快照 {len(entries)} 条：新增 {added}、跳过 {skipped}；"
          f"库内现有 {total} 条 —— {where}")
    return 0


def run(args: argparse.Namespace) -> int:
    db_path = Path(args.db).resolve() if args.db else DEFAULT_DB
    out_path = Path(args.out).resolve() if args.out else DEFAULT_OUT

    if getattr(args, "do_import", False):
        return import_snapshot(db_path, out_path, dry_run=getattr(args, "dry_run", False))

    if args.self_test:
        # 1) 对已提交内容再脱敏一次必须原样不动（幂等 = 没有规则会误伤正文）
        # 2) 用现有条目重跑聚合，total / tag_frequency / 顺序必须逐字一致
        snapshot = load_snapshot(out_path)
        entries = snapshot.get("insights") or []
        drift = 0
        for entry in entries:
            for field in ("insight", "context"):
                value = entry.get(field) or ""
                if redact(value) != value:
                    drift += 1
                    print(f"[差异] {entry.get('id')}.{field} 会被二次改写", file=sys.stderr)
            tags = entry.get("tags") or []
            if [redact(tag) for tag in tags] != tags:
                drift += 1
                print(f"[差异] {entry.get('id')}.tags 会被二次改写", file=sys.stderr)
        rebuilt = build_payload(
            entries, snapshot.get("generated_at") or "1970-01-01T00:00:00+00:00"
        )
        if comparable(rebuilt) != comparable(snapshot):
            drift += 1
            print("[差异] 聚合口径（total / tag_frequency / 顺序）与快照不一致", file=sys.stderr)
        if drift:
            print(f"[失败] 快照自检有 {drift} 处不一致", file=sys.stderr)
            return 2
        print(f"[通过] 快照自检一致（{len(entries)} 条，脱敏幂等 + 聚合一致）")
        return 0

    snapshot = load_snapshot(out_path)
    existed = snapshot.get("insights") or []
    try:
        fresh = read_db(db_path)
    except SourceUnavailable as exc:
        if args.strict:
            print(f"[失败] {exc}", file=sys.stderr)
            return 3
        print(f"[跳过] {exc}", file=sys.stderr)
        return 3

    entries = merge(existed, fresh)
    generated_at = datetime.now(tz=UTC).isoformat(timespec="seconds")
    candidate = build_payload(entries, generated_at)

    if comparable(candidate) == comparable(snapshot):
        if args.check:
            print(f"[最新] 快照已是最新（{candidate['total']} 条，运行库 {len(fresh)} 条）")
            return 0
        print(f"[无变化] 快照已是最新（{candidate['total']} 条，运行库 {len(fresh)} 条）")
        return 0

    added = candidate["total"] - len(existed)
    if args.check:
        print(
            f"[过期] 快照落后：现有 {len(existed)} 条，运行库 {len(fresh)} 条，"
            f"同步后 {candidate['total']} 条（+{added}）",
            file=sys.stderr,
        )
        return 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(dump(candidate, detect_newline(out_path)), encoding="utf-8", newline="")
    print(
        f"[已更新] {out_path.relative_to(REPO_ROOT)}："
        f"{len(existed)} -> {candidate['total']} 条（运行库 {len(fresh)} 条，新增 {added}）"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="导出运行期经验库为仓库跟踪的脱敏快照",
    )
    parser.add_argument("--db", help=f"经验库路径（默认 {DEFAULT_DB}）")
    parser.add_argument("--out", help=f"快照路径（默认 {DEFAULT_OUT}）")
    parser.add_argument("--check", action="store_true", help="只检查快照是否落后，不改文件")
    parser.add_argument("--strict", action="store_true", help="运行库缺失/读不了时按失败处理")
    parser.add_argument("--self-test", action="store_true", help="用现有快照自检导出管线")
    parser.add_argument("--import", dest="do_import", action="store_true",
                        help="反向：把快照写回运行库（换机器/库被清空后补回经验）")
    parser.add_argument("--dry-run", action="store_true",
                        help="配合 --import：只报会新增多少条，不写库")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except ExportError as exc:
        print(f"[失败] {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - 钩子里要能看见任何意外
        print(f"[失败] 未预期错误：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
