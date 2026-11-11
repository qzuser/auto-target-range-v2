"""前端调用与后端路由的契约检查。

为什么加这条：控制台前端没有构建步骤，`static/js/*.js` 里全是手写的
``fetch("/api/...")`` 字面量。后端改个路径（``/api/sessions/{id}/stop`` →
``/api/sessions/{id}/halt`` 之类）前端不会编译报错，只会运行时 404，而且
往往要等用户点下去才发现。这里把两边的字符串对齐：JS 里出现的每个
``/api/...`` 都必须能匹配到 ``web/`` 下某个 ``@app.<method>("...")`` 声明。

思路借自 Project Muteki（AGPL-3.0，只看思路没有拷代码）CI 里的
"Check generated API contracts"：他们用生成的 TS 契约做同样的事，
我们没有构建步骤，所以退一步用源码正则，够用且零依赖。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

WEB_ROOT = Path(__file__).resolve().parents[1] / "src" / "spiritscout" / "web"
JS_DIR = WEB_ROOT / "static" / "js"

ROUTE_RE = re.compile(r"@app\.(?:get|post|put|delete|patch|head|options)\(\s*[\"']([^\"']+)")
# 双引号/单引号里不会有多余空白；反引号模板里可能有空格（三元），得单独收
JS_CALL_RE = re.compile(r"[\"'](/api/[^\"'\s]*)|`(/api/[^`]*)`")
DYNAMIC_RE = re.compile(r"\$\{[^}]*\}")


def _route_segments(path: str) -> list[str]:
    """``/api/sessions/{session_id}/stop`` → ``['api', 'sessions', '*', 'stop']``"""
    return ["*" if s.startswith("{") else s for s in path.strip("/").split("/") if s]


def _js_segments(literal: str) -> list[str]:
    """JS 字面量 → 段列表：模板变量算通配，查询串与哈希丢掉。"""
    text = DYNAMIC_RE.sub("*", literal)
    text = text.split("?", 1)[0].split("#", 1)[0]
    return [s for s in text.strip("/").split("/") if s]


def _matches(route: list[str], call: list[str]) -> bool:
    """路由逐段匹配调用；调用比路由短（尾部动态拼）也算命中。"""
    if len(call) > len(route):
        return False
    for want, got in zip(route, call, strict=False):
        if want == "*" or got == "*":
            continue
        if want != got:
            return False
    return True


def _routes() -> list[str]:
    found: list[str] = []
    for path in WEB_ROOT.rglob("*.py"):
        found.extend(ROUTE_RE.findall(path.read_text(encoding="utf-8")))
    return found


def _calls() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path in sorted(JS_DIR.glob("*.js")):
        for quoted, templated in JS_CALL_RE.findall(path.read_text(encoding="utf-8")):
            literal = quoted or templated
            found.setdefault(literal, set()).add(path.name)
    return found


class ApiContractTests(unittest.TestCase):
    """前端字面量与后端路由不许各说各话。"""

    def test_scanner_sees_both_sides(self) -> None:
        # 正则失效（写法改了、目录挪了）时会静默变成「全都匹配」，所以先确认扫到了东西
        self.assertGreater(len(_routes()), 60)
        self.assertGreater(len(_calls()), 40)

    def test_every_frontend_call_matches_a_route(self) -> None:
        routes = [_route_segments(r) for r in _routes()]
        missing: list[str] = []
        for literal, files in sorted(_calls().items()):
            call = _js_segments(literal)
            if any(_matches(route, call) for route in routes):
                continue
            missing.append(f"{literal}  ← {', '.join(sorted(files))}")
        self.assertEqual(
            missing,
            [],
            "这些前端调用在后端找不到对应路由（改路径时两边要一起改）：\n" + "\n".join(missing),
        )

    def test_dynamic_segments_are_treated_as_wildcards(self) -> None:
        # 模板变量与 {param} 都算通配：/api/sessions/${id}/messages ↔ /api/sessions/{session_id}/messages
        self.assertTrue(
            _matches(_route_segments("/api/sessions/{session_id}/messages"),
                     _js_segments("/api/sessions/${S.cur}/messages"))
        )
        # 三元表达式里的 ? 不是查询串，不能被切断
        self.assertTrue(
            _matches(_route_segments("/api/sessions/{session_id}/pause"),
                     _js_segments("/api/sessions/${S.cur}/${s.paused ? 'pause' : 'resume'}"))
        )
        # 段名对不上就是真的对不上
        self.assertFalse(
            _matches(_route_segments("/api/sessions"), _js_segments("/api/session"))
        )


if __name__ == "__main__":
    unittest.main()
