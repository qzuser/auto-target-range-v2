"""桌面版与环境自检：静态守护 + 几条真跑的行为测试。

桌面版是 C#（Windows 自带 csc 编译），跑不了单元测试，所以这里守两件事：

1. **行为约束**：真去跑 `scripts/bootstrap.py --json`，确认它能给出结构化结果、
   退出码与 `ok` 一致——GUI 与启动脚本都靠这个契约判断「环境能不能用」。
2. **回归陷阱**：把踩过的坑写成断言。`Assembly.LoadFrom`（同步目录/网络盘上会抛
   0x80131515 导致内嵌浏览器起不来）、把 WebView2 构造写进窗体字段、在进程流上混用
   同步与异步读——这三样都真出过问题，谁改回去这里就该红。
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
DESKTOP_CS = PACKAGE / "launcher" / "SpiritScoutDesktop.cs"
BUILD_PS1 = PACKAGE / "launcher" / "build-desktop.ps1"
BOOTSTRAP = PACKAGE / "scripts" / "bootstrap.py"


class DesktopSourceTests(unittest.TestCase):
    """看源码：这几处写法直接对应线上会翻车的场景。"""

    @classmethod
    def setUpClass(cls) -> None:
        if not DESKTOP_CS.is_file():
            raise unittest.SkipTest("桌面版源码不在这个包里（release 的 wheel 不带 launcher/）")
        cls.text = DESKTOP_CS.read_text(encoding="utf-8")

    def test_assemblies_load_from_bytes_not_path(self) -> None:
        # LoadFrom 在同步目录 / 网络盘上会被 CLR 判成「从网络位置加载」并抛 0x80131515
        self.assertIn("Assembly.Load(File.ReadAllBytes", self.text)
        self.assertNotIn("Assembly.LoadFrom(", self.text)

    def test_webview_creation_is_isolated_and_guarded(self) -> None:
        # 引用 WebView2 类型的语句集中在 CreateWebView 里，DLL 缺了才 catch 得住
        self.assertIn("private Control CreateWebView()", self.text)
        self.assertIn("catch (Exception ex)", self.text)
        self.assertIn("EnsureCoreWebView2Async", self.text)
        self.assertIn("NavigationCompleted", self.text)

    def test_has_three_level_fallback_for_extraction(self) -> None:
        self.assertIn("灵枢桌面版-lib", self.text)
        self.assertIn("SpiritScout-lib", self.text)
        self.assertIn("ResolveLibDir", self.text)

    def test_process_streams_are_read_one_way(self) -> None:
        # 同一条流既 BeginReadLine 又 ReadToEnd 会抛「不能混合同步操作和异步操作」
        capture = self.text.split("private async Task<CaptureResult> CaptureAsync", 1)[1]
        capture = capture.split("/// <summary>把 bootstrap", 1)[0]
        self.assertNotIn("BeginOutputReadLine", capture)
        self.assertNotIn("BeginErrorReadLine", capture)
        self.assertIn("StandardOutput.ReadToEnd()", capture)

    def test_server_is_stopped_as_a_tree(self) -> None:
        self.assertIn("taskkill", self.text)
        self.assertIn("/t /f", self.text)

    def test_has_edge_fallback_and_crash_report(self) -> None:
        self.assertIn("--app=", self.text)
        self.assertIn("crash-", self.text)
        self.assertIn("UnhandledException", self.text)


class DesktopBuildScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        if not BUILD_PS1.is_file():
            raise unittest.SkipTest("编译脚本不在这个包里")
        self.raw = BUILD_PS1.read_bytes()
        self.text = self.raw.decode("utf-8-sig")

    def test_saved_with_bom_for_windows_powershell(self) -> None:
        # 无 BOM 时 Windows PowerShell 5.1 会把中文读成乱码，并把它后面的引号拆坏
        self.assertEqual(self.raw[:3], b"\xef\xbb\xbf")

    def test_pins_webview2_sdk_and_embeds_resources(self) -> None:
        self.assertRegex(self.text, r"SdkVersion\s*=\s*'1\.0\.2903\.40'|SdkVersion\s*=\s*''")
        for res in ("wv2.core", "wv2.winforms", "wv2.loader"):
            self.assertIn("/resource:", self.text)
            self.assertIn(res, self.text)

    def test_rejects_stale_instance_and_reports_csc_output(self) -> None:
        self.assertIn("Stop-Process", self.text)
        self.assertIn("$compileLog", self.text)

    def test_offline_mode_documented(self) -> None:
        self.assertIn("-SkipDownload", self.text)


class BootstrapCliTests(unittest.TestCase):
    """真跑一遍自检：GUI 与启动脚本都依赖这个 JSON 契约。"""

    @classmethod
    def setUpClass(cls) -> None:
        if not BOOTSTRAP.is_file():
            raise unittest.SkipTest("bootstrap.py 不在这个包里")

    def test_json_output_matches_exit_code(self) -> None:
        result = subprocess.run([sys.executable, str(BOOTSTRAP), "--json"],
                                capture_output=True, text=True, timeout=180,
                                encoding="utf-8", errors="replace")
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        self.assertTrue(lines, f"没有输出：{result.stderr}")
        payload = json.loads(lines[-1])
        for key in ("root", "python", "venv", "missing", "warnings", "ok"):
            self.assertIn(key, payload)
        self.assertEqual(result.returncode == 0, payload["ok"],
                         "退出码要和 ok 字段一致，否则调用方没法只靠一个判断")

    def test_help_lists_repair_flags(self) -> None:
        result = subprocess.run([sys.executable, str(BOOTSTRAP), "--help"],
                                capture_output=True, text=True, timeout=60,
                                encoding="utf-8", errors="replace")
        self.assertEqual(result.returncode, 0)
        for flag in ("--fix", "--toolkit", "--recreate", "--mirror"):
            self.assertIn(flag, result.stdout)


if __name__ == "__main__":
    unittest.main()
