"""Flag 页的复制按钮：结构上钉住「每条都有按钮、值可复制、样式在」。

行为（走 clipboard / 退回 execCommand / 反馈文案）由 ``tests/test_flag_copy.js``
在桩 DOM 上验真实实现，这里只管源码里该有的东西没被后续改动顺手删掉——
比如重排 flag 卡片时把按钮连着 ``data-flag`` 一起丢了，或者忘了给它配样式。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "spiritscout" / "web" / "static"
VIEWS_JS = STATIC / "js" / "views.js"
VIEWS_CSS = STATIC / "css" / "views.css"
INDEX = STATIC / "index.html"


class FlagCopyMarkupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.js = VIEWS_JS.read_text(encoding="utf-8")

    def test_copy_helpers_exist(self) -> None:
        for name in ("copyText", "copyFlagByIndex", "renderFlags"):
            self.assertIn(f"function {name}(" if name != "copyText" else "async function copyText(",
                          self.js, f"views.js 缺 {name}")

    def test_every_card_renders_a_copy_button_with_its_index(self) -> None:
        block = re.search(r"function renderFlags\(\) \{(.*?)\n\}", self.js, re.S)
        self.assertIsNotNone(block, "views.js 找不到 renderFlags()")
        body = block.group(1)
        self.assertIn('class="flag-copy"', body, "flag 卡片里没有复制按钮")
        self.assertIn('data-flag="${i}"', body,
                      "按钮要带下标：不带的话点了不知道该复制哪一条")
        self.assertIn("querySelectorAll(\".flag-copy\")", body,
                      "渲染完要把按钮都绑上点击")

    def test_copy_button_sits_in_the_footer_not_on_the_value(self) -> None:
        # 值那行是等宽字体的长串，按钮压上去会挡住内容；放 footer 那行才对
        self.assertIn('<div class="flag-foot">', self.js)
        self.assertIn(".flag-foot", VIEWS_CSS.read_text(encoding="utf-8"))


class FlagCopyStyleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.css = VIEWS_CSS.read_text(encoding="utf-8")

    def test_button_styles_are_present(self) -> None:
        for sel in (".flag-copy", ".flag-copy:hover", ".flag-copy.copied", ".flag-chal"):
            self.assertIn(sel, self.css, f"views.css 缺 {sel}")

    def test_copied_state_is_visually_distinct(self) -> None:
        block = re.search(r"\.flag-copy\.copied \{(.*?)\}", self.css, re.S)
        self.assertIsNotNone(block, "没有 .flag-copy.copied 这条")
        self.assertIn("var(--ok)", block.group(1),
                      "复制成功该用成功色，不然用户看不出点了有没有效果")


class FlagViewWiringTests(unittest.TestCase):
    def test_views_script_is_cache_busted_past_the_copy_feature(self) -> None:
        html = INDEX.read_text(encoding="utf-8")
        tag = re.search(r'src="/static/js/views\.js\?v=([\w-]+)"', html)
        self.assertIsNotNone(tag, "index.html 没引 views.js")
        self.assertNotIn("20261029-wp", tag.group(1),
                         "views.js 换了内容，缓存标记没跟着换——浏览器会拿旧的")

    def test_flag_panel_is_still_a_tab(self) -> None:
        html = INDEX.read_text(encoding="utf-8")
        self.assertIn('data-tab="flags"', html, "Flag 不再是会话里的一个标签页")
        self.assertIn('id="tab-flags"', html, "缺 #tab-flags 容器")


if __name__ == "__main__":
    unittest.main()
