"""题目身份：同一道题重开不该被清空，换了题必须断干净。

这组测试盯的是三件事：指纹要稳（续聊不算换题）、第一次与同一题都不能动
既有记录、真换题时上一题的关联要清掉且留档可查。
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from spiritscout import taskid  # noqa: E402
from spiritscout.blackboard import Blackboard  # noqa: E402
from spiritscout.core.audit import AuditLogger  # noqa: E402
from spiritscout.core.models import AgentType, BlackboardLayer, RunMode  # noqa: E402
from spiritscout.launch import LaunchRequest, prepare_launch  # noqa: E402

CHALLENGE_A = {"id": "web-01", "title": "登录绕过", "category": "web",
               "url": "http://a.test/"}
CHALLENGE_B = {"id": "web-02", "title": "反序列化", "category": "web",
               "url": "http://b.test/"}


def _plan(challenges=None, mission="一份 ctf 任务，拿 flag"):
    return prepare_launch(LaunchRequest(
        mode=RunMode.CTF, mission=mission,
        challenges_yaml=json.dumps(challenges) if challenges else None))


class FingerprintTests(unittest.TestCase):
    def test_same_plan_gives_same_fingerprint(self) -> None:
        a = taskid.identity_of(_plan([CHALLENGE_A]))
        b = taskid.identity_of(_plan([CHALLENGE_A]))
        self.assertEqual(a.fingerprint, b.fingerprint)

    def test_different_challenge_changes_fingerprint(self) -> None:
        a = taskid.identity_of(_plan([CHALLENGE_A]))
        b = taskid.identity_of(_plan([CHALLENGE_B]))
        self.assertNotEqual(a.fingerprint, b.fingerprint)

    def test_continuation_wording_does_not_change_fingerprint(self) -> None:
        """续聊会改任务原文——不能因此判成换题，否则每聊一句就清一次。"""
        first = taskid.identity_of(_plan([CHALLENGE_A], mission="一份 ctf 任务，拿 flag"))
        later = taskid.identity_of(_plan([CHALLENGE_A], mission="继续，重点看 /admin"))
        self.assertEqual(first.fingerprint, later.fingerprint)

    def test_label_names_the_challenge(self) -> None:
        ident = taskid.identity_of(_plan([CHALLENGE_A]))
        self.assertIn("登录绕过", ident.label)

    def test_multiple_challenges_counted_in_label(self) -> None:
        ident = taskid.identity_of(_plan([CHALLENGE_A, CHALLENGE_B]))
        self.assertIn("2 道题", ident.label)

    def test_challenge_order_does_not_matter(self) -> None:
        a = taskid.identity_of(_plan([CHALLENGE_A, CHALLENGE_B]))
        b = taskid.identity_of(_plan([CHALLENGE_B, CHALLENGE_A]))
        self.assertEqual(a.fingerprint, b.fingerprint)


class MissionTargetTests(unittest.TestCase):
    """续聊里给了新目标，要不要把旧题面丢掉。"""

    def setUp(self) -> None:
        from spiritscout.web.sessions import _switches_challenge

        self.check = _switches_challenge
        self.old = json.dumps([{"id": "a", "title": "A", "url": "http://a.test/"}])

    def test_same_host_subpath_is_same_challenge(self) -> None:
        # "接着看 /admin" 是同一道题的继续，不能因此清掉上一轮的成果
        self.assertFalse(self.check(["http://a.test/admin"], self.old))

    def test_other_host_is_a_new_challenge(self) -> None:
        self.assertTrue(self.check(["http://b.test/"], self.old))

    def test_old_challenge_without_url_cannot_be_matched(self) -> None:
        no_url = json.dumps([{"id": "a", "title": "A"}])
        self.assertTrue(self.check(["http://b.test/"], no_url))

    def test_broken_yaml_treated_as_new_challenge(self) -> None:
        self.assertTrue(self.check(["http://b.test/"], "not: [valid"))


class SwitchTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.bb_path = root / "blackboard.db"
        self.workspace = root
        self.audit = AuditLogger(root / "audit.jsonl")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _seed(self) -> None:
        """在每一层都放一条"上一题"的事实，外加一条用户原话。"""
        bb = Blackboard(self.bb_path)
        try:
            bb.write(BlackboardLayer.TARGET_AUTH, "user-context",
                     {"statements": [{"text": "拿 flag"}]}, updated_by="user-context")
            bb.write(BlackboardLayer.ASSET, "asset-1", {"host": "a.test"},
                     agent_type=AgentType.MASTER, updated_by="test")
            bb.write(BlackboardLayer.RECON_CLUE, "clue-1", {"path": "/admin"},
                     updated_by="test")
            bb.write(BlackboardLayer.VULN, "vuln-1", {"title": "SQLi"}, updated_by="test")
            bb.write(BlackboardLayer.CREDENTIAL, "cred-1", {"user": "admin"},
                     updated_by="test")
            bb.write(BlackboardLayer.TOPOLOGY, "topo-1", {"edge": "a->b"},
                     agent_type=AgentType.MASTER, updated_by="test")
            bb.write(BlackboardLayer.TASK_STATE, "task-1", {"status": "solved"},
                     updated_by="test")
        finally:
            bb.close()

    def _call(self, plan, mode="ctf"):
        return taskid.switch_if_changed(
            bb_path=self.bb_path, workspace=self.workspace,
            plan=plan, mode=mode, audit=self.audit)

    def _layers(self) -> dict[str, int]:
        bb = Blackboard(self.bb_path)
        try:
            return {layer.value: bb.count(layer) for layer in BlackboardLayer}
        finally:
            bb.close()

    def test_first_run_records_identity_without_clearing(self) -> None:
        self._seed()
        before = self._layers()
        self.assertIsNone(self._call(_plan([CHALLENGE_A])))
        after = self._layers()
        # 第一次开工：只多了一条身份记录，其他一条不少
        self.assertEqual(after["target_auth"], before["target_auth"] + 1)
        for name in ("asset", "recon_clue", "vuln", "credential", "topology", "task_state"):
            self.assertEqual(after[name], before[name], name)

    def test_same_challenge_keeps_previous_results(self) -> None:
        self._seed()
        self._call(_plan([CHALLENGE_A]))
        before = self._layers()
        self.assertIsNone(self._call(_plan([CHALLENGE_A])))
        self.assertEqual(self._layers(), before)

    def test_switching_challenge_clears_previous_facts(self) -> None:
        self._seed()
        self._call(_plan([CHALLENGE_A]))
        switch = self._call(_plan([CHALLENGE_B]))
        self.assertIsNotNone(switch)
        assert switch is not None
        for name in ("asset", "recon_clue", "vuln", "credential", "topology", "task_state"):
            self.assertEqual(switch.cleared.get(name, 0), 1, name)
        counts = self._layers()
        for name in ("asset", "recon_clue", "vuln", "credential", "topology", "task_state"):
            self.assertEqual(counts[name], 0, name)

    def test_switching_keeps_user_context_and_identity(self) -> None:
        self._seed()
        self._call(_plan([CHALLENGE_A]))
        self._call(_plan([CHALLENGE_B]))
        bb = Blackboard(self.bb_path)
        try:
            self.assertIsNotNone(bb.read(BlackboardLayer.TARGET_AUTH, "user-context"))
            ident = bb.read(BlackboardLayer.TARGET_AUTH, taskid.IDENTITY_RECORD)
        finally:
            bb.close()
        self.assertEqual(ident["fingerprint"],
                         taskid.identity_of(_plan([CHALLENGE_B])).fingerprint)

    def test_switching_archives_flag_store_and_progress(self) -> None:
        old = taskid.identity_of(_plan([CHALLENGE_A])).fingerprint
        (self.workspace / "flags.json").write_text('{"flags": []}', encoding="utf-8")
        (self.workspace / "competition_progress.json").write_text(
            '{"solved_ids": ["web-01"]}', encoding="utf-8")
        self._call(_plan([CHALLENGE_A]))
        switch = self._call(_plan([CHALLENGE_B]))
        assert switch is not None
        self.assertEqual(len(switch.archived), 2)
        # 归档意味着原名不再存在：新一轮不会读到上一题的 flag 与进度
        self.assertFalse((self.workspace / "flags.json").exists())
        self.assertFalse((self.workspace / "competition_progress.json").exists())
        archived = {p.name for p in self.workspace.iterdir()}
        self.assertTrue(any(old in name for name in archived), archived)

    def test_switch_is_audited(self) -> None:
        self._seed()
        self._call(_plan([CHALLENGE_A]))
        self._call(_plan([CHALLENGE_B]))
        rows = [json.loads(line) for line in
                (self.workspace / "audit.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()]
        actions = [r["detail"].get("action") for r in rows if isinstance(r.get("detail"), dict)]
        self.assertIn("task_switched", actions)

    def test_summary_mentions_both_challenges(self) -> None:
        self._seed()
        self._call(_plan([CHALLENGE_A]))
        switch = self._call(_plan([CHALLENGE_B]))
        assert switch is not None
        text = switch.summary()
        self.assertIn("登录绕过", text)
        self.assertIn("反序列化", text)
        self.assertIn("不再带入本次", text)

    def test_no_identity_layer_write_when_same(self) -> None:
        """同一道题重跑不该产生新的身份版本（否则黑板每轮都在涨）。"""
        self._call(_plan([CHALLENGE_A]))
        bb = Blackboard(self.bb_path)
        try:
            row = bb.read_versioned(BlackboardLayer.TARGET_AUTH, taskid.IDENTITY_RECORD)
        finally:
            bb.close()
        version = row[1]
        self._call(_plan([CHALLENGE_A]))
        bb = Blackboard(self.bb_path)
        try:
            again = bb.read_versioned(BlackboardLayer.TARGET_AUTH, taskid.IDENTITY_RECORD)
        finally:
            bb.close()
        self.assertEqual(again[1], version)


if __name__ == "__main__":
    unittest.main()
