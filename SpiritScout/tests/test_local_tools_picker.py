"""「选择文件夹」对话框：确认选中路径能直接进配置，取消与失败都不改配置。

真正的原生窗口不在测试里弹（会卡住跑测试的人），用 mock 替换
``dir_picker.pick_directory``；对话框自身的行为靠子进程脚本的边界保证。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from spiritscout.tools import dir_picker
from spiritscout.web.routes.local_tools import mount_local_tools


class DirPickerRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "workspace"
        self.root.mkdir(parents=True)
        self.tools = Path(self.tmp.name) / "工具 目录"
        self.tools.mkdir()
        (self.tools / "demo.py").write_text("print('ok')\n", encoding="utf-8")
        app = FastAPI()
        mount_local_tools(app, cfg=SimpleNamespace(workspace=SimpleNamespace(root=str(self.root))))
        self.client = TestClient(app)

    def tearDown(self):
        self.tmp.cleanup()

    def test_pick_returns_path_and_can_be_saved(self):
        with mock.patch.object(dir_picker, "pick_directory", return_value=str(self.tools)) as pick:
            data = self.client.post("/api/local-tools/pick-dir").json()
        self.assertFalse(data["cancelled"])
        self.assertEqual(data["path"], str(self.tools))
        pick.assert_called_once()
        saved = self.client.put("/api/local-tools", json={"dirs": [data["path"]]}).json()
        self.assertEqual(saved["config"]["dirs"], [str(self.tools)])
        self.assertEqual(saved["summary"]["tools"], 1)

    def test_pick_uses_first_configured_dir_as_start(self):
        self.client.put("/api/local-tools", json={"dirs": [str(self.tools)]})
        with mock.patch.object(dir_picker, "pick_directory", return_value=None) as pick:
            self.client.post("/api/local-tools/pick-dir")
        self.assertEqual(pick.call_args.args[0], str(self.tools))

    def test_pick_cancel_keeps_config(self):
        self.client.put("/api/local-tools", json={"dirs": [str(self.tools)]})
        with mock.patch.object(dir_picker, "pick_directory", return_value=None):
            data = self.client.post("/api/local-tools/pick-dir").json()
        self.assertTrue(data["cancelled"])
        self.assertIsNone(data["path"])
        self.assertEqual(self.client.get("/api/local-tools").json()["config"]["dirs"], [str(self.tools)])

    def test_pick_failure_reports_503_with_reason(self):
        with mock.patch.object(dir_picker, "pick_directory",
                               side_effect=dir_picker.PickerError("这台机器没有可用的图形界面")):
            resp = self.client.post("/api/local-tools/pick-dir")
        self.assertEqual(resp.status_code, 503)
        self.assertIn("图形界面", resp.json()["detail"])

    def test_pick_initial_override(self):
        other = Path(self.tmp.name) / "other"
        other.mkdir()
        with mock.patch.object(dir_picker, "pick_directory", return_value=None) as pick:
            self.client.post("/api/local-tools/pick-dir", params={"initial": str(other)})
        self.assertEqual(pick.call_args.args[0], str(other))


class DirPickerUnitTests(unittest.TestCase):
    def test_normalize_keeps_only_existing_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(dir_picker._normalize(tmp), str(Path(tmp)))
            self.assertEqual(dir_picker._normalize(str(Path(tmp) / "nope")), "")
            self.assertEqual(dir_picker._normalize("  "), "")
            self.assertEqual(dir_picker._normalize(None), "")

    def test_available_reflects_tkinter(self):
        with mock.patch.dict("sys.modules", {"tkinter": None}):
            self.assertFalse(dir_picker.available())
        self.assertTrue(dir_picker.available())

    def test_pick_reports_missing_gui(self):
        with mock.patch.object(dir_picker, "available", return_value=False):
            with self.assertRaises(dir_picker.PickerError):
                dir_picker.pick_directory()

    def test_pick_rejects_non_directory_output(self):
        done = SimpleNamespace(returncode=0, stdout=b"/definitely/not/here\n", stderr=b"")
        with mock.patch.object(dir_picker, "available", return_value=True), \
             mock.patch.object(dir_picker.subprocess, "run", return_value=done):
            with self.assertRaises(dir_picker.PickerError):
                dir_picker.pick_directory()

    def test_pick_reports_missing_tkinter_from_child(self):
        done = SimpleNamespace(returncode=3, stdout=b"",
                               stderr=b"no-gui:No module named 'tkinter'")
        with mock.patch.object(dir_picker, "available", return_value=True), \
             mock.patch.object(dir_picker.subprocess, "run", return_value=done):
            with self.assertRaises(dir_picker.PickerError) as ctx:
                dir_picker.pick_directory()
        self.assertIn("No module named", str(ctx.exception))

    def test_closing_dialog_counts_as_cancel(self):
        """点窗口的 X、按取消、Esc 都只算「没选」，不是故障。"""
        for done in (
            SimpleNamespace(returncode=0, stdout=b"", stderr=b""),
            SimpleNamespace(returncode=0, stdout=b"", stderr=b"dialog-aborted: TclError"),
            SimpleNamespace(returncode=1, stdout=b"", stderr=b"something odd"),
        ):
            with mock.patch.object(dir_picker, "available", return_value=True), \
                 mock.patch.object(dir_picker.subprocess, "run", return_value=done):
                self.assertIsNone(dir_picker.pick_directory())

    def test_pick_accepts_existing_directory_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            done = SimpleNamespace(returncode=0, stdout=tmp.encode(), stderr=b"")
            with mock.patch.object(dir_picker, "available", return_value=True), \
                 mock.patch.object(dir_picker.subprocess, "run", return_value=done):
                self.assertEqual(dir_picker.pick_directory(), str(Path(tmp)))

    def test_pick_timeout_is_reported(self):
        import subprocess as sp

        with mock.patch.object(dir_picker, "available", return_value=True), \
             mock.patch.object(dir_picker.subprocess, "run",
                               side_effect=sp.TimeoutExpired(cmd="x", timeout=1)):
            with self.assertRaises(dir_picker.PickerError) as ctx:
                dir_picker.pick_directory(timeout=1)
        self.assertIn("没有响应", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
