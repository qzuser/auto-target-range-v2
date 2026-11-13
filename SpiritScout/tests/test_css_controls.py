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

    def test_shell_pages_carry_no_palette_of_their_own(self) -> None:
        # 颜色一个都不许写在页面里：全部来自构建时拼进来的控制台样式表，
        # 页面里出现十六进制色值就说明又在偷偷抄第二套。
        for name in ("splash.html", "error.html", "dialog.html"):
            page = read(SHELL / name)
            self.assertIn("{{SHELL_CSS}}", page, name)
            self.assertEqual(re.findall(r"#[0-9a-fA-F]{3,8}\b", page), [], f"{name} 里不该有硬编码颜色")

    def test_shell_style_layer_only_lays_out(self) -> None:
        layer = read(SHELL / "shell-pages.css")
        # 壳自己的那一层只摆位置，不重新定义令牌
        self.assertNotIn("--accent:", layer)
        self.assertNotIn("--bg:", layer)
        self.assertIn("body.shell", layer)
        self.assertIn("var(--accent)", layer)          # 用控制台的令牌
        self.assertIn("var(--line)", layer)
        self.assertIn("@media (max-width: 520px)", layer)
        self.assertIn("@media (max-height: 560px)", layer)
        # 按钮/输入框交给 base.css + polish.css，这里不许再写一套尺寸
        self.assertNotIn("min-height: 32px", layer)
        self.assertNotIn(".btn.primary {", layer)

    def test_password_dialog_is_a_form_not_a_console(self) -> None:
        page = read(SHELL / "dialog.html")
        self.assertIn('type="password"', page)
        self.assertIn("setpw", page)
        self.assertIn("window.ssResult", page)


class UsagePageFitTests(unittest.TestCase):
    """用量页十列宽表：得在自己那张卡里滚，窄屏还要收起派生列。"""

    def test_table_is_wrapped_in_its_own_scroller(self) -> None:
        js = read(STATIC / "js" / "usage.js")
        self.assertIn('class="u-table-wrap"', js)
        css = read(CSS / "views.css")
        self.assertIn(".u-table-wrap {", css)
        self.assertIn("overflow-x: auto", css)

    def test_narrow_screens_drop_derived_columns(self) -> None:
        css = read(CSS / "views.css")
        self.assertIn("@media (max-width: 1100px)", css)
        self.assertIn(".u-col-cache, .u-col-fresh { display: none; }", css)
        js = read(STATIC / "js" / "usage.js")
        self.assertIn("u-col-cache", js)
        self.assertIn("u-col-fresh", js)
        self.assertIn("u-narrow-note", js)

    def test_asset_versions_are_bumped(self) -> None:
        html = read(STATIC / "index.html")
        self.assertIn("views.css?v=20261111-usagefit", html)
        self.assertIn("usage.js?v=20261111-usagefit", html)


if __name__ == "__main__":
    unittest.main()


class ShellCssSyncTests(unittest.TestCase):
    """窗口壳的样式是构建时从控制台样式表拼出来的，不能各写各的。"""

    def test_build_composes_shell_css_from_console_stylesheets(self) -> None:
        script = read(SHELL.parent / "build-desktop.ps1")
        self.assertIn("'base.css'", script)
        self.assertIn("'polish.css'", script)
        self.assertIn("'shell-pages.css'", script)
        self.assertIn('"/resource:" + $shellCssPath + ",app.shellcss"', script)

    def test_shell_pages_are_filled_by_the_shell_stylesheet(self) -> None:
        source = read(SHELL.parent / "SpiritScoutDesktop.cs")
        self.assertIn("{{SHELL_CSS}}", source)
        self.assertIn("app.shellcss", source)
        self.assertIn("ReadShellCss(", source)

    def test_console_stylesheets_exist_where_the_build_expects(self) -> None:
        for name in ("base.css", "polish.css"):
            self.assertTrue((CSS / name).is_file(), name)


class PageChromeTests(unittest.TestCase):
    """用量/项目/经验/设置/本地工具 的页面骨架跟仪表盘、编队对齐。"""

    def test_section_15_unifies_page_head(self) -> None:
        css = read(CSS / "polish.css")
        self.assertIn("15. 页面骨架", css)
        self.assertIn(".usage-head h2, .resource-head h2, .exp-head h2, .lt-head h2, .set-card h2", css)
        self.assertIn("font-size: 19px; font-weight: 600", css)
        self.assertIn(".u-card { padding: 16px 18px; gap: 8px; }", css)
        self.assertIn(".u-card, .pfolder, .exp-history, .resource-catalog, .resource-chat,", css)
        self.assertIn("border-radius: 9px;", css)
        self.assertIn(".u-table-wrap { border-radius: 9px; }", css)
        self.assertIn(".card.acard, .home-mode-card { border-radius: 9px; }", css)

    def test_card_buttons_are_not_downgraded_by_the_control_layer(self) -> None:
        # 全局按钮圆角那条不能把整张卡（文件夹、智能体、模式卡）按 6px 处理
        css = read(CSS / "polish.css")
        self.assertIn(":not(.pfolder):not(.acard):not(.home-mode-card)", css)

    def test_section_14_breakpoints(self) -> None:
        css = read(CSS / "polish.css")
        self.assertIn("14. 自适应", css)
        # 中窄档必须有下限，否则会把 860 以下的单列覆盖回两列
        self.assertIn("@media (min-width: 861px) and (max-width: 1080px)", css)
        self.assertIn("@media (max-width: 860px)", css)
        self.assertIn("@media (max-width: 560px)", css)
        self.assertIn(".side > nav {\n    flex-direction: row;", css.replace("\r\n", "\n"))
        # 窄屏顶栏要留出设置/主题/退出，不然那几个按钮根本点不到
        self.assertIn(".side:not(.mobile-sessions-open) .side-foot { display: flex; }", css)

    def test_asset_version_is_bumped(self) -> None:
        html = read(STATIC / "index.html")
        self.assertIn("polish.css?v=20261112-pageless", html)


if __name__ == "__main__":
    unittest.main()
