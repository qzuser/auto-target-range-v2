"""同题多方向并行派工。

并行执行的机制本来就在（就绪节点一次性全部 create_task 派出去），缺的是规划
器愿不愿意为同一道题一次铺开多个方向。这里锁两件事：DAG 不会把同题的多方向
节点当重复丢掉，规划提示词里确实带着并行优先的要求。
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from spiritscout.agents.master.agent import MasterAgent
from spiritscout.agents.master.dag import TaskDAG
from spiritscout.core.models import AgentType, TaskStatus

CHALLENGE = {"id": "c1", "title": "stega3", "url": "http://c1.fixture"}


def make_master() -> MasterAgent:
    master = object.__new__(MasterAgent)
    master.agent_id = "master-test"
    master.ctx = SimpleNamespace(
        audit=Mock(), pause_gate=None, plan_override=None, enable_llm_planning=False,
        agents={AgentType.CTF_WEB: object(), AgentType.CTF_MISC: object()},
        tactic_map={"CTF-WEB": (AgentType.CTF_WEB, "ctf_solve"),
                    "CTF-MISC": (AgentType.CTF_MISC, "ctf_solve")},
        extra={"run_mode": "ctf"})
    master._ensure_business_gate = lambda nodes: nodes
    return master


class ParallelDispatchTests(unittest.TestCase):
    def test_same_challenge_keeps_all_parallel_nodes(self) -> None:
        """同题的多方向节点用「战术@序号」区分，DAG 不能把它们合并掉。"""
        dag = TaskDAG()
        result = dag.upsert_from_plan([
            {"tactic": "CTF-WEB", "title": "验证上传点", "challenge_id": "c1"},
            {"tactic": "CTF-WEB@2", "title": "验证编码线索", "challenge_id": "c1"},
            {"tactic": "CTF-MISC", "title": "还原隐写载荷", "challenge_id": "c1"},
        ], 0)
        self.assertEqual(len(result.created), 3, "三个方向都要落图")
        self.assertEqual(len(dag.all_nodes()), 3)
        self.assertEqual({n.status for n in dag.all_nodes()}, {TaskStatus.PENDING})

    def test_ready_nodes_expose_parallel_directions_at_once(self) -> None:
        """没有依赖关系的方向必须同时就绪——串行等就白等了。"""
        dag = TaskDAG()
        dag.upsert_from_plan([
            {"tactic": "CTF-WEB", "title": "方向一"},
            {"tactic": "CTF-MISC", "title": "方向二"},
            {"tactic": "CTF-WEB@2", "title": "方向三"},
        ], 0)
        self.assertEqual(len(dag.ready_nodes()), 3)

    def test_dependencies_still_serialise_what_must_wait(self) -> None:
        """真有硬前置时仍按依赖走，并行不能盖过依赖。"""
        dag = TaskDAG()
        dag.upsert_from_plan([
            {"tactic": "CTF-WEB", "title": "先拿到入口"},
            {"tactic": "CTF-MISC", "title": "再推导载荷", "depends_on": ["CTF-WEB"]},
        ], 0)
        ready = [n.tactic for n in dag.ready_nodes()]
        self.assertEqual(ready, ["CTF-WEB"], "有前置的节点还不该开工")
        self.assertEqual(len(dag.all_nodes()), 2)


class PlannerPromptTests(unittest.TestCase):
    """规划提示词是并行的唯一方向盘：少了这段，模型就一题一节点串行试。"""

    @staticmethod
    def _constraints() -> str:
        import inspect

        from spiritscout.agents.master import planning

        src = inspect.getsource(planning)
        start = src.index('"派工以并行优先')
        return src[start:start + 1200]

    def test_prompt_asks_for_parallel_directions(self) -> None:
        text = self._constraints()
        for phrase in ("并行优先", "同时开工", "depends_on", "互不重叠"):
            self.assertIn(phrase, text, f"规划约束里缺「{phrase}」")

    def test_prompt_explains_tactic_suffix_for_same_challenge(self) -> None:
        """不写这条，同题第二个节点会被 DAG 当成重复丢弃。"""
        self.assertIn("战术@序号", self._constraints())

    def test_prompt_spreads_work_across_agents(self) -> None:
        self.assertIn("不同 agent", self._constraints())


if __name__ == "__main__":
    unittest.main()
