"""host 后端的宿主侧 ACL 收口：会话目录去继承 + 证据目录 deny 写。

bwrap 的「整机只读 + 主目录遮蔽」在 Windows 上没有等价物，这里的边界是分级的：
只收紧本次会话目录（别的本地账户读不到、Agent 改不了自己的证据），**不做读隔离**。
非 Windows 平台整套跳过，并在用例里说明为什么。
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from spiritscout.tools import host_guard
from spiritscout.tools.sandbox import sandbox_backend, sandbox_exec

_IS_WINDOWS = os.name == "nt"
_WIN_ONLY = unittest.skipUnless(_IS_WINDOWS, "ACL 收口是 Windows 专有实现；POSIX 由进程组隔离")
_HOST_ONLY = unittest.skipUnless(
    sandbox_backend() == "host", "只在 host 后端（无 bwrap）验证")


class SIDTests(unittest.TestCase):
    @_WIN_ONLY
    def test_current_user_sid_is_a_sid(self) -> None:
        sid = host_guard.current_user_sid()
        self.assertTrue(sid.startswith("S-1-"), f"拿到的不是 SID: {sid!r}")
        self.assertEqual(sid.count("-") >= 4, True)


class HardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "session"
        self.evidence = self.root / "attachments"
        self.evidence.mkdir(parents=True)

    def tearDown(self) -> None:
        # 先撤销 deny 再删目录，否则清理时自己也会被拒
        host_guard.release(self.root, (self.evidence,))
        self._tmp.cleanup()

    @_WIN_ONLY
    def test_hardening_drops_inherited_aces(self) -> None:
        report = host_guard.harden(self.root, (self.evidence,))
        self.assertTrue(report.workspace_locked, report.skipped)
        acl = host_guard.describe_acl(self.root)
        # (I) 标记继承 ACE；要查的是 DACL——授权行里去继承后只应剩显式的
        # 本机用户 / SYSTEM / Administrators。完整性标签必须排除在外：
        # `icacls /inheritance:r` 不处理 Mandatory Label，而且那条低完整性
        # ACE 正是「Agent 只能读证据」的凭据，删掉才是错的。
        dacl = "\n".join(line for line in acl.splitlines()
                         if "Mandatory Label" not in line)
        self.assertNotIn("(I)", dacl, dacl)
        self.assertIn("SYSTEM", acl.upper())
        self.assertIn("ADMINISTRATORS", acl.upper())

    @_WIN_ONLY
    def test_existing_evidence_rejects_rewrite_but_upload_still_works(self) -> None:
        evidence_file = self.evidence / "challenge.txt"
        evidence_file.write_text("题面原文", encoding="utf-8")
        report = host_guard.harden(self.root, (self.evidence,))
        self.assertTrue(report.readonly_denied, report.skipped)
        with self.assertRaises(PermissionError):
            evidence_file.write_text("tampered", encoding="utf-8")
        # 目录本身不锁：平台补投的附件还得写得进来，否则上行通道被焊死
        fresh = self.evidence / "uploaded.txt"
        fresh.write_text("new", encoding="utf-8")
        self.assertTrue(fresh.is_file())
        host_guard.release(self.root, (self.evidence,))
        evidence_file.write_text("ok", encoding="utf-8")   # 撤销后恢复可写
        self.assertEqual(evidence_file.read_text(encoding="utf-8"), "ok")

    @_WIN_ONLY
    def test_hardening_is_applied_once_per_directory(self) -> None:
        first = host_guard.harden(self.root, (self.evidence,))
        second = host_guard.harden(self.root, (self.evidence,))
        self.assertTrue(first.applied)
        self.assertFalse(second.applied)
        self.assertEqual(second.skipped, "已加固")

    @unittest.skipIf(_IS_WINDOWS, "非 Windows 走进程组隔离，不启用 ACL 收口")
    def test_non_windows_skips_with_reason(self) -> None:
        report = host_guard.harden(self.root, (self.evidence,))
        self.assertFalse(report.applied)
        self.assertIn("非 Windows", report.skipped)
        self.assertFalse(host_guard.available())


class SandboxIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "workspace"
        self.root.mkdir(parents=True)

    def tearDown(self) -> None:
        host_guard.release(self.root, (self.root / "attachments",))
        self._tmp.cleanup()

    @_HOST_ONLY
    async def test_execution_reports_hardening_and_keeps_evidence_readonly(self) -> None:
        evidence = self.root / "attachments"
        evidence.mkdir(exist_ok=True)
        original = evidence / "challenge.txt"
        original.write_text("题面原文", encoding="utf-8")
        result = await sandbox_exec("printf hi", workspace_root=str(self.root))
        self.assertTrue(result.ok, result.error)
        status = (result.parsed or {}).get("hardening") or {}
        self.assertEqual(status.get("workspace_locked"), _IS_WINDOWS,
                         f"host 后端应报告 ACL 收口状态: {status}")
        if _IS_WINDOWS and status.get("workspace_locked"):
            # 沙箱里也改不动既有证据——收口对 Agent 自己同样生效
            tamper = await sandbox_exec(
                f"printf x > '{original}'", workspace_root=str(self.root))
            self.assertNotEqual(tamper.returncode, 0, "既有证据应当拒绝改写")
            self.assertEqual(original.read_text(encoding="utf-8"), "题面原文")
