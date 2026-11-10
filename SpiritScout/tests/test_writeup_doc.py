"""赛方解题思路模板：方向分章、未解题不许写成已解、模型不可用也有兜底。

模板来自赛方那份 docx（团队信息 / 解题情况 / 具体WP，具体WP 按
WEB/PWN/REVERSE/MISC/CRYPTO/DS/IOT 分章）。这组测试盯住三件事：
分章对不对、Flag 归属对不对、模型掉线时点"生成"还能不能拿到东西。
"""
from __future__ import annotations

import tempfile
import unittest
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import AsyncMock

from spiritscout.blackboard import Blackboard
from spiritscout.core.audit import AuditLogger
from spiritscout.core.models import BlackboardLayer, FlagCandidate
from spiritscout.ctf.writeup import (
    _WP_SYSTEM,
    WP_DIRECTIONS,
    build_wp_digest,
    direction_key,
    tool_inventory,
    wp_body,
    wp_fallback,
)


def _flag(value: str, cid: str, accepted: bool | None) -> FlagCandidate:
    """FlagCandidate 要求 flag_id；测试里用它把三处构造收拢成一行。"""
    return FlagCandidate(flag_id=f"fid-{cid}-{value}", value=value,
                         challenge_id=cid, accepted=accepted)

def _challenge(cid: str, title: str, direction: str = "web", **kw) -> dict:
    return {"id": cid, "title": title, "direction": direction, **kw}


def _digest(challenges, flags=(), routes=(), findings=(), team=None, overrides=None,
            tools=None):
    with tempfile.TemporaryDirectory() as tmp:
        bb = Blackboard(f"{tmp}/bb.db")
        for index, (title, notes) in enumerate(routes):
            bb.write(BlackboardLayer.TASK_STATE, f"t{index}", {
                "task": {"task_id": f"t{index}", "task_type": "solve",
                         "payload": {"node_title": title}},
                "routes": [{"name": "主路线", "notes": list(notes)}],
            }, updated_by="recon")
        for index, text in enumerate(findings):
            bb.write(BlackboardLayer.TOPOLOGY, f"f{index}", {
                "kind": "finding", "type": "clue", "text": text,
            }, updated_by="recon")
        digest = build_wp_digest(
            challenges=challenges, flags=list(flags), run_summary={},
            # team 传空 dict 表示"什么都没填"，与不传（默认战队名）区分开
            blackboard=bb, team={"name": "灵枢战队"} if team is None else team,
            facts={"model_calls": 12}, direction_overrides=overrides, tools=tools,
        )
        bb.close()
    return digest


class DirectionTests(unittest.TestCase):
    def test_aliases_land_in_the_seven_chapters(self) -> None:
        cases = {
            "web": "WEB", "Web安全": "WEB", "PWN": "PWN", "pwn": "PWN",
            "逆向": "REVERSE", "reverse": "REVERSE", "密码学": "CRYPTO",
            "杂项": "MISC", "stego": "MISC", "数据安全": "DS", "工控": "IOT",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(direction_key(raw), expected)

    def test_unknown_and_empty_land_in_misc(self) -> None:
        for raw in ("", None, "某个没见过的方向"):
            with self.subTest(raw=raw):
                self.assertEqual(direction_key(raw), "MISC")


class DigestTests(unittest.TestCase):
    def test_chapters_group_by_direction_in_template_order(self) -> None:
        digest = _digest([
            _challenge("c1", "登录绕过", "web"),
            _challenge("c2", "栈溢出", "pwn"),
            _challenge("c3", "伪装文件", "misc"),
        ])
        self.assertEqual(digest["chapter_order"], ["WEB", "PWN", "MISC"])
        self.assertEqual([c["id"] for c in digest["chapters"]["PWN"]], ["c2"])
        # 空方向不出现：模板里没题的章不该凭空冒出来
        self.assertNotIn("CRYPTO", digest["chapters"])

    def test_flags_attach_to_their_own_challenge(self) -> None:
        flags = [
            _flag("flag{a}", "c1", True),
            _flag("flag{b}", "c2", None),
        ]
        digest = _digest([_challenge("c1", "题一"), _challenge("c2", "题二")], flags)
        first = next(c for c in digest["challenges"] if c["id"] == "c1")
        second = next(c for c in digest["challenges"] if c["id"] == "c2")
        self.assertEqual([f["value"] for f in first["flags"]], ["flag{a}"])
        self.assertEqual([f["value"] for f in second["flags"]], ["flag{b}"])
        self.assertTrue(first["solved"])
        # accepted 为 None（未判定）按"已提取"处理，不当成失败
        self.assertTrue(second["solved"])

    def test_wrong_flag_does_not_count_as_solved(self) -> None:
        flags = [_flag("flag{wrong}", "c1", False)]
        digest = _digest([_challenge("c1", "题一")], flags)
        self.assertEqual(digest["unsolved_ids"], ["c1"])
        self.assertEqual(digest["solved_count"], 0)

    def test_unsolved_ids_list_everything_without_a_flag(self) -> None:
        digest = _digest([
            _challenge("c1", "解出的"),
            _challenge("c2", "没解出的"),
        ], [_flag("flag{a}", "c1", True)])
        self.assertEqual(digest["unsolved_ids"], ["c2"])
        self.assertEqual((digest["total"], digest["solved_count"]), (2, 1))

    def test_route_notes_follow_the_challenge_title(self) -> None:
        digest = _digest(
            [_challenge("c1", "登录绕过")],
            routes=[("登录绕过 · 主攻", ["抓包发现 role 参数可改"])],
        )
        entry = digest["challenges"][0]
        self.assertEqual(entry["routes"][0]["notes"], ["抓包发现 role 参数可改"])

    def test_internal_counters_stay_out_of_the_material(self) -> None:
        """调用/失败计数不进材料：写手拿到它就会写成复盘与验证环节。"""
        digest = _digest([_challenge("c1", "题一")])
        self.assertNotIn("run_facts", digest)

    def test_flag_material_carries_no_verdict(self) -> None:
        """只留 flag 值；判定/提交状态属于平台侧验证，不进 WP 材料。"""
        digest = _digest([_challenge("c1", "题一")],
                         [_flag("flag{a}", "c1", True)])
        flags = digest["challenges"][0]["flags"]
        self.assertEqual(flags, [{"value": "flag{a}"}])


class PromptTests(unittest.TestCase):
    """写手口径：交的是解题思路（中文、写明工具），不是这次作业是怎么编排的。"""

    def test_prompt_asks_for_the_solution_not_the_pipeline(self) -> None:
        self.assertIn("解题思路", _WP_SYSTEM)
        self.assertIn("全文中文", _WP_SYSTEM)
        self.assertIn("必须写工具", _WP_SYSTEM)
        self.assertIn("内部编排", _WP_SYSTEM)
        # 这些词只出现在「不许写」的纪律里，素材本身不再往编排上引
        for word in ("子 Agent", "派发", "编排", "回合"):
            with self.subTest(word=word):
                self.assertIn(word, _WP_SYSTEM)

    def test_prompt_keeps_the_contest_skeleton(self) -> None:
        for heading in ("## 团队信息", "## 解题情况", "## 具体WP", "**Flag**", "**过程**"):
            with self.subTest(heading=heading):
                self.assertIn(heading, _WP_SYSTEM)

    def test_prompt_bans_verification_and_retro_sections(self) -> None:
        """验证环节与经验复盘都不写：这是「只讲解题过程」的硬口径。"""
        for banned in ("验证环节", "经验与复盘", "未判定", "改进建议"):
            with self.subTest(banned=banned):
                self.assertIn(banned, _WP_SYSTEM)


class ToolTests(unittest.TestCase):
    def test_digest_carries_the_tool_inventory(self) -> None:
        digest = _digest([_challenge("c1", "题一")],
                         tools=[{"tool": "nmap", "calls": 3}])
        self.assertEqual(digest["tools"], [{"tool": "nmap", "calls": 3}])
        self.assertNotIn("rounds", digest, "编排回合数不该进写手材料")

    def test_fallback_lists_what_was_used(self) -> None:
        digest = _digest([_challenge("c1", "题一")],
                         tools=[{"tool": "sqlmap", "calls": 2}])
        body = wp_fallback(digest)
        self.assertIn("sqlmap", body)
        self.assertIn("用到的工具", body)
        self.assertNotIn("本次调用", body, "调用次数是内部计数，不进 WP")

    def test_fallback_has_no_flag_verdicts(self) -> None:
        digest = _digest([_challenge("c1", "题一")], [_flag("flag{a}", "c1", True)])
        body = wp_fallback(digest)
        self.assertIn("`flag{a}`", body)
        for verdict in ("✅", "❌", "未判定", "正确"):
            with self.subTest(verdict=verdict):
                self.assertNotIn(verdict, body)

    def test_inventory_counts_the_audit_tool_calls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audit = AuditLogger(f"{tmp}/audit.jsonl")
            audit.log("agent.tool_call", "ctf-web-x",
                      {"calls": [{"id": "1", "name": "investigate"}]})
            audit.log("agent.tool_call", "ctf-web-x",
                      {"calls": [{"id": "2", "name": "investigate"},
                                 {"id": "3", "name": "bash"}]})
            audit.log("model.started", "ctf-web-x", {"call_id": "c"})
            rows = tool_inventory(audit)
        self.assertEqual([r["tool"] for r in rows], ["investigate", "bash"])
        self.assertEqual(rows[0]["calls"], 2)


class FallbackTests(unittest.TestCase):
    def test_fallback_keeps_the_template_skeleton(self) -> None:
        digest = _digest([
            _challenge("c1", "登录绕过", "web", description="后台登录校验可绕过"),
            _challenge("c2", "栈溢出", "pwn"),
        ], [_flag("flag{a}", "c1", True)])
        body = wp_fallback(digest)
        for heading in ("## 团队信息", "## 解题情况", "## 具体WP", "### WEB", "### PWN"):
            with self.subTest(heading=heading):
                self.assertIn(heading, body)
        self.assertIn("flag{a}", body)
        self.assertIn("#### 登录绕过", body)

    def test_fallback_marks_unsolved_challenge_as_unfinished(self) -> None:
        digest = _digest([_challenge("c2", "栈溢出", "pwn")])
        body = wp_fallback(digest)
        self.assertIn("未获取到", body)
        # 没解出来就不许出现像 flag 的内容
        self.assertNotIn("flag{", body)

    def test_fallback_without_challenges_says_so(self) -> None:
        digest = _digest([])
        body = wp_fallback(digest)
        self.assertIn("本场未解出题目", body)

    def test_fallback_leaves_screenshot_placeholders(self) -> None:
        digest = _digest([_challenge("c1", "题一")])
        body = wp_fallback(digest)
        self.assertIn("[截图：", body)


class BodyTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_model_output_returns_none(self) -> None:
        gateway = SimpleNamespace(chat=AsyncMock(
            return_value=SimpleNamespace(content="   ")))
        digest = _digest([_challenge("c1", "题一")])
        self.assertIsNone(await wp_body(gateway, digest=digest))

    async def test_model_failure_returns_none_instead_of_raising(self) -> None:
        gateway = SimpleNamespace(chat=AsyncMock(side_effect=RuntimeError("模型挂了")))
        digest = _digest([_challenge("c1", "题一")])
        self.assertIsNone(await wp_body(gateway, digest=digest))

    async def test_body_is_returned_without_code_fence(self) -> None:
        gateway = SimpleNamespace(chat=AsyncMock(return_value=SimpleNamespace(
            content="```markdown\n# 战队-解题思路\n\n## 具体WP\n```")))
        digest = _digest([_challenge("c1", "题一")])
        body = await wp_body(gateway, digest=digest)
        self.assertIsNotNone(body)
        assert body is not None
        self.assertTrue(body.startswith("# 战队-解题思路"))
        self.assertNotIn("```", body)

    async def test_model_tacked_url_is_stripped_from_the_challenge_heading(self) -> None:
        """实测模型会把入口地址挂到题目小标题上；那一行只该是题名。"""
        gateway = SimpleNamespace(chat=AsyncMock(return_value=SimpleNamespace(
            content="# 战队-解题思路\n\n### WEB\n\n"
                    "#### 题一（https://a.test/）\n\n- **题面要点**：…\n\n"
                    "#### 题二    https://b.test/\n\n"
                    "#### 模型自己起的名 [https://c.test/x]\n\n"
                    "#### 正常标题\n")))
        digest = _digest([_challenge("c1", "题一"), _challenge("c2", "题二")])
        body = await wp_body(gateway, digest=digest)
        assert body is not None
        for heading in ("#### 题一", "#### 题二", "#### 模型自己起的名", "#### 正常标题"):
            self.assertIn(f"{heading}\n", body if body.endswith("\n") else body + "\n")
        for gone in ("a.test", "b.test", "c.test"):
            self.assertNotIn(gone, body)


class TemplateShapeTests(unittest.TestCase):
    def test_seven_directions_in_the_order_the_template_uses(self) -> None:
        self.assertEqual(WP_DIRECTIONS,
                         ("WEB", "PWN", "REVERSE", "MISC", "CRYPTO", "DS", "IOT"))


class ManualInfoTests(unittest.TestCase):
    """信息页填的内容：进材料、进分章，缺了也不影响成文。"""

    TEAM: ClassVar[dict[str, object]] = {
        "name": "灵枢战队", "members": ["张三", "李四"],
        "affiliation": "某某大学", "contest": "2026 练习赛",
        "notes": "只用题面给的入口"}

    def test_extra_team_fields_reach_the_digest(self) -> None:
        digest = _digest([_challenge("c1", "题一")], team=self.TEAM)
        self.assertEqual(digest["team"]["name"], "灵枢战队")
        self.assertEqual(digest["team"]["members"], ["张三", "李四"])
        self.assertEqual(digest["team"]["affiliation"], "某某大学")
        self.assertEqual(digest["team"]["contest"], "2026 练习赛")
        self.assertEqual(digest["team"]["notes"], "只用题面给的入口")

    def test_direction_override_wins_over_the_category(self) -> None:
        digest = _digest([_challenge("c1", "题一", "web"),
                          _challenge("c2", "题二", "pwn")],
                         overrides={"c1": "crypto", "c2": "PWN"})
        entries = {e["id"]: e for e in digest["challenges"]}
        self.assertEqual(entries["c1"]["chapter"], "CRYPTO")
        self.assertTrue(entries["c1"]["chapter_by_user"])
        # 别名归一：小写 pwn 也算作手改，但分章不变
        self.assertEqual(entries["c2"]["chapter"], "PWN")
        self.assertTrue(entries["c2"]["chapter_by_user"])
        self.assertEqual(digest["chapter_order"], ["PWN", "CRYPTO"])

    def test_untouched_challenge_is_marked_automatic(self) -> None:
        digest = _digest([_challenge("c1", "题一", "web")], overrides={"c9": "PWN"})
        entry = digest["challenges"][0]
        self.assertFalse(entry["chapter_by_user"])
        self.assertEqual(entry["chapter"], "WEB")

    def test_fallback_renders_the_filled_fields(self) -> None:
        text = wp_fallback(_digest([_challenge("c1", "题一")], team=self.TEAM))
        self.assertIn("# 灵枢战队-解题思路", text)
        self.assertIn("- 队员组成：张三、李四", text)
        self.assertIn("- 所属单位：某某大学", text)
        self.assertIn("- 参赛赛事：2026 练习赛", text)
        self.assertIn("> 补充说明：只用题面给的入口", text)

    def test_fallback_without_manual_info_still_delivers(self) -> None:
        """什么都没填：标题退到默认战队名，缺的字段写「（待填写）」，不编内容。"""
        text = wp_fallback(_digest([_challenge("c1", "题一")], team={}))
        self.assertIn("# 灵枢战队-解题思路", text)
        self.assertIn("- 团队名称：（待填写）", text)
        self.assertIn("- 队员组成：（待填写）", text)
        self.assertNotIn("所属单位", text)
        self.assertNotIn("补充说明", text)


if __name__ == "__main__":
    unittest.main()
