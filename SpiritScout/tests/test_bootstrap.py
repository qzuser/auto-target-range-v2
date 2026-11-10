"""环境自检与一键修复：`scripts/bootstrap.py` 的行为。

这套逻辑决定「换台机器能不能跑起来」，所以每条失败路径都钉一遍：找不到解释器、
venv 半残、首个源装不动要换源、装完还要复验。全部用假 subprocess，不碰真网络。
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "bootstrap.py"


def _load():
    spec = importlib.util.spec_from_file_location("ss_bootstrap", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)   # type: ignore[union-attr]
    return module


bootstrap = _load()


class ParseVersionTests(unittest.TestCase):
    def test_reads_plain_and_prefixed(self) -> None:
        self.assertEqual(bootstrap.parse_version("3.11.6"), (3, 11, 6))
        self.assertEqual(bootstrap.parse_version("Python 3.12.1\n"), (3, 12, 1))
        self.assertEqual(bootstrap.parse_version("3.11"), (3, 11, 0))

    def test_rejects_garbage(self) -> None:
        self.assertIsNone(bootstrap.parse_version("no version here"))
        self.assertIsNone(bootstrap.parse_version(""))


class VenvPathTests(unittest.TestCase):
    def test_layout_follows_platform(self) -> None:
        root = Path("C:/proj") if os.name == "nt" else Path("/proj")
        exe = bootstrap.venv_python(root)
        if os.name == "nt":
            self.assertEqual(exe.parts[-2:], ("Scripts", "python.exe"))
        else:
            self.assertEqual(exe.parts[-2:], ("bin", "python"))
        self.assertEqual(exe.parent.parent, root / ".venv")


class FreePortTests(unittest.TestCase):
    def test_preferred_port_returned_when_free(self) -> None:
        port = bootstrap.free_port()
        self.assertTrue(1024 < port < 65536)

    def test_busy_port_falls_back_to_another(self) -> None:
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen(1)
            busy = sock.getsockname()[1]
            picked = bootstrap.free_port(busy)
        self.assertNotEqual(picked, busy)
        self.assertTrue(1024 < picked < 65536)


class DiagnoseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path("C:/proj") if os.name == "nt" else Path("/proj")

    def test_no_python_is_not_ok_and_says_so(self) -> None:
        with mock.patch.object(bootstrap, "find_python", return_value=None), \
                mock.patch.object(bootstrap, "venv_state",
                                  return_value={"path": "x", "exists": False,
                                                "version": None, "has_pip": False}):
            result = bootstrap.diagnose(self.root)
        self.assertFalse(result["ok"])
        self.assertTrue(any("Python" in w for w in result["warnings"]))

    def test_healthy_environment_reports_ok(self) -> None:
        venv = {"path": "x", "exists": True, "version": "3.11.6", "has_pip": True}
        deps = {"python": "3.11.6", "runtime_missing": [], "toolkit_missing": [],
                "self_version": "0.44.3", "source_version": "0.44.3", "pip": True}
        with mock.patch.object(bootstrap, "find_python",
                              return_value={"path": "x", "version": "3.11.6", "source": "venv"}), \
                mock.patch.object(bootstrap, "venv_state", return_value=venv), \
                mock.patch.object(bootstrap, "probe_environment", return_value=deps):
            result = bootstrap.diagnose(self.root)
        self.assertTrue(result["ok"])
        self.assertEqual(result["missing"], [])

    def test_missing_deps_is_not_ok(self) -> None:
        venv = {"path": "x", "exists": True, "version": "3.11.6", "has_pip": True}
        deps = {"python": "3.11.6", "runtime_missing": ["litellm"], "toolkit_missing": [],
                "self_version": None, "source_version": "0.44.3", "pip": True}
        with mock.patch.object(bootstrap, "find_python",
                              return_value={"path": "x", "version": "3.11.6", "source": "venv"}), \
                mock.patch.object(bootstrap, "venv_state", return_value=venv), \
                mock.patch.object(bootstrap, "probe_environment", return_value=deps):
            result = bootstrap.diagnose(self.root)
        self.assertFalse(result["ok"])
        self.assertEqual(result["missing"], ["litellm"])

    def test_venv_without_pip_is_flagged(self) -> None:
        venv = {"path": "x", "exists": True, "version": "3.11.6", "has_pip": False}
        with mock.patch.object(bootstrap, "find_python",
                              return_value={"path": "x", "version": "3.11.6", "source": "venv"}), \
                mock.patch.object(bootstrap, "venv_state", return_value=venv):
            result = bootstrap.diagnose(self.root)
        self.assertFalse(result["ok"])
        self.assertTrue(any("pip" in w for w in result["warnings"]))


class PipInstallTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path("C:/proj") if os.name == "nt" else Path("/proj")
        self.exe = self.root / ".venv" / "Scripts" / "python.exe"

    def test_switches_to_next_mirror_after_failure(self) -> None:
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            index = cmd[cmd.index("--index-url") + 1]
            code = 1 if "tuna" in index else 0
            return subprocess.CompletedProcess(cmd, code, "log line", "boom")

        with mock.patch.object(bootstrap, "_run", side_effect=fake_run):
            result = bootstrap._pip_install(".", root=self.root, exe=self.exe,
                                            mirrors=bootstrap.MIRRORS, timeout=5)
        self.assertTrue(result["ok"])
        self.assertIn("aliyun", result["mirror"])
        self.assertEqual(len(calls), 2, "第一个源失败后应当换下一个，而不是原地重试")

    def test_all_mirrors_failing_reports_false(self) -> None:
        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 1, "", "no network")

        with mock.patch.object(bootstrap, "_run", side_effect=fake_run):
            result = bootstrap._pip_install(".", root=self.root, exe=self.exe,
                                            mirrors=bootstrap.MIRRORS, timeout=5)
        self.assertFalse(result["ok"])
        self.assertEqual(len(result["attempts"]), len(bootstrap.MIRRORS))
        self.assertIsNone(result["mirror"])

    def test_command_carries_index_tmp_and_editable(self) -> None:
        seen: dict[str, object] = {}

        def fake_run(cmd, **kwargs):
            seen["cmd"] = list(cmd)
            seen["env"] = kwargs.get("env") or {}
            seen["cwd"] = kwargs.get("cwd")
            return subprocess.CompletedProcess(cmd, 0, "ok", "")

        with mock.patch.object(bootstrap, "_run", side_effect=fake_run):
            bootstrap._pip_install(".[toolkit]", root=self.root, exe=self.exe,
                                   mirrors=[bootstrap.OFFICIAL], timeout=5)
        cmd = seen["cmd"]
        self.assertEqual(cmd[cmd.index("--index-url") + 1], bootstrap.OFFICIAL)
        self.assertEqual(cmd[cmd.index("--editable") + 1], ".[toolkit]")
        self.assertIn("PIP_DISABLE_PIP_VERSION_CHECK", seen["env"])
        self.assertIn("TMP", seen["env"])
        self.assertEqual(Path(seen["cwd"]), self.root)


class FixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path("C:/proj") if os.name == "nt" else Path("/proj")

    def test_no_python_stops_before_touching_disk(self) -> None:
        with mock.patch.object(bootstrap, "diagnose", return_value={
                "python": None, "venv": {"exists": False}, "warnings": [], "missing": [],
                "toolkit_missing": [], "ok": False}):
            result = bootstrap.fix(self.root)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "no-python")

    def test_creates_venv_then_installs(self) -> None:
        absent = {"path": "x", "exists": False, "version": None, "has_pip": False}
        ready = {"path": "x", "exists": True, "version": "3.11.6", "has_pip": True}
        healthy = {"ok": True, "missing": [], "toolkit_missing": [], "python": None,
                   "venv": ready, "warnings": [], "deps": {"self_version": "0.44.3",
                                                           "runtime_missing": []}}
        started = {"python": {"path": "py -3.11", "version": "3.11.6", "source": "py -3.11"},
                   "venv": absent, "warnings": [], "missing": [], "toolkit_missing": [],
                   "ok": False, "deps": None}
        probes = iter([
            None,                                             # 建 venv 前没有探针结果
            {"runtime_missing": ["litellm"], "toolkit_missing": [], "self_version": None},
            {"runtime_missing": [], "toolkit_missing": [], "self_version": "0.44.3"},
        ])
        with mock.patch.object(bootstrap, "diagnose", side_effect=[started, healthy]), \
                mock.patch.object(bootstrap, "venv_state", return_value=ready), \
                mock.patch.object(bootstrap, "probe_environment", side_effect=lambda *a, **k: next(probes)), \
                mock.patch.object(bootstrap, "_run",
                                  return_value=subprocess.CompletedProcess(["py"], 0, "", "")), \
                mock.patch.object(bootstrap, "_pip_install",
                                  return_value={"ok": True, "mirror": bootstrap.MIRRORS[0],
                                                "attempts": [{"mirror": bootstrap.MIRRORS[0],
                                                              "code": 0, "seconds": 1.0}]}):
            result = bootstrap.fix(self.root)
        self.assertTrue(result["ok"])
        self.assertEqual(result["attempts"][0]["mirror"], bootstrap.MIRRORS[0])

    def test_install_failure_stops_with_reason(self) -> None:
        venv = {"path": "x", "exists": True, "version": "3.11.6", "has_pip": True}
        started = {"python": {"path": "x", "version": "3.11.6", "source": "venv"},
                   "venv": venv, "warnings": [], "missing": ["litellm"],
                   "toolkit_missing": [], "ok": False, "deps": None}
        with mock.patch.object(bootstrap, "diagnose", return_value=started), \
                mock.patch.object(bootstrap, "probe_environment",
                                  return_value={"runtime_missing": ["litellm"],
                                                "toolkit_missing": [], "self_version": None}), \
                mock.patch.object(bootstrap, "_pip_install",
                                  return_value={"ok": False, "mirror": None, "attempts": []}):
            result = bootstrap.fix(self.root)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "install-failed")

    def test_broken_venv_needs_recreate(self) -> None:
        broken = {"path": "x", "exists": True, "version": None, "has_pip": False}
        started = {"python": {"path": "x", "version": "3.11.6", "source": "venv"},
                   "venv": broken, "warnings": [], "missing": [], "toolkit_missing": [],
                   "ok": False, "deps": None}
        with mock.patch.object(bootstrap, "diagnose", return_value=started):
            result = bootstrap.fix(self.root)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "venv-broken")


class CliTests(unittest.TestCase):
    def test_json_flag_emits_single_parseable_line(self) -> None:
        healthy = {"root": "r", "platform": "p", "python": None,
                   "venv": {"exists": False}, "deps": None, "missing": [],
                   "toolkit_missing": [], "warnings": [], "tmp": "t", "port": 8010,
                   "ok": True}
        with mock.patch.object(bootstrap, "diagnose", return_value=healthy), \
                mock.patch("sys.stdout") as out:
            code = bootstrap.main(["--json"])
        self.assertEqual(code, 0)
        payload = "".join(call.args[0] for call in out.write.call_args_list)
        self.assertEqual(json.loads(payload.strip())["ok"], True)


if __name__ == "__main__":
    unittest.main()
