"""控制台登录默认关闭：本机工作台不再被自己的密码挡住。

登录只剩两条明确的路：`auth_mode: none`（默认，直接进）与
`auth_mode: password`（要管理员账号）。库里残留的账号不会把控制台重新锁上。
"""
from __future__ import annotations

import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from spiritscout.__main__ import clear_admin_password
from spiritscout.config.settings import SystemConfig, WebConfig, WorkspaceConfig
from spiritscout.core.exceptions import ConfigurationError
from spiritscout.web import auth as web_auth
from spiritscout.web.app import create_app

# 本机控制台只接受回环 Host（DNS 重绑定防护），测试也得从回环地址发请求
_BASE = "http://127.0.0.1"

_CREDENTIAL_ENVS = (
    "SPIRITSCOUT_ADMIN_USERNAME",
    "SPIRITSCOUT_ADMIN_PASSWORD",
    "SPIRITSCOUT_SERVER_PASSWORD",
    "SPIRITSCOUT_ADMIN_SYNC",
)


@contextmanager
def env_only(**values: str):
    with patch.dict(os.environ, values, clear=False):
        for key in _CREDENTIAL_ENVS:
            if key not in values:
                os.environ.pop(key, None)
        yield


def _app(root: str, *, host: str = "127.0.0.1", auth_mode: str = "none",
         remote_auth_required: bool = True):
    cfg = SystemConfig(
        workspace=WorkspaceConfig(root=root),
        web=WebConfig(host=host, auth_mode=auth_mode,
                      remote_auth_required=remote_auth_required),
    )
    return create_app(cfg, [])


class DefaultModeTests(unittest.TestCase):
    def test_web_config_defaults_to_no_login(self) -> None:
        self.assertEqual(WebConfig().auth_mode, "none")

    def test_open_console_serves_api_without_login(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp, env_only():
            with TestClient(_app(tmp), base_url=_BASE) as client:
                self.assertEqual(client.get("/api/sessions").status_code, 200)
                status = client.get("/api/auth/status").json()
                self.assertFalse(status["required"])
                self.assertFalse(status["authenticated"])

    def test_login_page_bounces_back_home(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp, env_only():
            with TestClient(_app(tmp), base_url=_BASE, follow_redirects=False) as client:
                response = client.get("/login")
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.headers["location"], "/")

    def test_leftover_admin_no_longer_locks_the_console(self) -> None:
        """以前只要 admin.db 里有账号就必须登录；现在由 auth_mode 说了算。"""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp, env_only(
                SPIRITSCOUT_ADMIN_PASSWORD="test-secret"):
            app = _app(tmp)                      # auth_mode=none
            self.assertTrue(web_auth.AdminStore(tmp).has_admins())
            with TestClient(app, base_url=_BASE) as client:
                self.assertEqual(client.get("/api/sessions").status_code, 200)
                self.assertFalse(client.get("/api/auth/status").json()["required"])


class PasswordModeTests(unittest.TestCase):
    def test_password_mode_still_blocks_anonymous(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp, env_only(
                SPIRITSCOUT_ADMIN_PASSWORD="test-secret"):
            with TestClient(_app(tmp, auth_mode="password"), base_url=_BASE) as client:
                self.assertEqual(client.get("/api/sessions").status_code, 401)
                self.assertTrue(client.get("/api/auth/status").json()["required"])

    def test_password_mode_without_account_runs_open(self) -> None:
        """选了 password 但还没设密码：本机不能因此起不来，先按开放模式跑。"""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp, env_only():
            with TestClient(_app(tmp, auth_mode="password"), base_url=_BASE) as client:
                self.assertEqual(client.get("/api/sessions").status_code, 200)
                self.assertFalse(client.get("/api/auth/status").json()["required"])


class RemoteBindTests(unittest.TestCase):
    def test_remote_bind_still_demands_login(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp, env_only():
            with self.assertRaises(ConfigurationError) as ctx:
                _app(tmp, host="0.0.0.0")
            self.assertIn("auth_mode", str(ctx.exception))

    def test_remote_bind_can_be_opened_explicitly(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp, env_only():
            app = _app(tmp, host="0.0.0.0", remote_auth_required=False)
            self.assertFalse(app.state.auth_enabled)


class ClearCredentialTests(unittest.TestCase):
    def test_clear_removes_every_account(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp, env_only():
            store = web_auth.AdminStore(tmp)
            store.upsert("spiritscout", "test-secret")
            self.assertTrue(store.has_admins())
            self.assertEqual(store.clear(), 1)
            self.assertFalse(store.has_admins())
            self.assertEqual(store.clear(), 0)      # 幂等

    def test_cli_clear_reports_and_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp, env_only():
            cfg = SystemConfig(workspace=WorkspaceConfig(root=tmp),
                               web=WebConfig())
            web_auth.AdminStore(tmp).upsert("spiritscout", "test-secret")
            self.assertEqual(clear_admin_password(cfg), 0)
            self.assertFalse(web_auth.AdminStore(tmp).has_admins())


class LauncherTests(unittest.TestCase):
    def test_launcher_no_longer_forces_password_setup(self) -> None:
        text = (Path(__file__).resolve().parents[1] / "launch.cmd").read_text(
            encoding="utf-8")
        commands = [line.strip() for line in text.splitlines()
                    if line.strip().lower().startswith('"%project_python%"')]
        self.assertTrue(commands, "启动器里应当有 python 命令行")
        for line in commands:
            self.assertNotIn("--set-admin-password", line)   # 启动不再逼你设密码
            self.assertIn("configs/system.yaml", line)
        self.assertIn("--auth password", text)      # 想开登录时怎么开，写在注释里
        self.assertTrue(text.isascii())             # cmd 里混中文会变乱码


if __name__ == "__main__":   # pragma: no cover
    unittest.main()
