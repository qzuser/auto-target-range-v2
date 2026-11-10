"""经验库的跨机器同步：导出成仓库里一个可 review 的 JSON，推/拉都走 git。

本地经验库是 SQLite（`experience.db`，不入 Git、不进仓库），要跨机器共享就只有
两条路：把库文件本身推上去（二进制、没法 review、容易冲突），或者把它导出成
一份文本清单放进仓库。这里选后者：仓库里的 `experience-export/` 就是那个公共
目录（`experience-insights.json` 是基线快照，`inbox/` 收所有人的提交）。

四条硬约束：

- **拉取只增不改不删**：本地已经有的（同样的内容指纹）原样保留，只补缺的。
- **导出跳过老数据的「已合并原件」**：那些是被提炼过的副本，导出没有意义。
- **导出先脱敏**：链接、IP:端口、flag 花括号字面量、常见密钥形态一律替换掉，
  经验要能公开，凭据和题目答案不能跟着走。
- **推拉都走本机 git**：复用仓库已有的 remote 与凭据，不在这里另存 token。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any

from spiritscout.core.exceptions import SpiritScoutError
from spiritscout.core.ids import new_id
from spiritscout.knowledge.absorb import MAX_INSIGHT
from spiritscout.knowledge.experience import _load_conn

FORMAT = "spiritscout.experience/v1"
# 仓库里既有的经验公共目录：主清单 + 每人一个提交文件
DEFAULT_SYNC_PATH = "experience-export/experience-insights.json"
DEFAULT_INBOX = "experience-export/inbox"
DEFAULT_BRANCH = "main"
MAX_ITEMS = 20000
_KEEP = re.compile(r"[^0-9a-z\u3400-\u4dbf\u4e00-\u9fff]+")
# 脱敏：与根目录 `experience-export/export_experience.py` 同一套标记，两个工具
# 写出来的快照口径一致，人在 diff 里看到的是同一种占位符
_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"https?://\S+"), "[目标地址已脱敏]"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d{1,5})?\b"), "[IP已脱敏]"),
    (re.compile(r"\b(?:sk|ghp|gho|xox[bp])[-_][A-Za-z0-9_\-]{8,}"), "[密钥已脱敏]"),
    (re.compile(r"[A-Za-z0-9_]{2,20}\{[^{}\s]{4,200}\}"), "[flag值已脱敏]"),
)


def redact(text: str) -> str:
    """抹掉会跟着经验一起公开的敏感字面量（链接、主机、密钥、flag）。"""
    out = str(text or "")
    for pattern, repl in _REDACTIONS:
        out = pattern.sub(repl, out)
    return out


def project_root() -> Path:
    """包所在的 git 仓库根目录。

    仓库布局不一定「包就在根上」——本项目把包放在 `SpiritScout/` 子目录里，
    `experience-export/` 却在仓库根。所以从本文件往上找 `.git`（目录或 worktree
    文件），找不到才退回按包深度估算的位置。
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ".git").exists():
            return parent
    return here.parents[3]


def fingerprint(text: str) -> str:
    """内容指纹：只留字与数字，去掉标点空白，再取 sha1。

    经验是同一条事实的不同措辞时，标点/空行差异不该被当成两条；
    但改写过的说法仍然算两条——去重只求稳，不求聪明。
    """
    flat = _KEEP.sub("", str(text or "").lower())
    return hashlib.sha1(flat.encode("utf-8")).hexdigest()[:16]


def _row_payload(row: dict[str, Any]) -> dict[str, Any]:
    insight = redact(str(row.get("insight") or "")[:MAX_INSIGHT])
    return {
        "insight_id": str(row.get("insight_id") or ""),
        "insight": insight,
        "context": redact(str(row.get("context") or "")[:600]),
        "tags": [str(t) for t in (row.get("tags") or []) if str(t).strip()][:24],
        "source_model": str(row.get("source_model") or ""),
        "ts": float(row.get("ts") or 0.0),
        "merged_from": [str(x) for x in (row.get("merged_from") or [])],
        "absorbed_from": [str(x) for x in (row.get("absorbed_from") or [])],
        "fp": fingerprint(insight),
    }


def export_payload(db_path: str | Path) -> dict[str, Any]:
    """把本地经验导成同步载荷（只读，不建库）。"""
    path = Path(db_path)
    if not path.exists():
        return {"format": FORMAT, "exported_at": time.time(), "count": 0, "items": []}
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        try:
            rows = conn.execute(
                "SELECT * FROM insights WHERE COALESCE(merged_into, '') = ''"
                " ORDER BY ts ASC").fetchall()
        except sqlite3.OperationalError:
            # 很老的库没有 merged_into 列：没有「已合并原件」这回事，全导
            rows = conn.execute("SELECT * FROM insights ORDER BY ts ASC").fetchall()
        names = [d[0] for d in conn.execute("SELECT * FROM insights LIMIT 0").description]
    except sqlite3.Error as exc:
        raise SpiritScoutError(f"经验库读取失败: {exc}") from exc
    finally:
        conn.close()
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rows:
        row = dict(zip(names, raw, strict=False))
        tags = row.get("tags")
        merged = row.get("merged_from")
        absorbed = row.get("absorbed_from")
        row["tags"] = _json_list(tags)
        row["merged_from"] = _json_list(merged)
        row["absorbed_from"] = _json_list(absorbed)
        item = _row_payload(row)
        if not item["insight"].strip() or item["fp"] in seen:
            continue
        seen.add(item["fp"])
        items.append(item)
        if len(items) >= MAX_ITEMS:
            break
    return {"format": FORMAT, "exported_at": time.time(), "count": len(items),
            "items": items}


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            loaded = json.loads(value)
        except ValueError:
            return []
        return loaded if isinstance(loaded, list) else []
    return []


def write_export(target: str | Path, payload: dict[str, Any]) -> Path:
    """把载荷写到目标文件（先写临时文件再替换，避免半截文件进 Git）。"""
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")
    tmp.replace(path)
    return path


def read_export(path: str | Path) -> dict[str, Any]:
    """读一个同步文件（认本模块格式，也认仓库里既有的老清单格式）。"""
    file = Path(path)
    if not file.is_file():
        raise SpiritScoutError(f"同步文件不存在: {file}")
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise SpiritScoutError(f"同步文件读取失败: {exc}") from exc
    payload = _as_payload(raw)
    if payload is None:
        raise SpiritScoutError(
            f"同步文件格式不认识（要 {FORMAT} 或 spiritscout-experience-insights），"
            "为免写坏库，已停止导入")
    return payload


def merge_payload(db_path: str | Path, payload: dict[str, Any], *,
                  audit: Any = None) -> dict[str, Any]:
    """把同步载荷并进本地库：**只补缺，不改不删**。

    同一内容（指纹相同）就算本地已有：这条跳过；本地比远端多了「适用场景」
    或标签时也不覆盖——远端只负责把缺的经验带过来。
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = _load_conn(path)
    added = updated = skipped = 0
    try:
        before = int(conn.execute("SELECT COUNT(*) FROM insights").fetchone()[0])
        # 比指纹前先过一遍脱敏：远端存的是脱敏后的文字（链接→<url>），本地原文
        # 带链接时两边不一致，会白import一份重复；按同一个口径算就一致了。
        local_fp: dict[str, str] = {}
        for insight_id, insight in conn.execute(
                "SELECT insight_id, insight FROM insights"):
            local_fp[fingerprint(redact(insight))] = str(insight_id)
        known_ids = {str(row[0]) for row in conn.execute("SELECT insight_id FROM insights")}
        with conn:
            for raw in payload.get("items") or []:
                if not isinstance(raw, dict):
                    continue
                insight = str(raw.get("insight") or "").strip()[:MAX_INSIGHT]
                if not insight:
                    continue
                fp = fingerprint(redact(insight))
                hit = local_fp.get(fp)
                if hit:
                    skipped += 1
                    continue
                insight_id = str(raw.get("insight_id") or "").strip()
                if not insight_id or insight_id in known_ids:
                    insight_id = new_id("exp")
                known_ids.add(insight_id)
                local_fp[fp] = insight_id
                conn.execute(
                    "INSERT INTO insights (insight_id, insight, context, tags,"
                    " source_session, source_model, ts, merged_from, absorbed_from)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (insight_id, insight, str(raw.get("context") or "")[:600],
                     json.dumps([str(t) for t in (raw.get("tags") or [])][:24],
                                ensure_ascii=False),
                     "", str(raw.get("source_model") or "")[:80],
                     float(raw.get("ts") or time.time()),
                     json.dumps([str(x) for x in (raw.get("merged_from") or [])]),
                     json.dumps([str(x) for x in (raw.get("absorbed_from") or [])])))
                added += 1
        after = int(conn.execute("SELECT COUNT(*) FROM insights").fetchone()[0])
        if after != before + added:
            raise SpiritScoutError(
                f"导入前后条数对不上（{before} + {added} ≠ {after}），已回滚")
    except sqlite3.Error as exc:
        raise SpiritScoutError(
            f"经验库写入失败（{type(exc).__name__}）: {str(exc)[:200]}") from exc
    finally:
        conn.close()
    if audit is not None:
        audit.log("experience.sync.pull", "user", {
            "added": added, "skipped": skipped, "updated": updated})
    return {"added": added, "updated": updated, "skipped": skipped,
            "total": after}


# ---------------------------------------------------------------- git 侧

def _git(repo: Path, *args: str, timeout: float = 120.0) -> subprocess.CompletedProcess:
    # core.quotepath=false：提交人名字里有中文时，git 默认会把路径转成 \346\235...
    # 的转义形式，后面拿路径去 `git show` 就对不上了。
    return subprocess.run(["git", "-C", str(repo), "-c", "core.quotepath=false", *args],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)


def _git_ok(result: subprocess.CompletedProcess, what: str) -> str:
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        raise SpiritScoutError(f"{what}失败: {detail[-1][:300] if detail else result.returncode}")
    return result.stdout.strip()


def repo_path(repo: str = "") -> Path:
    """同步用的 git 仓库目录；留空就用项目根目录。"""
    root = Path(repo).expanduser() if str(repo).strip() else project_root()
    if not (root / ".git").exists():
        raise SpiritScoutError(f"{root} 不是 git 仓库，没法同步经验")
    return root


def submit(db_path: str | Path, *, repo: str = "", inbox: str = DEFAULT_INBOX,
           branch: str = DEFAULT_BRANCH, message: str = "", user: str = "",
           audit: Any = None) -> dict[str, Any]:
    """提交：把本地经验导出成**自己的一个文件**放进仓库，提交并推送。

    为什么不直接改主清单 `insights.json`：那个文件是大家的公共快照，谁提交都改
    它会一路冲突。这里改成「每人每次提交写自己一个文件」（`inbox/<提交人>-<时间戳>.json`），
    于是**谁都能提交**——同一个目录里各写各的，不用先拉最新的、也不会覆盖别人的。
    拉取侧把这些文件全部读进来按内容指纹去重即可。
    """
    root = repo_path(repo)
    rel_dir = inbox.replace("\\", "/").strip("/")
    who = _slug(user.strip() or _git_user(root) or _fallback_user())
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    payload = export_payload(db_path)
    rel = f"{rel_dir}/{who}-{stamp}.json"
    target = root / rel
    suffix = 1
    while target.exists():                       # 同一秒提交两次也不覆盖
        suffix += 1
        rel = f"{rel_dir}/{who}-{stamp}-{suffix}.json"
        target = root / rel
    write_export(target, payload)
    _git_ok(_git(root, "add", "--", rel), "git add ")
    text = message.strip() or f"chore(experience): {who} 提交 {payload['count']} 条经验（{stamp}）"
    _git_ok(_git(root, "commit", "-m", text, "--", rel), "git commit ")
    push_out = _git(root, "push", "origin", f"HEAD:{branch}", timeout=300.0)
    if push_out.returncode != 0:
        detail = (push_out.stderr or push_out.stdout or "").strip().splitlines()
        raise SpiritScoutError(
            "推送失败: " + (detail[-1][:300] if detail else str(push_out.returncode))
            + "（没有写入权限时可以 fork 后往自己的分支提交，再提单合并）")
    if audit is not None:
        audit.log("experience.sync.submit", "user",
                  {"count": payload["count"], "file": rel, "branch": branch, "who": who})
    return {"submitted": True, "committed": True, "count": payload["count"],
            "file": rel, "path": str(target), "who": who, "branch": branch,
            "output": (push_out.stdout or "").strip()[-500:]}


def _git_user(root: Path) -> str:
    result = _git(root, "config", "user.name")
    return result.stdout.strip() if result.returncode == 0 else ""


def _fallback_user() -> str:
    return os.environ.get("USERNAME") or os.environ.get("USER") or "anonymous"


def _slug(value: str) -> str:
    """提交人名字改成文件名安全的形式：中文/空格都换掉，保留可读性。"""
    cleaned = re.sub(r"[^0-9A-Za-z_\u4e00-\u9fff-]+", "-", str(value or "")).strip("-")
    return (cleaned or "anonymous")[:40]


def _as_payload(raw: Any) -> dict[str, Any] | None:
    """认得两种格式：本模块的 `spiritscout.experience/v1`，和仓库里既有的
    `spiritscout-experience-insights`（根目录 `experience-export/` 那份老清单）。"""
    if not isinstance(raw, dict):
        return None
    if str(raw.get("format") or "") == FORMAT:
        return raw if isinstance(raw.get("items"), list) else None
    if str(raw.get("kind") or "") == "spiritscout-experience-insights":
        items: list[dict[str, Any]] = []
        for entry in raw.get("insights") or []:
            if not isinstance(entry, dict):
                continue
            insight = str(entry.get("insight") or "").strip()
            if not insight:
                continue
            items.append({
                "insight_id": str(entry.get("id") or ""),
                "insight": insight,
                "context": str(entry.get("context") or ""),
                "tags": [str(t) for t in (entry.get("tags") or [])],
                "source_model": str(entry.get("source_model") or ""),
                "ts": _epoch(entry.get("captured_at")),
                "fp": fingerprint(redact(insight)),
            })
        return {"format": FORMAT, "items": items, "count": len(items),
                "exported_at": _epoch(raw.get("generated_at"))}
    return None


def _epoch(value: Any) -> float:
    """ISO 时间串 → Unix 秒；认不出来就按当前时间（老清单里没有秒级时间）。"""
    text = str(value or "").strip()
    if not text:
        return time.time()
    try:
        from datetime import datetime

        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return time.time()


def _remote_payloads(repo: str = "", *, sync_path: str = DEFAULT_SYNC_PATH,
                     inbox: str = DEFAULT_INBOX,
                     branch: str = DEFAULT_BRANCH) -> dict[str, Any]:
    """把远端的主清单与 inbox 里所有文件读出来，逐个解析（读不到就跳过，不炸）。"""
    root = repo_path(repo)
    main_rel = sync_path.replace("\\", "/").strip("/")
    inbox_rel = inbox.replace("\\", "/").strip("/")
    _git_ok(_git(root, "fetch", "--quiet", "origin", branch), "git fetch ")
    listed = _git(root, "ls-tree", "-r", "--name-only", "FETCH_HEAD", "--",
                  main_rel, inbox_rel)
    paths = [line.strip() for line in (listed.stdout or "").splitlines() if line.strip()]
    payloads: list[dict[str, Any]] = []
    sources: list[str] = []
    for rel in paths:
        if not rel.endswith(".json"):
            continue
        shown = _git(root, "show", f"FETCH_HEAD:{rel}")
        if shown.returncode != 0:
            continue
        try:
            raw = json.loads(shown.stdout)
        except ValueError:
            continue
        payload = _as_payload(raw)
        if payload is None:
            continue
        payloads.append(payload)
        sources.append(rel)
    return {"payloads": payloads, "sources": sources,
            "main_path": main_rel, "inbox": inbox_rel, "branch": branch}


def pull(db_path: str | Path, *, repo: str = "", sync_path: str = DEFAULT_SYNC_PATH,
         inbox: str = DEFAULT_INBOX, branch: str = DEFAULT_BRANCH,
         audit: Any = None) -> dict[str, Any]:
    """从远端拉经验并并进本地库：主清单 + 所有人提交的 inbox 一起读，只补缺。"""
    remote = _remote_payloads(repo, sync_path=sync_path, inbox=inbox, branch=branch)
    if not remote["payloads"]:
        raise SpiritScoutError(
            f"远端 {branch} 上还没有经验文件（{remote['main_path']} 或 "
            f"{remote['inbox']}/ 都是空的）：先在任意一台机器上点「提交」")
    total_added = total_skipped = total_updated = 0
    for payload in remote["payloads"]:
        result = merge_payload(db_path, payload, audit=None)
        total_added += int(result["added"])
        total_skipped += int(result["skipped"])
        total_updated += int(result["updated"])
    if audit is not None:
        audit.log("experience.sync.pull", "user", {
            "added": total_added, "skipped": total_skipped,
            "files": len(remote["sources"]), "branch": branch})
    return {"added": total_added, "updated": total_updated,
            "skipped": total_skipped, "files": len(remote["sources"]),
            "sources": remote["sources"][-8:], "branch": branch}


__all__ = [
    "DEFAULT_BRANCH", "DEFAULT_INBOX", "DEFAULT_SYNC_PATH", "FORMAT",
    "export_payload", "fingerprint", "merge_payload", "project_root", "pull",
    "read_export", "redact", "repo_path", "submit", "write_export",
]
