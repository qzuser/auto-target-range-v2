"""主界面收敛为主功能项，其余收进「设置」独立界面。

用户把导航要求说死过：主界面只留任务 / 仪表盘 / 编队 / 项目这类日常入口，模型、
MCP、Skill 都进设置，而且设置要单开一个界面，不是弹窗。经验提炼后来又被点名从
设置里挪出来——它是天天要看的东西，不该埋在设置里。

这条要求很容易在后续改动里被悄悄破坏——多插一个 ``data-nav``、把某个视图挪回顶层、
或者图省事换成 ``<dialog>``，用户都得重新提一次。这里把结构钉住：

* 主侧栏的 ``data-nav`` 恰好是这几项，且顺序固定；
* ``#view-settings`` 是 ``<main>`` 里的普通 ``<section>``，不是 ``<dialog>``；
* 设置分类里的每个面板都在 ``#view-settings`` 子树内；
* 主界面的各项在 ``#view-settings`` 子树**外**；
* 前端 ``SET_TABS`` 与页面上的分类按钮一一对应，两边不准走散。
"""

from __future__ import annotations

import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "spiritscout" / "web" / "static"
INDEX = STATIC / "index.html"
CORE = STATIC / "js" / "core.js"

MAIN_NAV = ["home", "dash", "agents", "projects", "exp"]
SET_TABS = ["models", "mcp", "skill", "about"]
SET_PANEL_IDS = ["view-models", "view-mcp", "view-skill", "view-about"]
VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
    "param", "source", "track", "wbr", "path", "circle", "rect", "line", "polygon",
    "polyline", "ellipse", "stop", "use",
}


class _Tree(HTMLParser):
    """记下每个元素 id 的祖先链，用来判断「某面板是否在设置子树内」。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, str | None]] = []
        self.parents: dict[str, list[str]] = {}
        self.ancestors: dict[str, list[str]] = {}
        self.tags: dict[str, str] = {}
        self.attrs_by_id: dict[str, dict[str, str]] = {}

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in VOID:
            return
        mapping = dict(attrs)
        node_id = mapping.get("id")
        if node_id:
            self.parents[node_id] = [name for name, _ in self.stack]
            self.ancestors[node_id] = [nid for _, nid in self.stack if nid]
            self.tags[node_id] = tag
            self.attrs_by_id[node_id] = mapping
        self.stack.append((tag, node_id))

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID:
            return
        if self.stack:
            self.stack.pop()


def _parse() -> tuple[_Tree, str]:
    html = INDEX.read_text(encoding="utf-8")
    tree = _Tree()
    tree.feed(html)
    return tree, html


class MainNavigationTests(unittest.TestCase):
    def test_sidebar_has_exactly_the_four_primary_entries(self) -> None:
        _, html = _parse()
        nav_block = re.search(r"<nav>(.*?)</nav>", html, re.S)
        self.assertIsNotNone(nav_block, "侧栏 <nav> 不见了")
        found = re.findall(r'data-nav="([a-z]+)"', nav_block.group(1))
        self.assertEqual(found, MAIN_NAV, f"主侧栏应只有 {MAIN_NAV}，实际 {found}")

    def test_moved_views_are_no_longer_primary_nav_entries(self) -> None:
        _, html = _parse()
        nav_block = re.search(r"<nav>(.*?)</nav>", html, re.S)
        assert nav_block is not None
        for gone in ("models", "mcp", "skill"):
            self.assertNotIn(
                f'data-nav="{gone}"', nav_block.group(1),
                f"{gone} 已经收进设置，不该再占主侧栏的位置",
            )

    def test_experience_is_back_in_the_primary_nav(self) -> None:
        """经验提炼被点名从设置里挪了出来，它得有自己的侧栏入口。"""
        tree, html = _parse()
        nav_block = re.search(r"<nav>(.*?)</nav>", html, re.S)
        assert nav_block is not None
        self.assertIn('data-nav="exp"', nav_block.group(1), "经验提炼应回到主侧栏")
        self.assertNotIn('data-set="exp"', html, "经验提炼不该再挂在设置分类里")
        self.assertNotIn("view-settings", tree.ancestors["view-exp"],
                         "#view-exp 应自成顶层视图，不在设置子树内")

    def test_settings_entry_lives_in_the_sidebar_footer(self) -> None:
        tree, _ = _parse()
        self.assertIn("btn-settings", tree.parents, "侧栏底部缺设置入口")
        self.assertNotIn(
            "nav", tree.parents["btn-settings"],
            "设置入口应放在 nav 之外——主侧栏只承担四个功能项",
        )


class SettingsSurfaceTests(unittest.TestCase):
    def test_settings_is_a_section_not_a_dialog(self) -> None:
        tree, _ = _parse()
        self.assertIn("view-settings", tree.tags, "缺 #view-settings 视图容器")
        self.assertEqual(
            tree.tags["view-settings"], "section",
            "设置要单开一个界面：应是普通 section 视图，不是 dialog 弹窗",
        )
        self.assertIn("main", tree.parents["view-settings"], "设置应是主区里的顶层视图")

    def test_every_settings_panel_sits_inside_the_settings_view(self) -> None:
        tree, _ = _parse()
        for panel in SET_PANEL_IDS:
            self.assertIn(panel, tree.ancestors, f"缺设置面板 #{panel}")
            self.assertIn(
                "view-settings", tree.ancestors[panel],
                f"#{panel} 应在 #view-settings 之内，实际祖先 {tree.ancestors[panel]}",
            )

    def test_primary_views_stay_outside_settings(self) -> None:
        tree, _ = _parse()
        for vid in ("view-home", "view-dash", "view-agents", "view-projects", "view-exp"):
            self.assertIn(vid, tree.ancestors, f"缺主视图 #{vid}")
            self.assertNotIn(
                "view-settings", tree.ancestors[vid],
                f"#{vid} 属于主界面，不该被塞进设置",
            )

    def test_settings_tabs_cover_every_moved_feature(self) -> None:
        _, html = _parse()
        found = re.findall(r'data-set="([a-z]+)"', html)
        self.assertEqual(found, SET_TABS, f"设置分类应覆盖 {SET_TABS}，实际 {found}")


class SettingsRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.js = CORE.read_text(encoding="utf-8")

    def test_settings_view_is_registered(self) -> None:
        self.assertRegex(
            self.js, r"settings:\s*\"#view-settings\"",
            "core.js 的 VIEWS 没登记 settings",
        )

    def test_panel_map_matches_the_markup(self) -> None:
        block = re.search(r"const SET_TABS = \{(.*?)\};", self.js, re.S)
        self.assertIsNotNone(block, "core.js 缺 SET_TABS 定义")
        pairs = dict(re.findall(r"(\w+):\s*\"(#[\w-]+)\"", block.group(1)))
        self.assertEqual(list(pairs), SET_TABS, f"SET_TABS 分类应覆盖 {SET_TABS}")
        for key, selector in pairs.items():
            self.assertEqual(selector, f"#view-{key}")
        self.assertNotIn("exp", pairs, "经验提炼已回主界面，不该再算设置分类")

    def test_experience_is_routed_as_a_top_level_view(self) -> None:
        self.assertRegex(self.js, r'exp:\s*"#view-exp"',
                         "core.js 的 VIEWS 要登记 exp，主侧栏才切得过去")

    def test_show_routes_settings_panes_instead_of_hiding_everything(self) -> None:
        # show() 必须先判断是否落在设置分类里，再决定顶层显示哪个视图
        self.assertIn("const inSet = SET_TABS[view] !== undefined;", self.js)
        self.assertIn('k !== (inSet ? "settings" : view)', self.js,
                      "设置分类应点亮 #view-settings，其余按原名切换")

    def test_sidebar_button_reopens_last_settings_tab(self) -> None:
        self.assertRegex(
            self.js, r'#btn-settings"\)\.onclick[^\n]*show\(S\.setTab \|\| SET_FIRST\)',
            "设置入口应回到上次看的那一页",
        )


class TaskDockTests(unittest.TestCase):
    """后台任务坞：任务在跑而你没看着它时，得有个地方能找回来。

    用户提的是「为什么在后台运行了」——任务切走就彻底失联，界面上一声不吭。
    修法是左下角浮一条：「N 个任务在后台运行」，点开能看见每条状态并跳回去。
    它必须是全局浮层，一旦落在某个 ``#view-*`` 里，切视图就跟着没了。
    """

    def setUp(self) -> None:
        self.js = CORE.read_text(encoding="utf-8")

    def test_dock_sits_outside_every_view(self) -> None:
        tree, _ = _parse()
        self.assertIn("task-dock", tree.tags, "index.html 里没有 #task-dock")
        self.assertEqual(tree.tags["task-dock"], "section")
        views = [a for a in tree.ancestors["task-dock"] if a.startswith("view-")]
        self.assertEqual(views, [], f"任务坞不该挂在视图子树里，实际祖先 {views}")
        self.assertNotIn("main", tree.ancestors["task-dock"],
                         "任务坞是浮层，不该占 <main> 的栅格")
        self.assertIn("hidden", tree.attrs_by_id["task-dock"], "默认要收起")

    def test_dock_reports_count_and_toggle(self) -> None:
        tree, html = _parse()
        for node in ("dock-toggle", "dock-count", "dock-body"):
            self.assertIn(node, tree.tags, f"任务坞缺 #{node}")
        self.assertIn('aria-expanded="false"', html, "展开按钮要有初始折叠状态")
        self.assertIn('aria-controls="dock-body"', html, "展开按钮要指向正文容器")

    def test_dock_has_a_renderer_and_a_toggle_initialiser(self) -> None:
        for name in ("backgroundTasks", "renderTaskDock", "initTaskDock"):
            self.assertIn(f"function {name}(", self.js, f"core.js 缺 {name}")

    def test_dock_is_refreshed_on_route_and_list_changes(self) -> None:
        show_block = re.search(r"function show\(view\) \{(.*?)\n\}", self.js, re.S)
        self.assertIsNotNone(show_block, "core.js 找不到 show()")
        self.assertIn("renderTaskDock()", show_block.group(1),
                      "切视图会改变「哪些算在后台」，show() 里要重算")
        fetch_block = re.search(r"async function fetchSessions\(\) \{(.*?)\n\}", self.js, re.S)
        self.assertIsNotNone(fetch_block, "core.js 找不到 fetchSessions()")
        self.assertIn("renderTaskDock()", fetch_block.group(1),
                      "会话列表刷新后要跟着重算")
        self.assertIn("initTaskDock();", self.js, "启动时要绑一次展开按钮")

    def test_background_means_not_the_one_you_are_looking_at(self) -> None:
        # 「后台」= 未终结 且 不是当前视图正在看的那个会话
        self.assertRegex(
            self.js,
            r"function backgroundTasks\(\) \{\s*return S\.sessions\.filter\(s =>\s*"
            r"!TERMINAL\.has\(s\.status\) && !\(S\.view === \"session\" && s\.session_id === S\.cur\)",
            "backgroundTasks 的定义被改坏了：它应排除当前正在看的会话",
        )


if __name__ == "__main__":
    unittest.main()
