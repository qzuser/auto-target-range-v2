"""控制台图标：标签页图标与品牌图形。

图标是纯静态资产，最容易出的问题是"文件改了但没人引用""引用路径改名后 404"
"内联 SVG 忘了 aria-hidden 抢读屏"。这组测试盯住这些，顺带确认 SVG 本身能被
XML 解析——坏掉的 SVG 在浏览器里是静默的空白，很难靠肉眼发现。
"""
from __future__ import annotations

import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from fastapi.testclient import TestClient

from spiritscout.config.settings import SystemConfig, WorkspaceConfig
from spiritscout.web.app import create_app

STATIC = Path(__file__).resolve().parents[1] / "src/spiritscout/web/static"
SVG_NS = "{http://www.w3.org/2000/svg}"


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


class FaviconAssetTests(unittest.TestCase):
    def test_favicon_is_well_formed_svg(self) -> None:
        root = ET.fromstring(_read("favicon.svg"))
        self.assertEqual(root.tag, f"{SVG_NS}svg")
        self.assertEqual(root.get("viewBox"), "0 0 32 32")
        # 标签页图标不能执行脚本，也不该引用任何外部资源（此时网络可能不可用）
        text = _read("favicon.svg")
        self.assertNotIn("<script", text)
        self.assertNotIn("href", text)
        self.assertNotIn("<use", text)
        self.assertNotIn("<image", text)

    def test_favicon_has_a_label_for_hover_title(self) -> None:
        text = _read("favicon.svg")
        self.assertIn("<title>灵枢 SpiritScout</title>", text)
        self.assertIn('aria-label="灵枢 SpiritScout"', text)

    def test_favicon_served_over_http(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(SystemConfig(workspace=WorkspaceConfig(root=tmp)), [])
            with TestClient(app, base_url="http://127.0.0.1") as client:
                response = client.get("/static/favicon.svg")
                self.assertEqual(response.status_code, 200)
                self.assertIn("svg", response.headers["content-type"])
                self.assertIn("<svg", response.text)

    def test_login_page_can_load_favicon_before_signing_in(self) -> None:
        """登录页在未登录时就该有图标，静态资源不能被鉴权挡住。"""
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(SystemConfig(workspace=WorkspaceConfig(root=tmp)), [])
            with TestClient(app, base_url="http://127.0.0.1") as client:
                self.assertEqual(client.get("/login").status_code, 200)
                self.assertEqual(client.get("/static/favicon.svg").status_code, 200)


class PageReferenceTests(unittest.TestCase):
    def test_both_pages_link_the_favicon(self) -> None:
        for page in ("index.html", "login.html"):
            with self.subTest(page=page):
                html = _read(page)
                self.assertRegex(
                    html,
                    r'<link rel="icon"[^>]*type="image/svg\+xml"[^>]*href="/static/favicon\.svg',
                )

    def test_both_pages_declare_theme_color(self) -> None:
        for page in ("index.html", "login.html"):
            with self.subTest(page=page):
                html = _read(page)
                self.assertEqual(html.count('name="theme-color"'), 2)
                self.assertIn('content="#f6f8fa"', html)

    def test_brand_marks_are_inline_and_hidden_from_screen_readers(self) -> None:
        cases = (("index.html", "brand-mark"), ("login.html", "login-mark"))
        for page, klass in cases:
            with self.subTest(page=page):
                html = _read(page)
                self.assertIn(f'class="{klass}"', html)
                mark = re.search(rf'<svg class="{klass}".*?</svg>', html, re.S)
                self.assertIsNotNone(mark, f"{page} 里 {klass} 应该是内联 SVG")
                assert mark is not None
                self.assertIn('aria-hidden="true"', mark.group(0))
                self.assertIn('focusable="false"', mark.group(0))
                ET.fromstring(mark.group(0))     # 内联 SVG 同样要能解析

    def test_styles_colour_the_marks_with_the_theme_accent(self) -> None:
        self.assertRegex(_read("css/base.css"), r"\.brand-mark \{[^}]*var\(--accent\)")
        self.assertRegex(_read("css/login.css"), r"\.login-mark \{[^}]*var\(--accent\)")

    def test_stylesheet_versions_agree_across_pages(self) -> None:
        """同一个样式表在各页面必须用同一个 ?v= 串。

        以前这里写死了某个具体日期串，改一次 CSS 就得改一次测试，等于把测试
        变成绊脚石而不是防线。真正会出错的是「改了 index.html 忘了 login.html」
        ——两边版本串不一致，用户在另一个页面拿到旧样式。这条能自动判，且不用
        随每次改动维护。格式校验保证它仍是「日期-标记」的样子。
        """
        seen: dict[str, set[str]] = {}
        for page in ("index.html", "login.html"):
            html = _read(page)
            for sheet in ("base.css", "login.css"):
                for match in re.finditer(rf"{re.escape(sheet)}\?v=([\w-]+)", html):
                    version = match.group(1)
                    self.assertRegex(
                        version, r"^\d{8}-[\w-]+$",
                        f"{page} 的 {sheet} 版本串要写成 日期-标记（当前 {version}）")
                    seen.setdefault(sheet, set()).add(version)
        for sheet, versions in seen.items():
            self.assertEqual(len(versions), 1,
                             f"{sheet} 的版本串在各页面不一致：{sorted(versions)}")


if __name__ == "__main__":
    unittest.main()

class DesktopIconTests(unittest.TestCase):
    """桌面版图标必须是网页标签页那一个，不然用户以为装了另一套东西。

    这里盯三件事：icon.ico 存在且是多尺寸、颜色跟 favicon.svg 对得上、
    构建脚本真的把它塞进了 exe（/win32icon）。
    """

    LAUNCHER = Path(__file__).resolve().parents[1] / "launcher"

    def test_ico_is_shipped_and_multi_size(self) -> None:
        ico = self.LAUNCHER / "icon.ico"
        self.assertTrue(ico.exists(), "缺 launcher/icon.ico：跑 python launcher/make-icon.py 生成")
        self.assertGreater(ico.stat().st_size, 2000)
        from PIL import Image

        sizes = sorted(Image.open(ico).info.get("sizes", []))
        self.assertIn((16, 16), sizes)
        self.assertIn((256, 256), sizes)
        self.assertGreaterEqual(len(sizes), 5)

    def test_ico_colors_match_the_web_favicon(self) -> None:
        import re

        from PIL import Image

        svg = _read("favicon.svg")
        bg = re.search(r'<rect[^>]*fill="([^"]+)"', svg)
        stroke = re.search(r'<g[^>]*stroke="([^"]+)"', svg)
        self.assertIsNotNone(bg)
        self.assertIsNotNone(stroke)
        image = Image.open(self.LAUNCHER / "icon.ico")
        image.size = (256, 256)
        image.load()
        pixels = image.convert("RGBA")

        def rgb(value: str) -> tuple[int, int, int]:
            return tuple(int(value[i : i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]

        self.assertEqual(pixels.getpixel((128, 24))[:3], rgb(bg.group(1)))
        self.assertEqual(pixels.getpixel((128, 128))[:3], rgb(stroke.group(1)))
        self.assertEqual(pixels.getpixel((1, 1))[3], 0, "圆角外应该是透明的")

    def test_generator_can_parse_the_current_svg(self) -> None:
        import importlib.util

        spec = importlib.util.spec_from_file_location("make_icon", self.LAUNCHER / "make-icon.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        shapes = module.parse(_read("favicon.svg"))
        self.assertEqual(len(shapes["dots"]), 4)
        self.assertEqual(len(shapes["lines"]), 3)
        self.assertAlmostEqual(float(shapes["radius"]), 7.5)

    def test_build_embeds_the_icon(self) -> None:
        script = (self.LAUNCHER / "build-desktop.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("/win32icon:", script)
        self.assertIn("icon.ico", script)
        self.assertIn("$iconArgs", script)
    def test_window_sets_its_own_icon(self) -> None:
        # WinForms 不会自动用 exe 里那份图标，不显式设就一直是通用图标
        source = (self.LAUNCHER / "SpiritScoutDesktop.cs").read_text(encoding="utf-8-sig")
        self.assertIn("ApplyAppIcon();", source)
        self.assertIn('GetManifestResourceStream("app.icon")', source)
        self.assertIn("Icon.ExtractAssociatedIcon(Application.ExecutablePath)", source)

    def test_build_embeds_the_icon_as_a_resource_too(self) -> None:
        script = (self.LAUNCHER / "build-desktop.ps1").read_text(encoding="utf-8-sig")
        self.assertIn('"/resource:" + $iconPath + ",app.icon"', script)
