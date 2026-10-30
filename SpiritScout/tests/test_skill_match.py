"""技能库的自动检索：从中文任务描述里认出该用哪条 skill。

这是「自动识别并调用 skills 解题」的核心。改动前是 ``any(word in hay)``——查询里
任意一个词撞上任意一条就算命中，不分字段、不排先后、不限条数；实际后果是描述里
一出现 "web" 就把所有带 web 的技能一起返回，调用方只能盲取前三个，等于随机取。

这里钉住四件事：
1. 中文要能命中英文技能库（206 条正文全是英文，不搭桥就是零命中）；
2. 常见词不能靠刷脸把泛化条目顶上来（injection / bypass 在几十条里都有）；
3. ``limit`` 要按相关度取前 N 条，而不是按字母序；
4. 端到端：几条真实中文描述，第一名必须是对症的那条。
"""

from __future__ import annotations

import unittest

from spiritscout.resources.store import (
    _rank_skills,
    _skill_idf,
    _skill_score,
    _skill_terms,
    builtin_skills,
    reference_skills_for,
)


def _skill(skill_id: str, *, domain: str = "", body: str = "", tools: str = "",
           origin: str = "builtin") -> dict:
    return {"skill_id": skill_id, "domain": domain, "body": body, "tools": tools,
            "description": "", "origin": origin, "version": 0}


class TermExtractionTests(unittest.TestCase):
    def test_chinese_and_ascii_are_split_apart(self) -> None:
        # 中文没有词边界，整段糊在一起就没法和英文正文比对了
        terms = _skill_terms("帮我解这道 PHP 反序列化")
        self.assertIn("php", terms)
        self.assertIn("deserializ", terms, "中文「反序列化」要展开成英文说法")

    def test_stopwords_and_single_chars_are_dropped(self) -> None:
        terms = _skill_terms("请帮我看看这个")
        self.assertEqual([t for t in terms if t in {"请", "帮", "看", "这个"}], [],
                         "虚词和单字不该进检索词")

    def test_chinese_terms_expand_to_the_library_vocabulary(self) -> None:
        # 206 条内置技能正文是英文，任务描述是中文——这是命中率的瓶颈所在
        cases = {
            "逆向一个固件": {"reverse", "disassembl", "firmware"},
            "提权到域控": {"privilege escalation", "privesc", "domain controller"},
            "SSRF 读云元数据": {"ssrf", "cloud", "metadata"},
            "安卓 APK 抓包": {"android", "apk", "packet capture"},
        }
        for text, expected in cases.items():
            terms = set(_skill_terms(text))
            self.assertTrue(expected <= terms,
                            f"{text!r} 应展开出 {sorted(expected)}，实际 {sorted(terms)}")

    def test_one_chinese_phrase_can_hit_several_aliases(self) -> None:
        # "委派提权到域控" 粘成一坨也要能同时认出委派、提权、域控三个概念
        terms = set(_skill_terms("委派提权到域控"))
        self.assertIn("delegation", terms)
        self.assertIn("privilege escalation", terms)
        self.assertIn("domain controller", terms)

    def test_stopword_stripping_keeps_the_content_words(self) -> None:
        # 两端虚词要摘掉，实词要留住；中间夹词的不强求（别名表那条路兜底）
        self.assertIn("逆向", _skill_terms("逆向一个"))
        self.assertIn("后门", _skill_terms("找出后门"))

    def test_duplicates_are_removed(self) -> None:
        terms = _skill_terms("sql SQL sql 注入")
        self.assertEqual(terms.count("sql"), 1)


class ScoringTests(unittest.TestCase):
    def test_more_specific_fields_score_higher(self) -> None:
        # skill_id 命中比正文命中更说明问题
        by_id = _skill_score(["deserializ"], _skill("web-deserialization"))
        by_body = _skill_score(["deserializ"], _skill("something-else",
                                                      body="deserialization bugs"))
        self.assertGreater(by_id, by_body)

    def test_whole_word_beats_substring(self) -> None:
        # "sql" 撞进 "mysql" 不算对症，权重该低一档
        exact = _skill_score(["sql"], _skill("web sql"))
        substring = _skill_score(["sql"], _skill("web mysql"))
        self.assertGreater(exact, substring)

    def test_a_term_scores_once_at_its_best_field(self) -> None:
        # 同一个词在多个字段出现不该重复计分，否则正文长的条目白占便宜
        both = _skill_score(["ssrf"], _skill("web-ssrf", domain="ssrf",
                                             body="ssrf " * 50))
        once = _skill_score(["ssrf"], _skill("web-ssrf"))
        self.assertEqual(both, once)

    def test_no_terms_scores_zero(self) -> None:
        self.assertEqual(_skill_score([], _skill("web-ssrf")), 0)

    def test_common_words_carry_less_weight(self) -> None:
        rows = [_skill(f"noise-{i}", body="injection bypass") for i in range(30)]
        rows.append(_skill("rare-ssrf", body="injection ssrf"))
        terms = ["injection", "ssrf"]
        idf = _skill_idf(terms, rows)
        self.assertLess(idf["injection"], idf["ssrf"],
                        "30 条都有的 injection 区分度该低于只有 1 条有的 ssrf")


class RankingTests(unittest.TestCase):
    def test_limit_takes_the_most_relevant_not_the_alphabetical(self) -> None:
        rows = [
            _skill("aaa-generic", body="web vulnerability"),
            _skill("zzz-ssrf", body="ssrf metadata cloud"),
        ]
        ranked = _rank_skills(rows, "SSRF 读云元数据")
        self.assertEqual(ranked[0]["skill_id"], "zzz-ssrf",
                         "按相关度排，不能让字母序把对症的压下去")

    def test_empty_query_returns_the_whole_library_in_stable_order(self) -> None:
        rows = [_skill("b-skill"), _skill("a-skill")]
        first = _rank_skills(rows, "")
        second = _rank_skills(list(reversed(rows)), "")
        self.assertEqual([r["skill_id"] for r in first], ["a-skill", "b-skill"])
        self.assertEqual([r["skill_id"] for r in first],
                         [r["skill_id"] for r in second],
                         "同样的库要给出同样的顺序")

    def test_custom_skills_win_ties(self) -> None:
        rows = [_skill("a-builtin", body="ssrf"), _skill("z-custom", body="ssrf",
                                                         origin="custom")]
        self.assertEqual(_rank_skills(rows, "ssrf")[0]["skill_id"], "z-custom",
                         "同分时用户自建的优先")

    def test_non_matching_skills_are_dropped(self) -> None:
        rows = [_skill("web-ssrf", body="ssrf"), _skill("nothing", body="unrelated")]
        self.assertEqual([r["skill_id"] for r in _rank_skills(rows, "ssrf")],
                         ["web-ssrf"])


class RealLibraryTests(unittest.TestCase):
    """拿真库跑：查询写成人话，第一名必须是对症的那条。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = list(builtin_skills().values())

    def _top(self, query: str, n: int = 1) -> list[str]:
        return [row["skill_id"] for row in _rank_skills(self.rows, query)[:n]]

    def test_library_is_intact(self) -> None:
        self.assertGreaterEqual(len(self.rows), 200, "技能库条数异常")

    def test_php_deserialization(self) -> None:
        self.assertEqual(self._top("帮我解这道 PHP 反序列化，拿到 flag"),
                         ["web-deserialization"])

    def test_firmware_reverse(self) -> None:
        self.assertEqual(self._top("逆向一个 ARM 固件，找出后门"),
                         ["reverse-eng-firmware"])

    def test_ssrf_to_cloud_metadata(self) -> None:
        self.assertEqual(self._top("这个网站有 SSRF，读一下云元数据"),
                         ["cloud-imds-ssrf"])

    def test_kerberos_delegation(self) -> None:
        self.assertEqual(self._top("Kerberos 委派提权到域控"),
                         ["ad-delegation-abuse"])

    def test_jwt_claim_confusion(self) -> None:
        self.assertEqual(self._top("JWT alg 混淆，把 role 改成 admin"),
                         ["web-auth-jwt"])

    def test_android_packet_capture(self) -> None:
        self.assertEqual(self._top("安卓 APK 抓包看签名算法"),
                         ["mobile-apk-reverse"])

    def test_memory_forensics(self) -> None:
        top = self._top("内存取证看看有没有被注入", n=2)
        self.assertTrue(any("forensic" in r for r in top),
                        f"内存取证应该命中取证类技能，实际 {top}")

    def test_english_query_works_too(self) -> None:
        # 原名是英文技能库，英文查询不该反而变差
        self.assertIn("web-ssrf", self._top("ssrf server side request forgery", n=3))

    def test_sql_injection_rows_are_reachable(self) -> None:
        top = self._top("SQL 注入绕过 WAF 拿数据", n=8)
        self.assertTrue(any("sql" in r or "waf" in r for r in top),
                        f"SQL 注入题该拿到 sqli / waf 类技能，实际 {top}")


class _FakeResources:
    """只接住 skills()，用来验组装逻辑而不牵扯数据库。"""

    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.queries: list[str] = []
        self.limits: list[int | None] = []

    def skills(self, query: str = "", *, include_body: bool = False,
               limit: int | None = None) -> list[dict]:
        self.queries.append(query)
        self.limits.append(limit)
        return self.rows[:limit] if limit is not None else self.rows


class ReferenceSkillsForTests(unittest.TestCase):
    """注入到决策输入的那一步：用什么检索、注入几条、附什么说明。"""

    def _task(self, **payload):
        class _Task:
            pass
        task = _Task()
        task.payload = payload
        return task

    def test_query_includes_the_mission_text(self) -> None:
        # 之前只拿 node_title + 角色名去匹配，题目描述再清楚也白搭
        rows = [_skill("web-deserialization", body="deserialization")]
        resources = _FakeResources(rows)
        reference_skills_for(
            self._task(mission="帮我解这道 PHP 反序列化", node_title="分析目标"),
            "web_attacker", resources)
        query = resources.queries[0]
        self.assertIn("PHP 反序列化", query, "检索词必须带上任务原文")
        self.assertIn("分析目标", query)
        self.assertIn("web attacker", query, "角色名补足领域提示")

    def test_survives_a_task_without_a_mission(self) -> None:
        resources = _FakeResources([_skill("web-ssrf", body="ssrf")])
        payload = reference_skills_for(self._task(node_title="x"), "web_attacker",
                                       resources)
        self.assertIn("reference_skills", payload, "只有 node_title 也要能工作")

    def test_nothing_matched_injects_nothing(self) -> None:
        # 空数组既占位置又说明不了什么
        payload = reference_skills_for(self._task(mission="随便聊聊"), "x",
                                       _FakeResources([]))
        self.assertEqual(payload, {})

    def test_empty_everything_injects_nothing(self) -> None:
        self.assertEqual(reference_skills_for(self._task(), "", _FakeResources([])), {})

    def test_hint_explains_that_these_are_facts_not_steps(self) -> None:
        payload = reference_skills_for(
            self._task(mission="SSRF"), "web_attacker",
            _FakeResources([_skill("web-ssrf", body="ssrf")]))
        hint = payload["reference_skills_hint"]
        self.assertIn("不是步骤序列", hint,
                      "照抄技能卡会变成写死的解题模板，说明里必须讲清")
        self.assertIn("证据优先", hint, "现场观测要压过技能卡里的说法")

    def test_limit_and_body_truncation_are_respected(self) -> None:
        rows = [_skill(f"s-{i}", body="x" * 5000) for i in range(10)]
        resources = _FakeResources(rows)
        payload = reference_skills_for(self._task(mission="test"), "role", resources,
                                       limit=3, body_chars=200)
        self.assertEqual(resources.limits[0], 3)
        self.assertEqual(len(payload["reference_skills"]), 3)
        self.assertEqual(len(payload["reference_skills"][0]["reference"]), 200,
                         "正文要截断，不然一次决策就吃掉小半个上下文")

    def test_cards_carry_what_the_agent_needs_to_judge(self) -> None:
        paid = reference_skills_for(
            self._task(mission="ssrf"), "role",
            _FakeResources([_skill("web-ssrf", domain="web", tools="[burp]",
                                   body="ssrf how-to")]))["reference_skills"][0]
        self.assertEqual(paid["id"], "web-ssrf")
        self.assertEqual(paid["domain"], "web")
        self.assertIn("burp", paid["tools"], "工具清单要带上")
        self.assertIn("ssrf how-to", paid["reference"])


if __name__ == "__main__":
    unittest.main()
