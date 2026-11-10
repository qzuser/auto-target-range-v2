"""本地工具索引的接口：读配置、写目录、重扫、清暂存。

边界都在这层：目录必须是已存在的绝对路径，驱动器根直接拒；接口本身不执行
任何工具（执行只走 Agent 的 `local_tool`）。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from spiritscout.tools import local_runner
from spiritscout.web.routes.local_tools import mount_local_tools


def make_tool(folder: Path, name: str = "demo.py") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text("print('ok')\n", encoding="utf-8")
    return path


class LocalToolsApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "workspace"
        self.root.mkdir(parents=True)
        self.tools = Path(self.tmp.name) / "tools"
        make_tool(self.tools)
        app = FastAPI()
        mount_local_tools(app, cfg=SimpleNamespace(workspace=SimpleNamespace(root=str(self.root))))
        self.client = TestClient(app)

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_view_is_disabled(self):
        data = self.client.get("/api/local-tools").json()
        self.assertFalse(data["config"]["enabled"])
        self.assertEqual(data["tools"], [])
        self.assertIn("暂存", data["notice"])

    def test_put_enables_and_indexes(self):
        data = self.client.put("/api/local-tools",
                               json={"enabled": True, "dirs": [str(self.tools)]}).json()
        self.assertTrue(data["config"]["enabled"])
        self.assertEqual(data["summary"]["tools"], 1)
        self.assertEqual(data["tools"][0]["name"], "demo")
        self.assertTrue((self.root / "local-tools.json").is_file())

    def test_put_rejects_relative_and_missing_dirs(self):
        self.assertEqual(self.client.put("/api/local-tools",
                                         json={"dirs": ["relative/path"]}).status_code, 422)
        self.assertEqual(self.client.put("/api/local-tools",
                                         json={"dirs": [str(Path(self.tmp.name) / "nope")]}).status_code, 422)

    def test_put_rejects_drive_root(self):
        root = Path(self.tools.anchor)
        if root.parent == root:                       # 仅在真的能拿到盘符根时验证
            self.assertEqual(self.client.put("/api/local-tools",
                                             json={"dirs": [str(root)]}).status_code, 422)

    def test_refresh_sees_new_tool(self):
        self.client.put("/api/local-tools", json={"enabled": True, "dirs": [str(self.tools)]})
        make_tool(self.tools, "later.cmd")
        data = self.client.post("/api/local-tools/refresh").json()
        self.assertEqual(data["summary"]["tools"], 2)

    def test_query_filter_and_limits(self):
        self.client.put("/api/local-tools", json={"enabled": True, "dirs": [str(self.tools)]})
        make_tool(self.tools, "other.cmd")
        self.client.post("/api/local-tools/refresh")
        data = self.client.get("/api/local-tools", params={"q": "demo"}).json()
        self.assertEqual([tool["name"] for tool in data["tools"]], ["demo"])
        self.assertEqual(data["indexed"], 2)

    def test_cleanup_removes_stale_runs(self):
        stale = local_runner.runs_root(self.root) / "run-old"
        stale.mkdir(parents=True)
        (stale / "junk.bin").write_bytes(b"x")
        data = self.client.post("/api/local-tools/cleanup").json()
        self.assertEqual(data["count"], 1)
        self.assertFalse(stale.exists())


if __name__ == "__main__":
    unittest.main()
