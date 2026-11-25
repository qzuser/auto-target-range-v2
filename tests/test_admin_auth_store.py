from __future__ import annotations

import base64
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing, contextmanager
from pathlib import Path
from unittest.mock import patch

from spiritscout.core.exceptions import ConfigurationError
from spiritscout.web import auth

_ENV_KEYS = (
    "SPIRITSCOUT_ADMIN_USERNAME",
    "SPIRITSCOUT_ADMIN_PASSWORD",
    "SPIRITSCOUT_SERVER_PASSWORD",
    "SPIRITSCOUT_ADMIN_SYNC",
)


@contextmanager
def env_only(**values: str):
    with patch.dict(os.environ, values, clear=False):
        for key in _ENV_KEYS:
            if key not in values:
                os.environ.pop(key, None)
        yield


class PasswordHashTests(unittest.TestCase):
    def test_hash_roundtrip_and_format(self) -> None:
        token = auth.hash_password("s3cret")
        self.assertTrue(token.startswith("scrypt$16384$8$1$"))
        self.assertNotIn("s3cret", token)
        self.assertTrue(auth.verify_password("s3cret", token))
        self.assertFalse(auth.verify_password("wrong", token))

    def test_same_password_gets_fresh_salt(self) -> None:
        self.assertNotEqual(auth.hash_password("same"),
                            auth.hash_password("same"))

    def test_malformed_hash_is_rejected(self) -> None:
        for stored in ("", "plain", "scrypt$x$8$1$a$b",
                       "scrypt$999999999$8$1$AAAA$AAAA"):
            self.assertFalse(auth.verify_password("secret", stored))


class AdminStoreTests(unittest.TestCase):
    def test_upsert_verify_and_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = auth.AdminStore(tmp)
            self.assertFalse(store.has_admins())
            store.upsert("admin", "first")
            self.assertTrue(store.has_admins())
            self.assertTrue(store.verify("admin", "first"))
            self.assertFalse(store.verify("admin", "second"))
            self.assertFalse(store.verify("nobody", "first"))
            old = store.password_fingerprint("admin")
            store.upsert("admin", "second")
            self.assertNotEqual(old, store.password_fingerprint("admin"))
            self.assertTrue(store.verify("admin", "second"))

    def test_env_sync_priority_and_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, env_only(
                SPIRITSCOUT_ADMIN_USERNAME="admin",
                SPIRITSCOUT_ADMIN_PASSWORD="new",
                SPIRITSCOUT_SERVER_PASSWORD="old"):
            store = auth.AdminStore(tmp)
            self.assertEqual(
                store.sync_from_env("SPIRITSCOUT_SERVER_PASSWORD",
                                    "SPIRITSCOUT_ADMIN_USERNAME",
                                    "SPIRITSCOUT_ADMIN_PASSWORD"),
                "admin")
            self.assertTrue(store.verify("admin", "new"))
            with env_only():
                self.assertIsNone(
                    store.sync_from_env("SPIRITSCOUT_SERVER_PASSWORD",
                                        "SPIRITSCOUT_ADMIN_USERNAME",
                                        "SPIRITSCOUT_ADMIN_PASSWORD"))
            self.assertTrue(store.verify("admin", "new"))

    def test_admin_password_cli_roundtrip_and_clear(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            config = root / "system.yaml"
            config.write_text(
                "workspace:\n"
                f"  root: {json.dumps(str(workspace))}\n",
                encoding="utf-8",
            )
            password = "p" * 1100
            set_result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "spiritscout",
                    "--config",
                    str(config),
                    "--set-admin-password",
                    "--password-stdin",
                ],
                input=password + "\n",
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                cwd=Path(__file__).resolve().parents[1],
                timeout=30,
                check=False,
            )
            self.assertEqual(set_result.returncode, 0, set_result.stderr)
            store = auth.AdminStore(workspace)
            self.assertTrue(store.verify("spiritscout", password))

            clear_result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "spiritscout",
                    "--config",
                    str(config),
                    "--clear-admin-password",
                ],
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                cwd=Path(__file__).resolve().parents[1],
                timeout=30,
                check=False,
            )
            self.assertEqual(clear_result.returncode, 0, clear_result.stderr)
            self.assertFalse(store.has_admins())

    def test_env_sync_skips_identical_password_and_can_be_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = auth.AdminStore(tmp)
            store.upsert("admin", "stable")
            with closing(sqlite3.connect(Path(tmp) / "admin.db")) as conn:
                before = conn.execute(
                    "SELECT updated_at FROM admins WHERE username='admin'"
                ).fetchone()[0]
            with env_only(SPIRITSCOUT_ADMIN_USERNAME="admin",
                          SPIRITSCOUT_ADMIN_PASSWORD="stable"):
                store.sync_from_env("SPIRITSCOUT_SERVER_PASSWORD",
                                    "SPIRITSCOUT_ADMIN_USERNAME",
                                    "SPIRITSCOUT_ADMIN_PASSWORD")
            with closing(sqlite3.connect(Path(tmp) / "admin.db")) as conn:
                after = conn.execute(
                    "SELECT updated_at FROM admins WHERE username='admin'"
                ).fetchone()[0]
            self.assertEqual(before, after)

            with env_only(SPIRITSCOUT_ADMIN_USERNAME="admin",
                          SPIRITSCOUT_ADMIN_PASSWORD="changed",
                          SPIRITSCOUT_ADMIN_SYNC="0"):
                self.assertIsNone(store.sync_from_env(
                    "SPIRITSCOUT_SERVER_PASSWORD",
                    "SPIRITSCOUT_ADMIN_USERNAME",
                    "SPIRITSCOUT_ADMIN_PASSWORD"))
            self.assertTrue(store.verify("admin", "stable"))

    def test_invalid_env_username_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, env_only(
                SPIRITSCOUT_ADMIN_USERNAME="bad:name",
                SPIRITSCOUT_ADMIN_PASSWORD="secret"):
            with self.assertRaises(ConfigurationError):
                auth.AdminStore(tmp).sync_from_env(
                    "SPIRITSCOUT_SERVER_PASSWORD",
                    "SPIRITSCOUT_ADMIN_USERNAME",
                    "SPIRITSCOUT_ADMIN_PASSWORD")


class SessionTests(unittest.TestCase):
    def test_session_roundtrip_and_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = auth.AdminStore(tmp)
            store.upsert("admin", "secret")
            token = store.issue_session("admin")
            self.assertEqual(store.verify_session(token), "admin")
            self.assertIsNone(store.verify_session(token + "x"))
            self.assertIsNone(store.verify_session("v1.abc.def"))
            self.assertIsNone(store.verify_session(""))
            self.assertTrue((Path(tmp) / "auth.key").is_file())

    def test_session_expires(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = auth.AdminStore(tmp)
            store.upsert("admin", "secret")
            with patch("spiritscout.web.auth.time.time", return_value=1000):
                token = store.issue_session("admin")
            with patch("spiritscout.web.auth.time.time",
                       return_value=1000 + auth.SESSION_TTL_SECONDS + 1):
                self.assertIsNone(store.verify_session(token))

    def test_password_change_invalidates_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = auth.AdminStore(tmp)
            store.upsert("admin", "old")
            token = store.issue_session("admin")
            store.upsert("admin", "new")
            self.assertIsNone(store.verify_session(token))

    def test_corrupt_key_file_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = auth.AdminStore(tmp)
            store.upsert("admin", "secret")
            (Path(tmp) / "auth.key").write_text("not-hex", encoding="ascii")
            with self.assertRaises(ConfigurationError):
                store.issue_session("admin")


class BasicHeaderTests(unittest.TestCase):
    def test_parse_basic_header(self) -> None:
        encoded = base64.b64encode(b"admin:pw").decode("ascii")
        self.assertEqual(auth.parse_basic_header(f"Basic {encoded}"),
                         ("admin", "pw"))
        self.assertIsNone(auth.parse_basic_header("Basic"))
        self.assertIsNone(auth.parse_basic_header("Basic "))
        self.assertIsNone(auth.parse_basic_header("Bearer token"))
        self.assertIsNone(auth.parse_basic_header("Basic !!!"))


class RateLimiterTests(unittest.TestCase):
    def test_window_slides_and_success_resets(self) -> None:
        now = [0.0]
        limiter = auth.LoginRateLimiter(
            limit=3, window=60.0, clock=lambda: now[0])
        self.assertIsNone(limiter.retry_after("ip"))
        for _ in range(3):
            limiter.failure("ip")
        self.assertIsNotNone(limiter.retry_after("ip"))
        now[0] = 61.0
        self.assertIsNone(limiter.retry_after("ip"))

        limiter.failure("ip")
        limiter.failure("ip")
        limiter.reset("ip")
        self.assertIsNone(limiter.retry_after("ip"))


if __name__ == "__main__":
    unittest.main()
