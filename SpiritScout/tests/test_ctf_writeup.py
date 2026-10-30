"""WriteUp 材料汇总与写手约束。

材料是写手唯一的事实来源，所以两头都要定住：`build_digest` 交出去的结构不能缺
（题面、Flag 状态、路线笔记），提示词里要明说「材料没写的原因不许替它下结论」——
上一版报告把同一节点的重复运行写成了「LLM 调用失败」，而那一轮失败计数其实是 0。
"""
from __future__ import annotations

import unittest

from spiritscout.ctf.writeup import (
    _WRITER_SYSTEM,
    build_digest,
    off_task_marker,
    run_facts,
    writeup_body,
)


class _FakeBlackboard:
    """只实现 build_digest 用到的 query 接口。"""

    def __init__(self, tasks: list[dict], findings: list[dict]) -> None:
        self._tasks = tasks
        self._findings = findings

    def query(self, layer, limit: int = 100):      # noqa: ANN001, ARG002 —— 夹具
        name = getattr(layer, "value", str(layer))
        if name == "task_state":
            return [{"data": t} for t in self._tasks][:limit]
        return [{"data": f} for f in self._findings][:limit]


class _Flag:
    def __init__(self, value: str, cid: str) -> None:
        self.value = value
        self.challenge_id = cid
        self.found_by = "ctf_web"
        self.submitted = True
        self.accepted = True


class DigestTests(unittest.TestCase):
    def test_digest_carries_challenges_flags_and_route_notes(self) -> None:
        board = _FakeBlackboard(
            tasks=[{"task": {"agent_type": "ctf_web", "status": "done",
                             "payload": {"node_title": "登录框"}},
                    "routes": [{"name": "sqli", "status": "done",
                                "notes": ["注释泄露后端语句"]}]}],
            findings=[{"kind": "finding", "type": "flag", "text": "flag{x}", "by": "ctf_web"}],
        )
        digest = build_digest(
            challenges=[{"id": "web-01", "title": "登录框里的秘密", "direction": "web",
                         "url": "http://127.0.0.1:8899/ch/web-01/", "description": "打登录框"}],
            flags=[_Flag("flag{x}", "web-01")],
            run_summary={"rounds_executed": 2,
                         "dag_nodes": [{"title": "登录框", "status": "done"}]},
            blackboard=board,
        )
        self.assertEqual(digest["challenges"][0]["id"], "web-01")
        self.assertEqual(digest["flags"][0]["accepted"], True)
        self.assertEqual(digest["rounds"], 2)
        self.assertEqual(digest["routes_notes"][0]["routes"][0]["notes"], ["注释泄露后端语句"])
        self.assertEqual(digest["findings"][0]["text"], "flag{x}")

    def test_unsolved_ids_name_every_challenge_without_an_accepted_flag(self) -> None:
        digest = build_digest(
            challenges=[{"id": "web-01"}, {"id": "rev-01"}, {"id": "misc-01"}],
            flags=[_Flag("flag{x}", "web-01")],
            run_summary={}, blackboard=_FakeBlackboard([], []),
        )
        self.assertEqual(digest["unsolved_ids"], ["rev-01", "misc-01"])

    def test_writer_prompt_forbids_ungrounded_failure_claims(self) -> None:
        # 材料是材料、不是对话：写手多次把记录当聊天记录去「复盘挑错」并编造失败
        self.assertIn("不是队员对你说话", _WRITER_SYSTEM)
        self.assertIn("不要产出「日志审查」", _WRITER_SYSTEM)
        self.assertIn("unsolved_ids", _WRITER_SYSTEM)
        self.assertIn("model_failures", _WRITER_SYSTEM)


class RunFactsTests(unittest.TestCase):
    def test_counts_only_event_tallies(self) -> None:
        class _Audit:
            def read_all(self):
                return [{"type": "model.call"}, {"type": "model.call"},
                        {"type": "model.failed"}, {"type": "agent.tool_call"},
                        {"type": "something.else"}]

        facts = run_facts(_Audit())
        self.assertEqual(facts["model_calls"], 2)
        self.assertEqual(facts["model_failures"], 1)
        self.assertEqual(facts["tool_call_turns"], 1)
        self.assertEqual(facts["model_timeouts"], 0)

    def test_missing_audit_yields_empty(self) -> None:
        self.assertEqual(run_facts(None), {})

    def test_digest_includes_run_facts(self) -> None:
        digest = build_digest(challenges=[], flags=[], run_summary={},
                              blackboard=_FakeBlackboard([], []),
                              facts={"model_failures": 0})
        self.assertEqual(digest["run_facts"], {"model_failures": 0})


class OffTaskTests(unittest.IsolatedAsyncioTestCase):
    """写手把材料当审查对象的产出要被拦下：重试一次，仍跑偏就回退模板。"""

    def test_marker_detection(self) -> None:
        self.assertEqual(off_task_marker("## 1. 结论\n正常内容"), "")
        self.assertEqual(off_task_marker("## 记录内部矛盾（值得修）"), "记录内部矛盾")
        self.assertEqual(off_task_marker("## 4. 建议的三处改动"), "建议的三处改动")

    async def test_review_style_output_is_retried_then_accepted(self) -> None:
        said: list[str] = []

        class _Gateway:
            async def chat(self, messages, **kwargs):   # noqa: ANN001, ARG002
                said.append(messages[-1]["content"][:20])

                class _R:
                    content = ("## 日志审查\n材料里有矛盾" if len(said) == 1
                               else "# WriteUp\n\n## 总览\n三题中两题完成。")
                return _R()

        body = await writeup_body(_Gateway(), digest={"challenges": []})
        self.assertEqual(len(said), 2, "第一版跑偏应触发一次重试")
        self.assertIn("# WriteUp", body or "")

    async def test_persistently_off_task_falls_back_to_template(self) -> None:
        class _Gateway:
            async def chat(self, messages, **kwargs):   # noqa: ANN001, ARG002
                class _R:
                    content = "## 质量问题\n材料不可信"
                return _R()

        self.assertIsNone(await writeup_body(_Gateway(), digest={"challenges": []}))
