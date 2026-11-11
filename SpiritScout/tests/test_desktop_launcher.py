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
        capture = capture.split("private string PickServerPython()", 1)[0]
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


PORTABLE_PS1 = PACKAGE / "launcher" / "build-portable.ps1"


class PortableBundleTests(unittest.TestCase):
    """便携版打包脚本：内嵌解释器 + 依赖 + 配置模板，双击就能用的那份。"""

    @classmethod
    def setUpClass(cls) -> None:
        if not PORTABLE_PS1.is_file():
            raise unittest.SkipTest("便携版脚本不在这个包里（release 的 wheel 不带 launcher/）")
        cls.raw = PORTABLE_PS1.read_bytes()
        cls.text = cls.raw.decode("utf-8-sig")

    def test_script_is_utf8_bom(self) -> None:
        # PowerShell 5.1 按 GBK 读不带 BOM 的 .ps1，中文注释会把脚本读崩
        self.assertTrue(self.raw.startswith(b"\xef\xbb\xbf"))

    def test_embeddable_runtime_gets_site_packages(self) -> None:
        # embeddable 包默认不加载 site-packages：不补 ._pth 的话 import 全是 ModuleNotFoundError
        self.assertIn("._pth", self.text)
        self.assertIn("import site", self.text)
        self.assertIn('Lib\\site-packages', self.text)
        self.assertIn("get-pip.py", self.text)

    def test_desktop_json_points_at_embedded_python(self) -> None:
        self.assertIn("desktop.json", self.text)
        self.assertIn('"python": "py\\\\python.exe"', self.text)
        self.assertIn('"root": "."', self.text)

    def test_ships_templates_not_real_configs(self) -> None:
        # 真实 models.yaml / system.yaml 里有别人的渠道与密钥，包里只能放模板
        self.assertIn("system.example.yaml", self.text)
        self.assertIn("models.example.yaml", self.text)
        for leak in ("Copy-Config 'system.yaml'", "Copy-Config 'models.yaml'"):
            self.assertNotIn(leak, self.text)

    def test_smoke_checks_import(self) -> None:
        self.assertIn("import spiritscout", self.text)
        self.assertIn("启动灵枢.cmd", self.text)

    def test_can_build_without_network(self) -> None:
        # 内网/离线也能出包：解释器包与 get-pip.py 都允许走本地文件
        self.assertIn("-PythonZip", self.text)
        self.assertIn("-GetPip", self.text)


class PortableDesktopModeTests(unittest.TestCase):
    """exe 侧的便携模式：靠桌面目录里的 desktop.json 找解释器。"""

    @classmethod
    def setUpClass(cls) -> None:
        if not DESKTOP_CS.is_file():
            raise unittest.SkipTest("桌面版源码不在这个包里")
        cls.text = DESKTOP_CS.read_text(encoding="utf-8")

    def test_reads_desktop_json(self) -> None:
        self.assertIn("desktop.json", self.text)
        self.assertIn("JsonField", self.text)
        self.assertIn("ReadDesktopConfig", self.text)

    def test_portable_probe_skips_bootstrap(self) -> None:
        # 便携版/单文件版没有 scripts/bootstrap.py：依赖在打包时就装进内嵌解释器了，
        # 所以确认环境的路径是「直接问解释器能不能 import」，不能去跑 bootstrap。
        self.assertIn("if (python == null && !_portable)", self.text)
        self.assertIn("import sys, spiritscout", self.text)

    def test_repair_explains_itself_in_portable_mode(self) -> None:
        # 便携版坏了只有一条路：换整份目录重来（依赖跟包一起，没有 venv 可修）
        self.assertIn("_portable", self.text)
        self.assertIn("这个 exe 只是窗口壳", self.text)
SINGLE_PS1 = PACKAGE / "launcher" / "build-single.ps1"


class SingleFileBundleTests(unittest.TestCase):
    """单文件版：一个 exe 里挂着运行时，双击就能跑。"""

    @classmethod
    def setUpClass(cls) -> None:
        if not SINGLE_PS1.is_file():
            raise unittest.SkipTest("单文件脚本不在这个包里（release 的 wheel 不带 launcher/）")
        cls.raw = SINGLE_PS1.read_bytes()
        cls.text = cls.raw.decode("utf-8-sig")

    def test_script_is_utf8_bom(self) -> None:
        self.assertTrue(self.raw.startswith(b"\xef\xbb\xbf"))

    def test_trailer_is_eight_bytes(self) -> None:
        # 9 个字符的标记塞进 8 字节会把 CopyTo 撑爆（Array.CopyTo 越界），踩过
        self.assertIn("SSRTPAY1", self.text)
        self.assertNotIn("SSRT1PAY1", self.text)
        self.assertIn("New-Object byte[] 40", self.text)

    def test_trailer_carries_payload_hash(self) -> None:
        # 只记长度的话，下载被截断/拷坏的 exe 会解出一堆垃圾；带上 SHA-256 才能当场拒绝
        self.assertIn("SHA256", self.text)
        self.assertIn("$tailHash -ne $payloadHash", self.text)

    def test_verifies_size_and_trailer(self) -> None:
        # 拼完必须自己读回来核一遍：大小 = 桩 + 载荷 + 24，尾标里的长度也要对
        self.assertIn("$tailLen -ne $zipLen", self.text)
        self.assertIn('$tailMagic -ne', self.text)

    def test_uses_tar_with_compress_archive_fallback(self) -> None:
        self.assertIn("tar.exe", self.text)
        self.assertIn("Compress-Archive", self.text)

    def test_build_writes_and_ships_a_manifest(self) -> None:
        # 解出来的树要靠清单自证完整：少一个文件时先别写 .ready
        self.assertIn("runtime.manifest.tsv", self.text)
        self.assertIn('$manifestLines.Add', self.text)
        self.assertIn("'configs' 'runtime.manifest.tsv'", self.text)

    def test_smoke_runs_from_another_directory(self) -> None:
        # 冒烟要从空目录启动，才验得了「自己解运行时」这条路
        self.assertIn("$sandbox", self.text)
        self.assertIn("Start-Process", self.text)
        self.assertIn("内嵌运行时可用", self.text)


class SingleFileDesktopModeTests(unittest.TestCase):
    """exe 侧：读尾标、倒载荷、展 zip、认缓存。"""

    @classmethod
    def setUpClass(cls) -> None:
        if not DESKTOP_CS.is_file():
            raise unittest.SkipTest("桌面版源码不在这个包里")
        cls.text = DESKTOP_CS.read_text(encoding="utf-8")

    def test_reads_trailer_magic(self) -> None:
        self.assertIn("internal static class BundledRuntime", self.text)
        self.assertIn('private const string Marker = "SSRTPAY1"', self.text)
        self.assertIn("HasPayload", self.text)
        self.assertIn("ReadTrailer", self.text)

    def test_verifies_payload_hash_before_unpacking(self) -> None:
        self.assertIn("private const int TrailerSize = 40", self.text)
        self.assertIn("VerifyPayload", self.text)
        self.assertIn("SHA256", self.text)
        # 校验必须发生在展开之前：解一半才发现载荷坏掉，磁盘上就留个半成品目录
        self.assertLess(
            self.text.index("if (!VerifyPayload(zip, ReadExpectedHash(self)))"),
            self.text.index("Expand(zip, candidate);"),
        )

    def test_expands_with_tar_then_powershell(self) -> None:
        self.assertIn("tar.exe", self.text)
        self.assertIn("Expand-Archive", self.text)

    def test_cache_key_uses_length_and_fingerprint(self) -> None:
        # 只按长度做键，两个不同版本可能撞车；带上载荷指纹才分得开
        self.assertIn("Fingerprint", self.text)
        self.assertIn("\"SpiritScout\", \"runtime\", tag", self.text)
        self.assertIn("灵枢运行时-", self.text)

    def test_verifies_the_extracted_tree(self) -> None:
        self.assertIn('private const string ManifestName = "runtime.manifest.tsv"', self.text)
        self.assertIn("VerifyTree", self.text)
        self.assertIn("VerifyTree(candidate, out broken)", self.text)

    def test_ready_checks_sentinels_not_just_marker(self) -> None:
        # .ready 在、文件却被清理过：这种情况要能识别出来，否则首页直接 500
        self.assertIn('private const string ReadyMarker = ".ready"', self.text)
        self.assertIn('"knowledge", "seed.py"', self.text)
        self.assertIn('"data", "seed.json"', self.text)

    def test_damaged_runtime_is_re_extracted(self) -> None:
        self.assertIn("上次解出来的运行时缺文件，重解一遍", self.text)
        self.assertIn("if (File.Exists(Path.Combine(candidate, ReadyMarker)))", self.text)

    def test_new_runtime_adopts_previous_user_data(self) -> None:
        # 换版本会解到新目录；模型密钥/会话都在旧目录的 .spiritscout 里，得搬过来
        self.assertIn("AdoptUserData(candidate, progress);", self.text)
        self.assertIn('internal const string UserDataFolder = ".spiritscout";', self.text)
        self.assertIn("已把上一次的配置与数据带过来", self.text)

    def test_adoption_skips_when_new_dir_already_has_data(self) -> None:
        self.assertIn("Directory.GetFileSystemEntries(mine).Length > 0) { return; }", self.text)

    def test_adoption_failure_only_warns(self) -> None:
        self.assertIn("旧数据没搬全", self.text)
        self.assertIn("catch (UnauthorizedAccessException ex)", self.text)

    def test_single_file_failure_never_falls_into_portable_mode(self) -> None:
        # 解压失败后不能把 _singleFile 关掉：关了就会走 desktop.json 分支，
        # 弹出一句「desktop.json 指向的解释器不存在」，用户以为还得自己配环境
        self.assertIn("_runtimeBroken = true;", self.text)
        self.assertNotIn("_singleFile = false;   // 退到普通模式", self.text)
        self.assertIn('_failTitle = "运行时没解出来";', self.text)
        self.assertIn("ShowErrorPage(", self.text)

    def test_single_file_failure_offers_retry(self) -> None:
        # 重试不再是窗口上的按钮，而是错误页上的「重试」，点了重跑整条启动流程
        self.assertIn("if (_runtimeBroken) { return; }", self.text)
        self.assertIn('if (action == "retry")', self.text)
        self.assertIn("await UnpackBundledRuntimeAsync();", self.text)

    def test_child_python_ignores_host_python_env(self) -> None:
        # 宿主机的 PYTHONHOME/PYTHONPATH 会把内嵌解释器带歪（换台机器就炸的典型原因）
        for name in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP"):
            self.assertIn('psi.EnvironmentVariables.Remove("' + name + '");', self.text)
        self.assertIn('psi.EnvironmentVariables["PYTHONNOUSERSITE"] = "1";', self.text)

    def test_shell_exe_tells_user_to_grab_single_file_build(self) -> None:
        self.assertIn("这个 exe 只是窗口壳", self.text)
        self.assertIn("single-win64.exe", self.text)

    def test_readiness_check_skips_marker_before_it_is_written(self) -> None:
        # 解压完那一刻 .ready 还没写；这时按「必须带标记」判会白解三次
        self.assertIn("private static bool Ready(string dir, bool requireMarker)", self.text)
        self.assertIn("if (!Ready(candidate, false))", self.text)
        self.assertIn("if (Ready(candidate, true))", self.text)

    def test_extracts_before_showing_environment(self) -> None:
        index = self.text.index("await UnpackBundledRuntimeAsync();")
        self.assertLess(index, self.text.index("string python = await EnsureReadyAsync();"))
if __name__ == "__main__":
    unittest.main()

class DesktopShellUiTests(unittest.TestCase):
    """窗口的观感约定：打开就是控制台，没有工具栏/日志面板，也不能出现黑底。"""

    LAUNCHER = Path(__file__).resolve().parents[1] / "launcher"

    def _shell(self) -> str:
        return (self.LAUNCHER / "SpiritScoutDesktop.cs").read_text(encoding="utf-8-sig")

    def test_no_toolbar_or_log_panel_left(self) -> None:
        source = self._shell()
        for gone in ("_btnStart", "_btnStop", "_btnFix", "_logPanel", "_placeholder", "SetupButton("):
            self.assertNotIn(gone, source, f"{gone} 应该已经从窗口里拿掉了")

    def test_window_is_just_the_embedded_console(self) -> None:
        source = self._shell()
        self.assertIn("BuildLayout()", source)
        self.assertIn("canvas.Controls.Add(CreateWebView());", source)
        # 两次双击只开一个实例：WebView2 的用户数据目录是独占的
        self.assertIn('"SpiritScoutDesktop-single-instance"', source)

    def test_launch_starts_everything_without_clicks(self) -> None:
        source = self._shell()
        self.assertIn("await StartAppAsync();", source)          # OnLoaded 里直接跑
        self.assertIn("ShowSplash(", source)
        self.assertIn("await EnsureReadyAsync();", source)
        self.assertIn("await StartServerAsync(python);", source)

    def test_error_page_only_when_environment_is_broken(self) -> None:
        source = self._shell()
        self.assertIn("ShowErrorPage(", source)
        self.assertIn("HandleUiAction(payload)", source)   # 错误页/对话框的消息都从这里进
        # 只有失败分支才展示错误页
        before, _, after = source.partition("string python = await EnsureReadyAsync();")
        self.assertIn("if (python == null)", after)

    def test_no_black_background_anywhere(self) -> None:
        source = self._shell()
        for banned in ("Color.FromArgb(24, 26, 32)", "Color.FromArgb(18, 20, 25)", "Color.Black"):
            self.assertNotIn(banned, source, f"{banned} 会闪黑底")
        self.assertIn("DefaultBackgroundColor = Color.FromArgb(246, 247, 249)", source)

    def test_ui_pages_are_light_and_offline(self) -> None:
        # 三张页的底色/白卡片/蓝主色都跟控制台同一套令牌（#f6f8fa / #0969da）
        for name in ("splash.html", "error.html", "dialog.html"):
            html = (self.LAUNCHER / "ui" / name).read_text(encoding="utf-8")
            self.assertIn("#f6f8fa", html, name)
            self.assertIn("#0969da", html, name)
            for remote in ("http://", "https://", "//cdn"):
                self.assertNotIn(remote, html, f"{name} 不该联网取资源")
        splash = (self.LAUNCHER / "ui" / "splash.html").read_text(encoding="utf-8")
        self.assertIn("{{STATUS}}", splash)
        error = (self.LAUNCHER / "ui" / "error.html").read_text(encoding="utf-8")
        for slot in ("{{TITLE}}", "{{LEAD}}", "{{DETAIL}}"):
            self.assertIn(slot, error)

    def test_build_embeds_the_ui_pages(self) -> None:
        script = (self.LAUNCHER / "build-desktop.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("'splash.html', 'error.html', 'dialog.html'", script)
        self.assertIn('"/resource:" + $pagePath + "," + $page', script)

    def test_password_is_set_inside_the_window(self) -> None:
        """设密码不许再弹一个黑色控制台让人瞎输——走窗口里的表单。"""
        source = self._shell()
        self.assertNotIn("cmd.exe", source)
        self.assertNotIn('"/k ', source)
        self.assertIn("ReadUiHtml(\"dialog.html\")", source)
        self.assertIn("--set-admin-password --password-stdin", source)
        self.assertIn("RunWithInputAsync(", source)
        self.assertIn("PushDialogResult(", source)
        self.assertIn("ExecuteScriptAsync(", source)

    def test_smoke_run_never_touches_the_user_profile(self) -> None:
        """构建冒烟不能跟用户开着的窗口抢 WebView2 的 profile（会报 0x800700AA）。"""
        source = self._shell()
        self.assertIn("SPIRITSCOUT_WEBVIEW_DIR", source)
        self.assertIn("!created && !smoke", source)        # 冒烟不参与单实例
        script = (self.LAUNCHER / "build-desktop.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("$env:SPIRITSCOUT_WEBVIEW_DIR = $smokeProfile", script)
        self.assertIn("SPIRITSCOUT_SMOKE_MARK", script)      # 冒烟靠标记文件确认，不猜日志路径
        self.assertIn("smoke-ok.txt", script)

    def test_shortcuts_reach_the_window_from_inside_the_page(self) -> None:
        """焦点在网页里时窗体收不到按键，所以快捷键是注入脚本转成消息的。"""
        source = self._shell()
        self.assertIn("AddScriptToExecuteOnDocumentCreatedAsync", source)
        self.assertIn("send('pw')", source)
        self.assertIn("send('reload')", source)
        self.assertIn('action == "pw"', source)
        self.assertIn('action == "reload"', source)

    def test_broken_browser_profile_heals_itself(self) -> None:
        source = self._shell()
        self.assertIn("QuarantineProfile(", source)      # 挪走坏 profile
        self.assertIn("RecreateWebView()", source)       # 重建控件（失败过的控件没法再初始化）
        self.assertIn("SpiritScout-webview2-", source)   # 最后退到独立目录

    def test_leftover_server_from_a_crash_is_reaped(self) -> None:
        source = self._shell()
        self.assertIn("KillStaleServer();", source)
        self.assertIn("WriteServerPid(", source)
        self.assertIn("ClearServerPid(", source)
