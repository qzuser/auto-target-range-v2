"""经验库跨机器同步（提交 / 拉取），以及「提炼 × 合并」撞车时的溯源收口。

要守住的性质：

1. **提交写自己一个文件**：`inbox/<提交人>-<时间戳>.json`，谁都能提、互不覆盖；
2. **拉取只补缺**：本地已有的（同内容指纹）跳过，不覆盖、不删除；
3. **提炼删原件时不留空指针**：被删条目吸收过的溯源搬到提炼结果上，别处指向
   被删 id 的 `absorbed_from` 引用清掉——这就是「二次提炼」和「合并」打架的现场。
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

from spiritscout.core.exceptions import SpiritScoutError
from spiritscout.knowledge import experience as exp
from spiritscout.knowledge import sync


def _store(path: Path) -> exp.ExperienceStore:
    """测试库：关掉入库判重，方便刻意造近义条目。"""
    return exp.ExperienceStore(path, duplicate_threshold=0)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


class FingerprintTests(unittest.TestCase):
    def test_punctuation_and_space_do_not_matter(self) -> None:
        a = sync.fingerprint("登录接口缺错误文案时可能存在用户名枚举")
        b = sync.fingerprint("登录接口缺错误文案时，可能存在用户名枚举。")
        self.assertEqual(a, b)

    def test_different_wording_is_a_different_fingerprint(self) -> None:
        self.assertNotEqual(sync.fingerprint("用 XS-Leak 判跨源状态"),
                            sync.fingerprint("用时间差判断跨源状态"))


class RedactionTests(unittest.TestCase):
    """经验要能公开：链接、主机、密钥、flag 字面量都不能跟着走。"""

    def test_sensitive_literals_are_replaced(self) -> None:
        text = ("在 http://target.local/admin 打点，回连 10.0.0.5:8080，"
                "拿到 ictf{tr4ck_th3_b34c0n} 后写 key=ghp_abcdefgh12345678")
        out = sync.redact(text)
        for leaked in ("http://", "target.local", "10.0.0.5", "ictf{", "ghp_"):
            self.assertNotIn(leaked, out)
        self.assertIn("[目标地址已脱敏]", out)
        self.assertIn("[IP已脱敏]", out)
        self.assertIn("[flag值已脱敏]", out)
        self.assertIn("[密钥已脱敏]", out)

    def test_export_applies_redaction(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            db = Path(tmp.name) / "experience.db"
            store = _store(db)
            store.add("靶场 http://10.1.2.3:8000 的 flag 是 ictf{abc12345}",
                      tags=["web"])
            store.close()
            payload = sync.export_payload(db)
            item = payload["items"][0]
            self.assertNotIn("10.1.2.3", item["insight"])
            self.assertNotIn("ictf{", item["insight"])
        finally:
            tmp.cleanup()


class LegacyFormatTests(unittest.TestCase):
    """目录里既有的 `spiritscout-experience-insights` 快照要能直接拉。"""

    def test_legacy_snapshot_is_readable(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            path = Path(tmp.name) / "experience-insights.json"
            path.write_text(json.dumps({
                "schema": 1, "kind": "spiritscout-experience-insights",
                "generated_at": "2026-11-10T06:05:07+00:00", "total": 1,
                "insights": [{"id": "exp-legacy01",
                              "insight": "退出码为 0 不代表绕过生效",
                              "context": "命令注入", "tags": ["web"],
                              "source_model": "master",
                              "captured_at": "2026-11-10T06:05:07+00:00"}],
            }, ensure_ascii=False), encoding="utf-8")
            payload = sync.read_export(path)
            self.assertEqual(payload["count"], 1)
            self.assertEqual(payload["items"][0]["insight_id"], "exp-legacy01")
            self.assertGreater(payload["items"][0]["ts"], 0)

            db = Path(tmp.name) / "fresh.db"
            _store(db).close()
            self.assertEqual(sync.merge_payload(db, payload)["added"], 1)
        finally:
            tmp.cleanup()


class PayloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "experience.db"
        store = _store(self.db)
        self.keep = store.add("命令退出码为 0 不等于过滤绕过生效", context="Web 命令注入",
                              tags=["web"], source_session="s1")
        self.legacy = store.add("老口径里的已合并原件", tags=["legacy"])
        store.close()
        import sqlite3
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE insights SET merged_into = 'other' WHERE insight_id = ?",
                     (self.legacy,))
        conn.commit()
        conn.close()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_export_skips_legacy_merged_rows(self) -> None:
        payload = sync.export_payload(self.db)
        ids = [item["insight_id"] for item in payload["items"]]
        self.assertEqual(ids, [self.keep])
        self.assertEqual(payload["count"], 1)
        self.assertTrue(payload["items"][0]["fp"])

    def test_roundtrip_file(self) -> None:
        target = sync.write_export(self.root / "out" / "insights.json",
                                   sync.export_payload(self.db))
        again = sync.read_export(target)
        self.assertEqual(again["count"], 1)

    def test_bad_format_is_refused(self) -> None:
        bad = self.root / "bad.json"
        bad.write_text(json.dumps({"format": "nope", "items": []}), encoding="utf-8")
        with self.assertRaises(SpiritScoutError):
            sync.read_export(bad)

    def test_merge_adds_only_missing(self) -> None:
        payload = sync.export_payload(self.db)
        other = self.root / "other.db"
        _store(other).close()
        result = sync.merge_payload(other, payload)
        self.assertEqual(result["added"], 1)

        # 再来一次：同内容指纹 → 跳过，不重复写
        again = sync.merge_payload(other, payload)
        self.assertEqual(again["added"], 0)
        self.assertEqual(again["skipped"], 1)

        payload["items"].append({**payload["items"][0], "insight_id": "exp-dup",
                                 "insight": "命令退出码为0不等于过滤绕过生效。"})
        third = sync.merge_payload(other, payload)
        self.assertEqual(third["added"], 0, "标点差异也算同一条")


class ProjectRootTests(unittest.TestCase):
    """仓库根要认 `.git`，不能按包深度硬猜——本项目的包就在 `SpiritScout/` 子目录里。"""

    def test_finds_git_toplevel_above_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            module = repo / "SpiritScout" / "src" / "spiritscout" / "knowledge" / "sync.py"
            module.parent.mkdir(parents=True)
            module.write_text("", encoding="utf-8")
            (repo / ".git").mkdir()
            real_file = sync.__file__
            try:
                sync.__file__ = str(module)
                self.assertEqual(sync.project_root(), repo.resolve())
            finally:
                sync.__file__ = real_file

    def test_worktree_file_counts_as_git(self) -> None:
        """`git worktree` 的 `.git` 是文件不是目录，也要认。"""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "wt"
            module = repo / "pkg" / "sync.py"
            module.parent.mkdir(parents=True)
            module.write_text("", encoding="utf-8")
            (repo / ".git").write_text("gitdir: /tmp/elsewhere\n", encoding="utf-8")
            real_file = sync.__file__
            try:
                sync.__file__ = str(module)
                self.assertEqual(sync.project_root(), repo.resolve())
            finally:
                sync.__file__ = real_file

    def test_default_paths_live_under_project_root(self) -> None:
        root = sync.project_root()
        self.assertEqual((root / sync.DEFAULT_SYNC_PATH).name, "experience-insights.json")
        self.assertEqual((root / sync.DEFAULT_INBOX).name, "inbox")


class GitSyncTests(unittest.TestCase):
    """真起两个仓库（work + bare origin），跑通 提交 → 拉取。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.origin = base / "origin.git"
        self.work = base / "work"
        subprocess.run(["git", "init", "--bare", "-b", "main", str(self.origin)],
                       capture_output=True, check=True)
        self.work.mkdir()
        for args in (["init", "-b", "main"],
                     ["config", "user.email", "t@example.com"],
                     ["config", "user.name", "测试提交人"]):
            _git(self.work, *args)
        (self.work / "README.md").write_text("seed\n", encoding="utf-8")
        _git(self.work, "add", "README.md")
        _git(self.work, "commit", "-m", "seed")
        _git(self.work, "remote", "add", "origin", str(self.origin))
        _git(self.work, "push", "-u", "origin", "main")

        self.db = base / "local.db"
        store = _store(self.db)
        store.add("coppersmith 的界要按模数的位数算", tags=["crypto"])
        store.close()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_submit_writes_own_file_and_pushes(self) -> None:
        result = sync.submit(self.db, repo=str(self.work), inbox="data/exp/inbox",
                             branch="main", user="张三")
        self.assertTrue(result["submitted"])
        rel = result["file"]
        self.assertTrue(rel.startswith("data/exp/inbox/"))
        self.assertIn("张三", rel)
        shown = _git(self.work, "show", f"HEAD:{rel}")
        self.assertEqual(shown.returncode, 0)
        payload = json.loads(shown.stdout)
        self.assertEqual(payload["count"], 1)
        remote = _git(self.origin, "log", "--oneline", "main")
        self.assertIn("提交", remote.stdout)

    def test_pull_fills_another_database_without_touching_local(self) -> None:
        sync.submit(self.db, repo=str(self.work), inbox="data/exp/inbox",
                    branch="main", user="李四")
        other = Path(self.tmp.name) / "other.db"
        store = _store(other)
        store.add("本地早就有的一条经验，别被覆盖", tags=["local"])
        store.close()

        result = sync.pull(other, repo=str(self.work), inbox="data/exp/inbox",
                           branch="main")
        self.assertEqual(result["added"], 1)
        self.assertGreaterEqual(result["files"], 1)

        again = sync.pull(other, repo=str(self.work), inbox="data/exp/inbox",
                          branch="main")
        self.assertEqual(again["added"], 0)

        conn = __import__("sqlite3").connect(other)
        texts = [row[0] for row in conn.execute("SELECT insight FROM insights")]
        conn.close()
        self.assertEqual(len(texts), 2, "本地原有的那条必须还在")

    def test_pull_without_any_remote_file_says_so(self) -> None:
        with self.assertRaises(SpiritScoutError):
            sync.pull(self.db, repo=str(self.work), inbox="data/exp/inbox",
                      branch="main")

    def _push_foreign(self, text: str, *, who: str) -> str:
        """模拟**别人**在自己机器上提交：直接往远端放他名下的 inbox 文件。"""
        rel = f"data/exp/inbox/{who}-20261110T000000Z.json"
        payload = {
            "format": sync.FORMAT,
            "exported_at": 1762310400.0,
            "count": 1,
            "items": [{
                "insight_id": f"exp-{who}",
                "insight": text,
                "context": "别人的机器",
                "tags": ["shared"],
                "source_model": who,
                "ts": 1762310400.0,
                "fp": sync.fingerprint(sync.redact(text)),
            }],
        }
        path = self.work / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        _git(self.work, "add", "--", rel)
        _git(self.work, "commit", "-m", f"{who} 提交经验")
        _git(self.work, "push", "origin", "main")
        return rel

    def test_pull_takes_every_contributors_inbox(self) -> None:
        """拉取会把 inbox 里**所有人**的文件都读进来，不只看自己那份。"""
        alice = self._push_foreign("别人家在别处攒的经验一", who="alice")
        bob = self._push_foreign("别人家在别处攒的经验二", who="bob")
        fresh = Path(self.tmp.name) / "fresh.db"
        _store(fresh).close()

        result = sync.pull(fresh, repo=str(self.work), inbox="data/exp/inbox",
                           branch="main")
        self.assertEqual(result["added"], 2)
        self.assertEqual(result["files"], 2)
        self.assertIn(alice, result["sources"])
        self.assertIn(bob, result["sources"])

        conn = __import__("sqlite3").connect(fresh)
        texts = sorted(row[0] for row in conn.execute("SELECT insight FROM insights"))
        conn.close()
        self.assertIn("别人家在别处攒的经验一", texts)
        self.assertIn("别人家在别处攒的经验二", texts)


class MergeAbsorbProvenanceTests(unittest.TestCase):
    """二次提炼删原件时，合并留下的溯源不能变成空指针。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "experience.db"
        store = _store(self.db)
        base = "命令退出码 0 不能证明过滤绕过成功，要看带外回连"
        self.a = store.add(base, tags=["web"])
        self.b = store.add(base + "；无回显时以 DNS 回连为准", tags=["web"])
        self.c = store.add(base + "；无回显时以 DNS 回连为准。", tags=["web"])
        store.close()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _connect(self) -> Any:
        import sqlite3
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        return conn

    def test_absorb_then_merge_carries_provenance(self) -> None:
        from spiritscout.knowledge.absorb import apply_absorb

        apply_absorb(self.db, [{
            "target_id": self.b, "sources": [self.a],
            "insight": "命令退出码 0 不能证明过滤绕过成功，要看带外回连；无回显时以 DNS 回连为准"}])
        preview = exp.merge_insights(self.db, [self.b, self.c],
                                     threshold=0.5, confirm=False)
        self.assertIn(self.a, preview["carried_absorbed_from"],
                      "预览要把被删条目吸收过的溯源带出去")
        exp.merge_insights(self.db, [self.b, self.c], threshold=0.5, confirm=True)

        conn = self._connect()
        try:
            rows = {row["insight_id"]: dict(row) for row in
                    conn.execute("SELECT * FROM insights")}
        finally:
            conn.close()
        merged = [row for row in rows.values() if row.get("source_model") == "merge"]
        self.assertEqual(len(merged), 1)
        self.assertNotIn(self.b, rows, "被提炼的原件已删除")
        self.assertNotIn(self.c, rows)
        self.assertIn(self.a, rows, "合并的原件按「合并」的承诺继续留着")
        absorbed = json.loads(merged[0].get("absorbed_from") or "[]")
        self.assertIn(self.a, absorbed, "提炼结果要承接这段溯源")


if __name__ == "__main__":
    unittest.main()
