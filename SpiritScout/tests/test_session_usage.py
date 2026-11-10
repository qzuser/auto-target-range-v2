"""会话用量的归属口径：会话账本 + 共享账本里属于本会话的调用。

回归背景：运行期的逐笔记录大多落在工作区共享账本，会话页只读
`sessions/<id>/usage.db`，于是同一场任务在用量页是几百万 token、在会话页只有
几百。这里钉住三件事：按审计 `call_id` 归属、合并后重算总量、审计增量扫描。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from spiritscout.web.session_usage import (
    audit_call_ids,
    merge_usage,
    session_usage,
    workspace_root,
)


def snapshot(rows: list[dict], *, used_tokens: int | None = None, mode: str = "ctf") -> dict:
    """造一份和 `read_usage` 同形状的快照（缺省字段按账本口径补齐）。"""
    total = sum(int(r.get("tokens") or 0) for r in rows)
    per_model: dict[str, int] = {}
    per_mode: dict[str, int] = {}
    for row in rows:
        per_model[row["model"]] = per_model.get(row["model"], 0) + int(row.get("tokens") or 0)
        per_mode[mode] = per_mode.get(mode, 0) + int(row.get("tokens") or 0)
    return {
        "used_tokens": total if used_tokens is None else used_tokens,
        "used_usd": 0.0,
        "calls": len(rows),
        "per_model_tokens": per_model,
        "per_mode_tokens": per_mode,
        "mode": mode,
        "call_series": rows,
    }


def call(call_id: str, tokens: int, model: str = "deepseek-v4.1-flash", **extra) -> dict:
    row = {"call_id": call_id, "ts": 1_700_000_000.0, "tokens": tokens,
           "input_tokens": tokens - 10, "output_tokens": 10, "model": model,
           "cached_input_tokens": max(0, tokens - 60),   # cache_summary 只统计带该字段的行
           "mode": "ctf", "cost_usd": 0.0}
    row.update(extra)
    return row


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def write_audit(path: Path, call_ids: list[str], *, kind: str = "model.call") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        for call_id in call_ids:
            stream.write(json.dumps({"type": kind, "actor": "ctf-misc-1",
                                     "detail": {"call_id": call_id, "tokens": 1}}) + "\n")


class MergeUsageTests(unittest.TestCase):
    def test_dedupes_by_call_id_and_recomputes(self):
        local = snapshot([call("c1", 100)], used_tokens=100)
        merged = merge_usage(local, [call("c1", 100), call("c2", 250, model="m2")])
        self.assertEqual(len(merged["call_series"]), 2)
        self.assertEqual(merged["used_tokens"], 350)
        self.assertEqual(merged["calls"], 2)
        self.assertEqual(merged["per_model_tokens"]["m2"], 250)
        self.assertEqual(merged["cache"]["measured_calls"], 2)

    def test_does_not_mutate_inputs(self):
        local = snapshot([call("c1", 100)])
        before = list(local["call_series"])
        merge_usage(local, [call("c2", 50)])
        self.assertEqual(local["call_series"], before)
        self.assertEqual(local["used_tokens"], 100)

    def test_no_extra_returns_same_totals(self):
        local = snapshot([call("c1", 100)])
        merged = merge_usage(local, [])
        self.assertEqual(merged["used_tokens"], 100)
        self.assertEqual(len(merged["call_series"]), 1)


class AuditCallIdTests(unittest.TestCase):
    def test_reads_ids_and_follows_appends(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit = Path(tmp) / "audit.jsonl"
            write_audit(audit, ["a1", "a2"])
            self.assertEqual(audit_call_ids(audit), {"a1", "a2"})
            write_audit(audit, ["a3"])
            self.assertEqual(audit_call_ids(audit), {"a1", "a2", "a3"})

    def test_collects_failed_and_cancelled(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit = Path(tmp) / "audit.jsonl"
            write_audit(audit, ["f1"], kind="model.failed")
            write_audit(audit, ["c1"], kind="model.cancelled")
            self.assertEqual(audit_call_ids(audit), {"f1", "c1"})

    def test_half_line_is_not_consumed(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit = Path(tmp) / "audit.jsonl"
            write_audit(audit, ["a1"])
            with audit.open("a", encoding="utf-8") as stream:
                stream.write('{"type": "model.call", "detail": {"call_id": "a2"')
            self.assertEqual(audit_call_ids(audit), {"a1"})
            with audit.open("a", encoding="utf-8") as stream:
                stream.write('}}\n')
            self.assertEqual(audit_call_ids(audit), {"a1", "a2"})

    def test_missing_file_is_empty(self):
        self.assertEqual(audit_call_ids(Path("definitely-missing") / "audit.jsonl"), set())


class SessionUsageTests(unittest.TestCase):
    def test_merges_shared_ledger_rows_into_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "sessions" / "sess-1"
            write_json(workspace / "usage.json", snapshot([call("c1", 100)]))
            write_json(root / "usage.json",
                       snapshot([call("c1", 100), call("c2", 900), call("other", 5000)]))
            write_audit(workspace / "audit.jsonl", ["c1", "c2"])
            usage = session_usage(workspace, workspace / "audit.jsonl")
            self.assertEqual(usage["used_tokens"], 1000)      # other 不属于本会话
            self.assertEqual(len(usage["call_series"]), 2)
            self.assertEqual(usage["shared_calls"], 2)        # c1、c2 都在共享账本里
            self.assertEqual(usage["merged_calls"], 1)        # c1 已在会话账本里，只并入 c2

    def test_falls_back_to_summary_when_ledger_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "sessions" / "sess-2"
            workspace.mkdir(parents=True)
            write_json(root / "usage.json", snapshot([call("x1", 400)]))
            write_audit(workspace / "audit.jsonl", ["x1"])
            usage = session_usage(workspace, workspace / "audit.jsonl",
                                  fallback=snapshot([call("x1", 400)]))
            self.assertEqual(usage["used_tokens"], 400)

    def test_unknown_workspace_returns_local_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "loose"
            write_json(workspace / "usage.json", snapshot([call("c1", 70)]))
            usage = session_usage(workspace, workspace / "audit.jsonl")
            self.assertEqual(usage["used_tokens"], 70)

    def test_workspace_root_hint(self):
        self.assertEqual(workspace_root(Path("/w/sessions/s1")), Path("/w"))
        self.assertIsNone(workspace_root(Path("/w/s1")))


if __name__ == "__main__":
    unittest.main()
