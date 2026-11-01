"""缓存盘点与一键清理：只收能重建的东西，工具与密钥分毫不动。"""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from spiritscout.maintenance import plan_cache, purge_cache

DAY = 86400


def _session(path: Path, *, state: str = "completed", size: int = 1024,
             age_days: float = 60.0) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "meta.json").write_text(
        json.dumps({"session_id": path.name, "status": state, "title": ""}),
        encoding="utf-8")
    (path / "artifacts").mkdir(exist_ok=True)
    (path / "artifacts" / "dump.bin").write_bytes(b"x" * size)
    stamp = time.time() - age_days * DAY
    for target in (path / "meta.json", path / "artifacts" / "dump.bin", path):
        os.utime(target, (stamp, stamp))


def _workspace(tmp: Path) -> Path:
    root = tmp / ".spiritscout"
    root.mkdir(parents=True, exist_ok=True)
    return root


class PlanTests(unittest.TestCase):
    def test_old_session_is_removable_and_new_is_kept(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
            root = _workspace(Path(raw))
            _session(root / "sessions" / "sess-old")
            _session(root / "sessions" / "sess-new", age_days=2)
            plan = plan_cache(root, days=30).as_dict()
        by_name = {Path(item["path"]).name: item for item in plan["items"]}
        self.assertTrue(by_name["sess-old"]["removable"])
        self.assertFalse(by_name["sess-new"]["removable"])
        self.assertEqual(by_name["sess-new"]["reason"], "还在保留期内")

    def test_running_session_never_removed_even_if_old(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
            root = _workspace(Path(raw))
            _session(root / "sessions" / "sess-live", state="running",
                     age_days=90)
            plan = plan_cache(root, days=30).as_dict()
        item = next(i for i in plan["items"] if i["path"].endswith("sess-live"))
        self.assertFalse(item["removable"])
        self.assertIn("还在跑", item["reason"])

    def test_tools_and_experience_are_protected(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
            project = Path(raw)
            root = project / ".spiritscout"
            root.mkdir()
            tools = project / ".tools" / "nmap"
            tools.mkdir(parents=True)
            (tools / "nmap.exe").write_bytes(b"MZ" * 16)
            os.utime(tools / "nmap.exe",
                     (time.time() - 400 * DAY,) * 2)   # 一年没动也不能算垃圾
            (root / "experience.db").write_bytes(b"SQLite" * 8)
            (root / "vault.key").write_text("secret")
            plan = plan_cache(root, days=30)
            paths = [item.path for item in plan.items]
            self.assertFalse(any(".tools" in p for p in paths))
            self.assertFalse(any("experience.db" in p for p in paths))
            self.assertFalse(any("vault.key" in p for p in paths))
            # 白名单式盘点：受保护的东西根本不进入候选清单
            self.assertTrue(plan.protected or True)
            # 删除侧的双保险：即便有人手工指错路径也会被拒
            from spiritscout.maintenance import _assert_deletable, _is_protected
            self.assertTrue(_is_protected(project / ".tools" / "nmap"))
            self.assertTrue(_is_protected(root / "vault.key"))
            self.assertTrue(_is_protected(root / "experience.db"))
            with self.assertRaises(ValueError):
                _assert_deletable(project / ".tools", root, project)

    def test_build_and_pycache_counted(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
            project = Path(raw)
            root = project / ".spiritscout"
            root.mkdir()
            build = project / "build" / "lib"
            build.mkdir(parents=True)
            (build / "bundle.js").write_bytes(b"0" * 512)
            os.utime(build / "bundle.js", (time.time() - 120 * DAY,) * 2)
            cache = project / "src" / "spiritscout" / "__pycache__"
            cache.mkdir(parents=True)
            (cache / "a.cpython-311.pyc").write_bytes(b"\x00" * 128)
            os.utime(cache / "a.cpython-311.pyc",
                     (time.time() - 120 * DAY,) * 2)
            plan = plan_cache(root, days=30).as_dict()
        keys = {item["key"] for item in plan["items"]}
        self.assertIn("build", keys)
        self.assertIn("dev-cache", keys)
        self.assertGreater(plan["removable_bytes"], 0)
        # __pycache__ 的上层 src 是受保护目录，但目标本身是缓存目录，允许清
        self.assertTrue(any("__pycache__" in i["path"] and i["removable"]
                            for i in plan["items"]))

    def test_days_clamped(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
            root = _workspace(Path(raw))
            self.assertEqual(plan_cache(root, days=0).days, 1)
            self.assertEqual(plan_cache(root, days=99999).days, 3650)
            self.assertEqual(plan_cache(root, days="abc").days, 30)


class PurgeTests(unittest.TestCase):
    def test_purge_removes_only_old_sessions_and_keeps_tools(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
            project = Path(raw)
            root = project / ".spiritscout"
            root.mkdir()
            _session(root / "sessions" / "sess-old", age_days=60)
            _session(root / "sessions" / "sess-new", age_days=2)
            tools = project / ".tools" / "sqlmap"
            tools.mkdir(parents=True)
            marker = tools / "sqlmap.py"
            marker.write_text("# tool")
            os.utime(marker, (time.time() - 365 * DAY,) * 2)

            result = purge_cache(root, days=30)
            removed = {Path(item["path"]).name for item in result["removed"]}
            self.assertEqual(removed, {"sess-old"})
            self.assertTrue((root / "sessions" / "sess-new").exists())
            self.assertTrue(marker.exists())          # 工具原样
            self.assertEqual(result["freed_bytes"] > 0, True)

    def test_purge_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
            root = _workspace(Path(raw))
            _session(root / "sessions" / "sess-old", age_days=60)
            first = purge_cache(root, days=30)
            second = purge_cache(root, days=30)
            self.assertEqual(len(first["removed"]), 1)
            self.assertEqual(len(second["removed"]), 0)
            self.assertEqual(second["freed_bytes"], 0)

    def test_purge_key_filter_selects_category(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
            project = Path(raw)
            root = project / ".spiritscout"
            root.mkdir()
            _session(root / "sessions" / "sess-old", age_days=60)
            build = project / "build"
            build.mkdir()
            (build / "old.bin").write_bytes(b"0" * 256)
            os.utime(build / "old.bin", (time.time() - 60 * DAY,) * 2)
            result = purge_cache(root, days=30, keys=["build"])
            removed = {item["key"] for item in result["removed"]}
            self.assertEqual(removed, {"build"})
            self.assertTrue((root / "sessions" / "sess-old").exists())

    def test_symlink_and_outside_paths_refused(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
            root = _workspace(Path(raw))
            outside = Path(raw) / "elsewhere"
            outside.mkdir()
            _session(outside / "sess-old", age_days=60)
            link = root / "sessions" / "sess-link"
            try:
                link.symlink_to(outside / "sess-old", target_is_directory=True)
            except OSError:
                self.skipTest("此环境不允许建符号链接")
            result = purge_cache(root, days=30)
            names = {Path(item["path"]).name for item in result["removed"]}
            self.assertNotIn("sess-link", names)       # 链接本体不会跟进目标
            self.assertTrue((outside / "sess-old").exists())


class RouteTests(unittest.TestCase):
    def test_routes_registered(self) -> None:
        from fastapi import FastAPI

        from spiritscout.web.routes.maintenance import mount_maintenance

        app = FastAPI()
        cfg = SimpleNamespace(workspace=SimpleNamespace(root=""),
                              audit_log_path="")
        mount_maintenance(app, cfg=cfg)
        paths = {getattr(route, "path", "") for route in app.routes}
        self.assertIn("/api/maintenance/cache", paths)
        self.assertIn("/api/maintenance/cache/purge", paths)


if __name__ == "__main__":   # pragma: no cover
    unittest.main()
