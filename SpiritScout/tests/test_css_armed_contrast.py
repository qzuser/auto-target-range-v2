"""两段式确认按钮（armed 态）的可读性：悬停时字必须还看得见。

`armConfirm` 给按钮加 `.armed` 并把文字换成「删除?」，靠一段红色底白字让
用户看清"这一下是真删"。但 `.armed` 只是两个类，`… button.danger:hover`
之类的危险态悬停规则权重更高——它们会把底色换回 `--bad-soft`（9% 透明）
或把字色改回红，于是按钮悬停时只剩一片红、字消失了。

这个测试把 CSS 真的按层叠规则算一遍：找出所有匹配的声明，取权重最高的
一条，然后用 WCAG 对比度判断"字还看得见吗"。它盯的是四条真实存在的路径：
会话列表的 ✕、项目/会话页的「删除」、删除项目、经验条目的「删除」。
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import NamedTuple

CSS_DIR = Path(__file__).resolve().parents[1] / "src" / "spiritscout" / "web" / "static" / "css"
# 加载顺序与页面一致：base 打底，其余按前缀细化
SHEETS = ("base.css", "views.css", "projects.css", "resources.css")
# 悬停态的对比度底线（WCAG 对大字号/粗体按钮的门槛是 3:1）
MIN_CONTRAST = 3.0


class Compound(NamedTuple):
    tag: str
    classes: frozenset[str]
    states: frozenset[str]


def _strip_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def _iter_rules(text: str):
    """逐条吐出 (selector, decls)。@media 块内部也展开——里面的规则同样参与层叠。"""
    depth = 0
    buf = ""
    selector = ""
    for ch in text:
        if ch == "{":
            depth += 1
            if depth == 1:
                selector = buf.strip()
                buf = ""
                continue
        elif ch == "}":
            depth -= 1
            if depth == 0:
                decls = _parse_decls(buf)
                if selector and not selector.startswith("@"):
                    yield selector, decls
                elif selector.startswith("@media"):
                    # 媒体查询里的规则照常参与（我们按"最坏情况"取它们）
                    yield from _iter_rules(buf)
                buf = ""
                continue
        buf += ch


def _parse_decls(body: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in body.split(";"):
        if ":" not in part:
            continue
        prop, _, value = part.partition(":")
        out[prop.strip().lower()] = value.strip()
    return out


def _compound(sel: str) -> Compound | None:
    """把一个复合选择器解析成 标签 + 类 + 状态伪类；含不认识的语法时放弃。"""
    if any(tok in sel for tok in (":not(", ":has(", ":is(", "::", ">", "+", "~", "[")):
        return None
    tag = ""
    classes: set[str] = set()
    states: set[str] = set()
    for tok in re.findall(r"[.#:]?[A-Za-z0-9_-]+|:", sel):
        if tok.startswith("."):
            classes.add(tok[1:])
        elif tok.startswith(":"):
            states.add(tok.lstrip(":"))
        elif tok == "*":
            continue
        else:
            tag = tok
    return Compound(tag, frozenset(classes), frozenset(states))


def _chain(selector: str) -> list[Compound] | None:
    parts = [p for p in re.split(r"\s+", selector.strip()) if p]
    out = []
    for part in parts:
        comp = _compound(part)
        if comp is None:
            return None
        out.append(comp)
    return out


def _matches_one(comp: Compound, tag: str, classes: frozenset[str], states: frozenset[str]) -> bool:
    if comp.tag and comp.tag != tag:
        return False
    if not comp.classes <= classes:
        return False
    known = {"hover", "active", "focus-visible", "focus", "disabled"}
    return (comp.states & known) <= states


def _matches(sel: str, ancestors: list[tuple[str, frozenset[str]]],
             element: tuple[str, frozenset[str]], states: frozenset[str]) -> bool:
    chain = _chain(sel)
    if not chain:
        return False
    rest = list(chain)
    target = rest.pop()
    if not _matches_one(target, element[0], element[1], states):
        return False
    # 其余部分按顺序在祖先链里找（从近到远）
    pool = list(reversed(ancestors))
    for comp in reversed(rest):
        found = False
        while pool:
            tag, classes = pool.pop(0)
            if _matches_one(comp, tag, classes, states):
                found = True
                break
        if not found:
            return False
    return True


def _specificity(sel: str) -> tuple[int, int, int]:
    ids = len(re.findall(r"#[A-Za-z0-9_-]+", sel))
    classes = len(re.findall(r"\.[A-Za-z0-9_-]+", sel))
    pseudos = len(re.findall(r":[A-Za-z-]+", sel))
    tags = len(re.findall(r"(?:^|[\s>+~])([A-Za-z][A-Za-z0-9-]*)", sel))
    return (ids, classes + pseudos, tags)


def load_rules() -> list[tuple[str, dict[str, str]]]:
    rules: list[tuple[str, dict[str, str]]] = []
    for name in SHEETS:
        text = _strip_comments((CSS_DIR / name).read_text(encoding="utf-8"))
        rules.extend(_iter_rules(text))
    return rules


def variables(rules: list[tuple[str, dict[str, str]]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for selector, decls in rules:
        if ":root" not in selector:
            continue
        for prop, value in decls.items():
            if prop.startswith("--") and prop not in out:
                out[prop] = value
    return out


def _expand(value: str, vars_: dict[str, str]) -> str:
    for _ in range(4):
        m = re.search(r"var\((--[A-Za-z0-9-]+)(?:,\s*([^)]+))?\)", value)
        if not m:
            break
        name, fallback = m.group(1), m.group(2)
        value = value.replace(m.group(0), vars_.get(name, (fallback or "transparent").strip()))
    return value.strip()


def _color(value: str) -> tuple[float, float, float, float] | None:
    value = value.strip().lower()
    named = {"#fff": (255, 255, 255, 1.0), "#ffffff": (255, 255, 255, 1.0),
             "white": (255, 255, 255, 1.0), "transparent": (0, 0, 0, 0.0),
             "red": (255, 0, 0, 1.0)}
    if value in named:
        return named[value]
    m = re.fullmatch(r"#([0-9a-f]{3,8})", value)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) == 6:
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 1.0)
        if len(h) == 8:
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16),
                    int(h[6:8], 16) / 255)
    m = re.fullmatch(r"rgba?\(([^)]+)\)", value)
    if m:
        parts = [p.strip() for p in re.split(r"[,\s/]+", m.group(1)) if p.strip()]
        try:
            nums = [float(p) for p in parts[:3]]
            alpha = float(parts[3]) if len(parts) > 3 else 1.0
        except ValueError:
            return None
        if len(nums) == 3:
            return (nums[0], nums[1], nums[2], alpha)
    return None


def _luminance(rgb: tuple[float, float, float, float]) -> float:
    def channel(c: float) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b, _ = rgb
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(fg: tuple[float, float, float, float],
             bg: tuple[float, float, float, float],
             page: tuple[float, float, float, float]) -> float:
    """字色与"实际看到的底色"的对比度；半透明底色要先与页面底色合成。"""
    alpha = bg[3]
    solid = tuple(bg[i] * alpha + page[i] * (1 - alpha) for i in range(3)) + (1.0,)
    l1, l2 = _luminance(fg), _luminance(solid)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def computed(rules: list[tuple[str, dict[str, str]]],
             ancestors: list[tuple[str, frozenset[str]]],
             element: tuple[str, frozenset[str]],
             states: frozenset[str]) -> dict[str, str]:
    """按 (权重, 出现顺序) 求某元素在某状态下的最终声明。"""
    winners: dict[tuple[int, int, int], dict[str, str]] = {}
    order: dict[tuple[int, int, int], int] = {}
    for index, (selector, decls) in enumerate(rules):
        for sel in selector.split(","):
            sel = sel.strip()
            if not sel or not _matches(sel, ancestors, element, states):
                continue
            key = _specificity(sel)
            slot = winners.setdefault(key, {})
            for prop, value in decls.items():
                if prop in ("color", "background", "background-color"):
                    slot[prop] = value
            order[key] = index
    merged: dict[str, str] = {}
    for key in sorted(winners, key=lambda k: (k, order[k])):
        merged.update(winners[key])
    if "background" not in merged and "background-color" in merged:
        merged["background"] = merged["background-color"]
    return merged


CARD = "proj-card"
OPS = "ops"
SESS = "sess-item"


def _cases():
    """按钮在页面里的真实位置：元素本身、祖先链、需要判定的状态。"""
    return {
        "项目/会话页「删除」": ([], ("button", frozenset({"btn", "sm", "danger", "armed"}))),
        "删除项目": ([], ("button", frozenset({"btn", "danger", "armed"}))),
        "会话列表 ✕": ([(SESS, frozenset({SESS})), (OPS, frozenset({"ops"}))],
                     ("button", frozenset({"danger", "armed"}))),
        "经验条目「删除」": ([], ("button", frozenset({"btn", "exp-del", "armed"}))),
    }


class ArmedButtonContrastTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rules = load_rules()
        cls.vars = variables(cls.rules)
        # 浅色主题的页面底色（--bg）
        cls.page = _color(_expand("var(--bg)", cls.vars)) or (255, 255, 255, 1.0)

    def _style(self, ancestors, element, states) -> tuple[str, str, float]:
        style = computed(self.rules, ancestors, element, frozenset(states))
        self.assertIn("color", style, f"没算到字色：{style}")
        self.assertIn("background", style, f"没算到底色：{style}")
        fg = _color(_expand(style["color"], self.vars))
        bg = _color(_expand(style["background"], self.vars))
        self.assertIsNotNone(fg, style["color"])
        self.assertIsNotNone(bg, style["background"])
        return style["color"], style["background"], contrast(fg, bg, self.page)

    def test_armed_buttons_are_readable_while_hovered(self) -> None:
        for name, (ancestors, element) in _cases().items():
            with self.subTest(button=name):
                _, _, ratio = self._style(ancestors, element, {"hover"})
                self.assertGreaterEqual(
                    ratio, MIN_CONTRAST,
                    f"{name} 悬停时字与底色对比度只有 {ratio:.2f}:1 —— 字看不见了")

    def test_armed_buttons_are_readable_at_rest(self) -> None:
        for name, (ancestors, element) in _cases().items():
            with self.subTest(button=name):
                _, _, ratio = self._style(ancestors, element, set())
                self.assertGreaterEqual(ratio, MIN_CONTRAST, f"{name} 确认态不可读")

    def test_armed_background_is_opaque(self) -> None:
        """确认态的底色必须是实色：半透明底会让白字落到页面底色上。"""
        for name, (ancestors, element) in _cases().items():
            with self.subTest(button=name):
                _, background, _ = self._style(ancestors, element, {"hover"})
                bg = _color(_expand(background, self.vars))
                assert bg is not None
                self.assertGreaterEqual(bg[3], 0.9, f"{name} 确认态底色是半透明的")

    def test_cascade_catches_the_old_regression(self) -> None:
        """把修复前的写法放回去，这套计算必须判它不合格（证明测试有效）。"""
        regressed = [
            (".btn.danger:hover", {"border-color": "var(--bad)", "background": "var(--bad-soft)"}),
            (".btn.armed", {"background": "var(--bad)", "border-color": "var(--bad)", "color": "#fff"}),
        ]
        # 只留这两条 + 变量与基础 .btn 声明，模拟旧 CSS 的层叠关系
        rules = [(sel, decls) for sel, decls in self.rules
                 if sel in (":root", ".btn", ".btn:hover", ".btn.danger", ".btn:disabled")]
        rules.extend(regressed)
        style = computed(rules, [], ("button", frozenset({"btn", "sm", "danger", "armed"})),
                     frozenset({"hover"}))
        bg = _color(_expand(style["background"], self.vars))
        fg = _color(_expand(style["color"], self.vars))
        assert bg is not None and fg is not None
        self.assertLess(contrast(fg, bg, self.page), MIN_CONTRAST,
                        "旧写法居然通过了？说明这个对比度检查抓不到真实回归")


if __name__ == "__main__":
    unittest.main()
