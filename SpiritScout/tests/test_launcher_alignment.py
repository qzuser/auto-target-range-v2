"""启动脚本与当前源码的对齐：入口命令、CLI 参数、依赖清单、端口口径、版本横幅。

为什么单列一条：仓库根那几个脚本由双击/计划任务直接跑，不经过任何构建。源码一改
（新增运行依赖、重命名 CLI 参数、换默认端口），它们不会自己跟着变，出问题时看到的是
「双击起不来」或「起来了但跑的是旧代码」，比一次失败的单元测试贵得多。这里把这类
漂移变成测试失败。
"""

from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path

from spiritscout import __version__
from spiritscout.__main__ import _banner, build_parser

ROOT = Path(__file__).resolve().parents[1]        # SpiritScout/
REPO = ROOT.parent                                # 仓库根：启动脚本与 README 在这层


def read(path: Path) -> str:
    """按 UTF-8 读脚本：cmd/ps1 带 BOM，sh 不带，都按 utf-8-sig 吃下去。"""
    return path.read_text(encoding="utf-8-sig")


def cli_flags(text: str) -> set[str]:
    """脚本里**显式**传给 `-m spiritscout` 的参数名。

    只看含 `-m spiritscout` 的行：启动器自己的开关（launch.sh 的 `--force`、
    `-h` 之类）不算，`"$@"` / `%*` 透传的东西静态看不出来，也跳过。
    """
    flags: set[str] = set()
    for line in text.splitlines():
        if "-m spiritscout" not in line:
            continue
        flags.update(re.findall(r"--[a-z][a-z0-9-]+", line))
    return flags


def dist_name(spec: str) -> str:
    """`mcp>=1.28.1,<2` → `mcp`；`pyyaml>=6.0` → `pyyaml`。"""
    return re.split(r"[<>=!~\[; ]", spec.strip(), maxsplit=1)[0].lower()


class LauncherAlignmentTests(unittest.TestCase):
    def setUp(self) -> None:
        # `_actions` 是 argparse 的稳定内部结构，这里只要全部选项字符串
        parser = build_parser()
        self.known = {opt for action in parser._actions for opt in action.option_strings}

    def test_launchers_only_pass_known_flags(self) -> None:
        for name in ("launch.cmd", "launch.sh"):
            with self.subTest(script=name):
                flags = cli_flags(read(ROOT / name))
                self.assertTrue(flags, f"{name} 里应当有传给 -m spiritscout 的参数")
                unknown = flags - self.known
                self.assertFalse(unknown, f"{name} 传了 CLI 不认的参数：{sorted(unknown)}")

    def test_local_launcher_still_sets_password_then_serves(self) -> None:
        """根启动器两步都要在：先 --set-admin-password --if-missing，再带 --port 起服务。"""
        flags = cli_flags(read(REPO / "start-local.ps1"))
        self.assertLessEqual({"--config", "--port", "--set-admin-password", "--if-missing"}, flags)
        self.assertFalse(flags - self.known)
        self.assertIn("--port $Port", read(REPO / "start-local.ps1"))

    def test_double_click_entry_and_docs_agree_on_port(self) -> None:
        entry = read(REPO / "启动服务.cmd")
        self.assertIn("start-local.ps1", entry)
        self.assertIn("-Port 8010", entry)
        self.assertRegex(read(REPO / "start-local.ps1"), r"\[int\]\$Port\s*=\s*8010")
        readme = read(REPO / "README.md")
        self.assertIn("127.0.0.1:8010", readme)
        # 配置里那个 8000 是给不带参的 launch.cmd/launch.sh 用的，别让文档说岔
        self.assertIn("8000", readme)

    def test_dependency_probe_covers_pyproject(self) -> None:
        """探针清单必须等于 pyproject 的运行时 / toolkit 依赖，否则启动器会漏装。"""
        config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        probe = read(ROOT / "scripts" / "probe_deps.py")
        runtime = re.search(r"RUNTIME = \[(.*?)\]", probe, re.S)
        toolkit = re.search(r"TOOLKIT = \[(.*?)\]", probe, re.S)
        self.assertIsNotNone(runtime, "probe_deps.py 里没有 RUNTIME 清单")
        self.assertIsNotNone(toolkit, "probe_deps.py 里没有 TOOLKIT 清单")
        probed_runtime = set(re.findall(r'"([A-Za-z0-9_.\-]+)"', runtime.group(1)))
        probed_toolkit = set(re.findall(r'"([A-Za-z0-9_.\-]+)"', toolkit.group(1)))
        expected_runtime = {dist_name(item) for item in config["project"]["dependencies"]}
        self.assertEqual(probed_runtime, expected_runtime,
                         "probe_deps.RUNTIME 与 pyproject dependencies 不一致")
        extras = config["project"].get("optional-dependencies", {})
        self.assertEqual(probed_toolkit, {dist_name(item) for item in extras.get("toolkit", [])},
                         "probe_deps.TOOLKIT 与 pyproject toolkit 不一致")

    def test_banner_prints_source_version(self) -> None:
        """启动横幅带版本：一眼确认接的是当前源码，而不是旧 venv 或旧包。"""
        text = _banner("127.0.0.1", 8010, "登录已关闭，本机直接进入（auth_mode=none）", 4)
        self.assertIn(f"v{__version__}", text)
        self.assertIn("http://127.0.0.1:8010", text)
        self.assertIn("并发上限 4", text)

    def test_local_launcher_reports_source_version(self) -> None:
        """启动器要把源码版本打出来（探针读 __init__.py，与 --version 同源）。"""
        text = read(REPO / "start-local.ps1")
        self.assertIn("deps.source_version", text)
        self.assertIn("源码版本", text)

    def test_readme_banner_sample_follows_version(self) -> None:
        """文档里贴的横幅示例也得跟着版本走，别再留一份旧号的输出。"""
        for name in ("README.md", "README_EN.md"):
            with self.subTest(file=name):
                self.assertIn(f"灵枢 Web 控制台 v{__version__}:", read(ROOT / name))


if __name__ == "__main__":       # pragma: no cover
    unittest.main()
