"""``python -m spiritscout --set-admin-password`` 的行为测试。

这条命令是首次启动唯一的设密入口：启动脚本把 stdin 交给它，用户输入的明文
只在这一个进程里存在，落盘的是 scrypt 哈希。所以这里盯五件事——写进去了、
写的是哈希、第二次不覆盖、被拒绝时不留残骸，以及「密码不设长度限制、明文只在
交互终端里显示一次」这两条当前口径。
"""

from __future__ import annotations

import contextlib
import io
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from spiritscout.__main__ import (
    EXIT_PASSWORD_REJECTED,
    main,
    set_admin_password,
)
from spiritscout.web import auth


class _Stdin(io.StringIO):
    """可控的 stdin：能当终端也能当管道，避免测试真去等键盘。"""

    def __init__(self, text: str = "", tty: bool = False) -> None:
        super().__init__(text)
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def _config(root: Path) -> Path:
    """只带 workspace.root 的最小配置；其余段走 settings 的默认值。"""
    path = root / "system.yaml"
    path.write_text(f'workspace:\n  root: "{(root / "ws").as_posix()}"\n',
                    encoding="utf-8")
    return path


class SetAdminPasswordCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        self.cfg = _config(self.root)
        self.db = self.root / "ws" / "admin.db"

    def tearDown(self) -> None:
        # Windows 上 sqlite 句柄释放稍慢，cleanup() 会静默放弃删除；
        # 再兜一次，别把 tmpXXXX 留在仓库里。
        self._tmp.cleanup()
        shutil.rmtree(self.root, ignore_errors=True)

    def _run(self, *extra: str, stdin: str = "", tty: bool = False) -> int:
        with patch("sys.stdin", _Stdin(stdin, tty=tty)):
            return main(["--config", str(self.cfg), "--set-admin-password",
                         *extra])

    def test_password_from_stdin_is_stored_as_hash_only(self) -> None:
        secret = "First-Run-Pass"
        self.assertEqual(self._run("--password-stdin", stdin=secret + "\n"), 0)
        self.assertTrue(self.db.exists())
        store = auth.AdminStore(self.root / "ws")
        self.assertTrue(store.has_admins())
        self.assertTrue(store.verify("spiritscout", secret))
        # 明文绝不出现在库里（连字节串都不该有）
        self.assertNotIn(secret.encode(), self.db.read_bytes())
        with closing(sqlite3.connect(self.db)) as con:
            stored = con.execute(
                "SELECT password_hash FROM admins").fetchone()[0]
        self.assertTrue(stored.startswith("scrypt$"))
        self.assertNotIn(secret, stored)

    def test_if_missing_keeps_existing_account(self) -> None:
        self.assertEqual(self._run("--password-stdin", "--if-missing",
                                   stdin="Original-Pass-1\n"), 0)
        store = auth.AdminStore(self.root / "ws")
        before = store.password_fingerprint("spiritscout")
        self.assertEqual(self._run("--password-stdin", "--if-missing",
                                   stdin="Other-Pass-2\n"), 0)
        self.assertEqual(store.password_fingerprint("spiritscout"), before)
        self.assertTrue(store.verify("spiritscout", "Original-Pass-1"))

    def test_admin_username_can_be_chosen(self) -> None:
        self.assertEqual(self._run("--password-stdin", "--admin-username",
                                   "ops", stdin="Whatever-123\n"), 0)
        store = auth.AdminStore(self.root / "ws")
        self.assertTrue(store.verify("ops", "Whatever-123"))
        self.assertFalse(store.verify("spiritscout", "Whatever-123"))

    def test_interactive_prompt_asks_twice(self) -> None:
        with patch("builtins.input", return_value=""), patch(
                "getpass.getpass", side_effect=["Typed-Secret", "Typed-Secret"]):
            self.assertEqual(self._run(tty=True), 0)
        self.assertTrue(
            auth.AdminStore(self.root / "ws").verify("spiritscout", "Typed-Secret"))

    def test_mismatch_leaves_no_database(self) -> None:
        with patch("builtins.input", return_value=""), patch(
                "getpass.getpass", side_effect=["One-Pass-1", "Two-Pass-2"]):
            self.assertEqual(self._run(tty=True), EXIT_PASSWORD_REJECTED)
        self.assertFalse(self.db.exists())

    def test_any_password_length_is_accepted(self) -> None:
        """字符限制已经拆掉：一位的口令也照设，几千字的也照设。"""
        self.assertEqual(self._run("--password-stdin", stdin="1\n"), 0)
        self.assertTrue(auth.AdminStore(self.root / "ws").verify("spiritscout", "1"))
        long_secret = "p" * 4096
        self.assertEqual(self._run("--password-stdin", stdin=long_secret + "\n"), 0)
        self.assertTrue(
            auth.AdminStore(self.root / "ws").verify("spiritscout", long_secret))

    def test_empty_password_sets_no_account(self) -> None:
        self.assertEqual(self._run("--password-stdin", stdin="\n"), 0)
        self.assertFalse(self.db.exists())

    def test_password_shown_once_in_interactive_terminal(self) -> None:
        """交互终端设完把明文显示一次；之后的运行不再显示。"""
        secret = "Shown-Once-1"
        first = io.StringIO()
        with patch("builtins.input", return_value=""), patch(
                "getpass.getpass", side_effect=[secret, secret]), \
                contextlib.redirect_stdout(first):
            self.assertEqual(self._run(tty=True), 0)
        self.assertIn(secret, first.getvalue())
        self.assertIn("只在这里显示一次", first.getvalue())
        second = io.StringIO()
        with contextlib.redirect_stdout(second):
            self.assertEqual(self._run("--password-stdin", "--if-missing",
                                       stdin=secret + "\n"), 0)
        self.assertNotIn(secret, second.getvalue())

    def test_password_from_stdin_is_not_echoed(self) -> None:
        """管道/自动化这条路不回显：明文不该跟着 stdout 进日志。"""
        secret = "Piped-Secret-1"
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(self._run("--password-stdin", stdin=secret + "\n"), 0)
        self.assertNotIn(secret, out.getvalue())

    def test_non_interactive_without_stdin_flag_is_rejected(self) -> None:
        self.assertEqual(self._run(), EXIT_PASSWORD_REJECTED)
        self.assertFalse(self.db.exists())

    def test_non_interactive_if_missing_skips_quietly(self) -> None:
        # 启动脚本在管道里调用时必须秒过，不能卡住启动
        self.assertEqual(self._run("--if-missing"), 0)
        self.assertFalse(self.db.exists())

    def test_tty_without_readable_input_skips_instead_of_crashing(self) -> None:
        """终端看着是交互的、实际被脚本包住（读输入抛 EOF）：跳过，不崩也不卡。"""
        with patch("sys.stdin", _Stdin("", tty=True)), \
                patch("builtins.input", side_effect=EOFError):
            self.assertEqual(self._run("--if-missing"), 0)
        self.assertFalse(self.db.exists())
        with patch("sys.stdin", _Stdin("", tty=True)), \
                patch("builtins.input", side_effect=EOFError):
            self.assertEqual(self._run(), EXIT_PASSWORD_REJECTED)

    def test_setup_writes_hash_but_no_session_key(self) -> None:
        # 设密只写 admin.db；登录 Cookie 的签名密钥（auth.key）是懒加载的，
        # 第一次签发会话才落地——它同样绝不进包，但不该被设密顺手带出来。
        self.assertEqual(self._run("--password-stdin", stdin="Key-Check-1\n"), 0)
        key = self.root / "ws" / "auth.key"
        self.assertTrue(self.db.exists())
        self.assertFalse(key.exists())
        store = auth.AdminStore(self.root / "ws")
        store.issue_session("spiritscout")
        self.assertTrue(key.exists())
        self.assertEqual(len(bytes.fromhex(key.read_text("ascii").strip())), 32)


class _Args:
    """set_admin_password 直接调用时用的最小参数壳。"""

    if_missing = False
    admin_username = None
    password_stdin = True


class DirectCallTests(unittest.TestCase):
    def test_returns_skip_for_existing_account(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            store = auth.AdminStore(root / "ws")
            store.upsert("spiritscout", "Already-Set-1")
            from spiritscout.config import load_system_config

            args = _Args()
            args.if_missing = True
            with patch("sys.stdin", _Stdin("Ignored-Pass\n")):
                self.assertEqual(
                    set_admin_password(
                        load_system_config(str(_config(root))), args), 0)
            self.assertTrue(store.verify("spiritscout", "Already-Set-1"))


if __name__ == "__main__":
    unittest.main()
