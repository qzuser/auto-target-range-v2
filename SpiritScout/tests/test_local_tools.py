"""本地工具索引与运行器：找得到、跑得动、用完不留残留。

这些用例都建在临时目录上：被"工具"写出来的文件必须能被运行器认出来并清掉，
原目录要么一丝不变，要么把改动还原回去——这是这个功能唯一的硬承诺。
"""

from __future__ import annotations

import json
import os
import tempfile
import textwrap
import unittest
from pathlib import Path

from spiritscout.tools import local_index, local_runner
from spiritscout.tools.local_tool import local_tool

TOOL_SOURCE = textwrap.dedent(
    """
    import os, pathlib, sys, time

    here = pathlib.Path(__file__).parent
    # 1) 往自己的工作目录写（落在暂存副本里，随副本一起销毁）
    pathlib.Path("cwd-output.txt").write_text("cwd", encoding="utf-8")
    # 2) 往"自己的工具目录"写（同一个副本）
    (here / "self-drop.txt").write_text("own", encoding="utf-8")
    # 3) 往临时目录写（运行器把 TMP 指到副本里）
    tmp = os.environ.get("TEMP") or os.environ.get("TMP")
    if tmp:
        pathlib.Path(tmp, "tmp-drop.txt").write_text("tmp", encoding="utf-8")
    # 4) 显式往原目录写（越界写入：运行器必须删掉这个残留）
    if len(sys.argv) > 1:
        pathlib.Path(sys.argv[1]).write_text("leak", encoding="utf-8")
    # 5) 改一个原目录里的既有文件（运行器要用副本还原它）
    if len(sys.argv) > 2:
        pathlib.Path(sys.argv[2]).write_text("mutated", encoding="utf-8")
    if "--sleep" in sys.argv:
        time.sleep(30)
    print("done", sys.argv[1:])
    """
)


def make_tool(folder: Path, name: str = "demo.py", source: str = TOOL_SOURCE) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(source, encoding="utf-8")
    return path


class ScanTests(unittest.TestCase):
    def test_finds_runnable_and_skips_junk(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_tool(root)
            (root / "notes.md").write_text("x", encoding="utf-8")
            nested = root / "bin" / "deep"
            make_tool(nested, "second.cmd", "@echo off\n")
            skip = root / "node_modules" / "pkg"
            make_tool(skip, "hidden.exe", "x")
            tools = local_index.scan([str(root)], max_depth=3)
            names = sorted(tool["name"] for tool in tools)
            self.assertEqual(names, ["demo", "second"])
            entry = next(tool for tool in tools if tool["name"] == "demo")
            self.assertEqual(entry["ext"], ".py")
            self.assertEqual(entry["dir"], os.path.normpath(str(root)))
            self.assertGreater(entry["size"], 0)

    def test_depth_limit_and_missing_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_tool(root / "a" / "b" / "c", "deep.py")
            self.assertEqual(local_index.scan([str(root)], max_depth=1), [])
            self.assertEqual(local_index.scan([str(root / "missing")]), [])
            self.assertEqual(len(local_index.scan([str(root)], max_depth=4)), 1)

    def test_max_files_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index in range(6):
                make_tool(root, f"tool{index}.py")
            self.assertEqual(len(local_index.scan([str(root)], max_files=3)), 3)


class ConfigTests(unittest.TestCase):
    def test_defaults_are_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = local_index.load(Path(tmp))
            self.assertFalse(config["enabled"])
            self.assertEqual(config["dirs"], [])

    def test_save_merges_and_normalizes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            saved = local_index.save(root, {"enabled": True, "dirs": ["C:/工具", "C:/工具", ""]})
            self.assertTrue(saved["enabled"])
            self.assertEqual(len(saved["dirs"]), 1)
            again = local_index.save(root, {"timeout_seconds": 30})
            self.assertTrue(again["enabled"])          # 没传的字段保持原值
            self.assertEqual(again["timeout_seconds"], 30)
            self.assertEqual(local_index.load(root)["dirs"], saved["dirs"])

    def test_index_is_cached_until_dir_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "work"
            tools = Path(tmp) / "tools"
            make_tool(tools)
            config = local_index.save(root, {"enabled": True, "dirs": [str(tools)]})
            index = local_index.LocalToolIndex(root)
            first = index.ensure(config)
            self.assertEqual(len(first["tools"]), 1)
            self.assertEqual(index.ensure(config)["scanned_at"], first["scanned_at"])
            make_tool(tools, "later.exe", "x")           # 同目录新增 → 靠保鲜期重扫
            fresh = index.ensure(config, ttl=0)
            self.assertEqual(len(fresh["tools"]), 2)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.tools = self.root / "tools"
        self.tool = make_tool(self.tools)
        self.workspace = self.root / "work"

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, args=None, timeout=60):
        return local_runner.run_local_tool(
            {"name": "demo", "path": str(self.tool)}, list(args or []),
            workspace=self.workspace, roots=[str(self.tools)], timeout=timeout)

    def test_copies_runs_and_leaves_no_residue(self):
        before = local_runner.manifest(self.tools)
        result = self.run_tool()
        self.assertEqual(result["returncode"], 0)
        self.assertIn("done", result["stdout"])
        self.assertTrue(result["clean"], result)
        self.assertEqual(local_runner.manifest(self.tools), before)
        self.assertTrue(result["stage_removed"])
        self.assertFalse(any(local_runner.runs_root(self.workspace).glob("run-*")))

    def test_removes_writes_into_original_dir(self):
        leak = self.tools / "leak.txt"
        result = self.run_tool([str(leak)])
        self.assertTrue(result["clean"], result)
        self.assertFalse(leak.exists())
        self.assertIn("leak.txt", [Path(item).name for item in result["removed"]])

    def test_restores_modified_file_from_stage_copy(self):
        victim = self.tools / "config.ini"
        victim.write_text("original", encoding="utf-8")
        result = self.run_tool([str(self.tools / "nothing.txt"), str(victim)])
        self.assertTrue(result["clean"], result)
        self.assertEqual(victim.read_text(encoding="utf-8"), "original")
        self.assertIn("config.ini", [Path(item).name for item in result["restored"]])

    def test_timeout_kills_and_still_cleans(self):
        result = self.run_tool(["--sleep"], timeout=2)
        self.assertTrue(result["timed_out"])
        self.assertTrue(result["clean"])
        self.assertTrue(result["stage_removed"])

    def test_rejects_tool_outside_configured_dirs(self):
        outside = make_tool(self.root / "elsewhere", "evil.py")
        with self.assertRaises(local_runner.LocalToolError):
            local_runner.run_local_tool({"name": "evil", "path": str(outside)}, [],
                                        workspace=self.workspace, roots=[str(self.tools)])

    def test_rejects_oversized_stage(self):
        (self.tools / "blob.bin").write_bytes(b"\0" * (2 * 1024 * 1024))
        with self.assertRaises(local_runner.LocalToolError):
            local_runner.run_local_tool({"name": "demo", "path": str(self.tool)}, [],
                                        workspace=self.workspace, roots=[str(self.tools)],
                                        max_stage_mb=1)

    def test_sweep_removes_stale_runs(self):
        stale = local_runner.runs_root(self.workspace) / "run-old"
        stale.mkdir(parents=True)
        (stale / "junk.txt").write_text("x", encoding="utf-8")
        removed = local_runner.sweep_runs(self.workspace, stale_seconds=0)
        self.assertEqual(len(removed), 1)
        self.assertFalse(stale.exists())


class BuiltinToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.tools = self.root / "tools"
        self.tool = make_tool(self.tools)

    def tearDown(self):
        self.tmp.cleanup()

    async def call(self, **params):
        return await local_tool(workspace=self.root, **params)

    async def test_disabled_refuses(self):
        result = await self.call(operation="search", query="demo")
        self.assertFalse(result.ok)
        self.assertIn("未启用", result.error)

    async def test_search_describe_and_run(self):
        local_index.save(self.root, {"enabled": True, "dirs": [str(self.tools)]})
        found = await self.call(operation="search", query="dem")
        self.assertTrue(found.ok, found.error)
        payload = json.loads(found.stdout)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["tools"][0]["name"], "demo")

        described = await self.call(operation="describe", name="demo")
        self.assertTrue(described.ok)
        self.assertEqual(json.loads(described.stdout)["name"], "demo")

        leaked = self.tools / "leak.txt"
        ran = await self.call(operation="run", name="demo", args=[str(leaked)], action="analysis")
        self.assertTrue(ran.ok, ran.stdout or ran.error)
        self.assertTrue(ran.parsed["clean"])
        self.assertFalse(leaked.exists())

    async def test_cleans_when_tool_wrote_into_original_dir(self):
        local_index.save(self.root, {"enabled": True, "dirs": [str(self.tools)]})
        ran = await self.call(operation="run", name="demo",
                              args=[str(self.tools / "x.txt")], action="analysis")
        self.assertTrue(ran.ok, ran.stdout or ran.error)
        self.assertFalse((self.tools / "x.txt").exists())

    async def test_unknown_tool_and_operation(self):
        local_index.save(self.root, {"enabled": True, "dirs": [str(self.tools)]})
        missing = await self.call(operation="run", name="nope", action="analysis")
        self.assertFalse(missing.ok)
        self.assertIn("索引里没有", missing.error)
        bogus = await self.call(operation="explode")
        self.assertFalse(bogus.ok)


if __name__ == "__main__":
    unittest.main()
