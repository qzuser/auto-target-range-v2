# -*- coding: utf-8 -*-
"""控件层：按钮和输入框在 web 端必须共用同一套几何与配色。

这是「按钮/输入框和 web 端对齐」的回归闸：设计令牌（高度、圆角、焦点圈）、
原生控件的重绘（select 箭头、checkbox/radio、file、range），以及散落在各
组件里的旧尺寸是否都被收回。纯文本断言，不需要浏览器。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CSS = REPO / "src" / "spiritscout" / "web" / "static" / "css"
SHELL = REPO / "launcher" / "ui"
STATIC = REPO / "src" / "spiritscout" / "web" / "static"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class ControlTokenTests(unittest.TestCase):
    """令牌：一个高度、一个圆角、一个焦点圈。"""

    def test_tokens_define_one_control_size(self) -> None:
        css = read(CSS / "polish.css")
        self.assertIn("--ctl-h: 32px", css)
        self.assertIn("--ctl-h-sm: 26px", css)
        self.assertIn("--ctl-ring:", css)
        self.assertIn("--radius-sm: 6px", css)

    def test_stylesheet_version_is_bumped(self) -> None:
        html = read(STATIC / "index.html")
        match = re.search(r"polish\.css\?v=([\w.-]+)", html)
        self.assertIsNotNone(match, "index.html 里没有 polish.css")
        self.assertNotEqual(match.group(1), "20261111-standard")


class ControlGeometryTests(unittest.TestCase):
    """几何：按钮不再是 7px/8px/9px 各一套。"""

    def test_buttons_share_one_radius(self) -> None:
        css = read(CSS / "polish.css")
        self.assertIn("button:not(.pill):not(.tag):not(.dot):not(.send-btn)", css)
        self.assertIn(":not(.send-btn)", css)          # 圆形发送键要留着
        for selector in ("#btn-settings", "#btn-theme", "#btn-logout", "#btn-new"):
            self.assertIn(selector, css)

    def test_inputs_and_selects_are_normalized(self) -> None:
        css = read(CSS / "polish.css")
        self.assertIn("min-height: var(--ctl-h)", css)
        self.assertIn("appearance: none", css)          # select 不再用系统箭头
        self.assertIn("--ctl-chevron", css)
        self.assertIn("file-selector-button", css)
        self.assertIn("var(--ctl-ring)", css)

    def test_checkbox_and_radio_are_redrawn(self) -> None:
        css = read(CSS / "polish.css")
        self.assertIn('input[type="checkbox"]', css)
        self.assertIn('input[type="radio"]', css)
        self.assertIn("clip-path: polygon", css)

    def test_legacy_control_sizes_are_reclaimed(self) -> None:
        css = read(CSS / "polish.css")
        for selector in (
            ".mission-settings select",
            ".cache-bar select",
            ".u-ops select",
            ".dash-filters select",
            ".acard .bind select",
            ".aw-toolbar button",
        ):
            self.assertIn(selector, css)

    def test_login_page_matches_console(self) -> None:
        css = read(CSS / "login.css")
        self.assertIn("var(--radius-sm", css)
        self.assertIn("box-shadow: 0 0 0 3px var(--accent-soft)", css)
        self.assertIn("login.css?v=", read(STATIC / "login.html"))


class ShellPageTests(unittest.TestCase):
    """外壳那三张页（启动、报错、密码）不另立一套配色。"""

    def test_shell_pages_use_web_palette(self) -> None:
        for name in ("splash.html", "error.html", "dialog.html"):
            page = read(SHELL / name)
            self.assertIn("--accent: #0969da", page, name)
            self.assertIn("--bg: #f6f8fa", page, name)
            self.assertIn("--radius-sm: 6px", page, name)
            self.assertNotIn("#1f883d", page, name)      # 旧的绿色主按钮
            self.assertNotIn("#b4510b", page, name)      # 旧的橙色告警
            # 琥珀色只剩启动页 logo 那一处（跟窗口图标/favicon 同一枚）
            if name == "splash.html":
                self.assertEqual(page.count("#a4681e"), 1, name)
                self.assertIn('fill="#a4681e"', page, name)
            else:
                self.assertNotIn("#a4681e", page, name)

    def test_shell_buttons_match_console_geometry(self) -> None:
        page = read(SHELL / "error.html")
        self.assertIn("min-height: 32px", page)
        self.assertIn("padding: 5px 12px", page)
        self.assertIn("font-size: 13px", page)
        self.assertIn("font-weight: 500", page)

    def test_password_dialog_is_a_form_not_a_console(self) -> None:
        page = read(SHELL / "dialog.html")
        self.assertIn('type="password"', page)
        self.assertIn("setpw", page)
        self.assertIn("window.ssResult", page)


if __name__ == "__main__":
    unittest.main()
