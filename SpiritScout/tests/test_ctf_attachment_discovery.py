"""附件发现的回退：用户直接传附件、没写赛题 YAML 时，工具也要看得见。

现场最常见的走法是「建会话 → 拖附件 → 发任务」，`challenges` 里没有
attachments 清单。工具若只认清单，就会回答「本题没有附件」——模型于是反复
向用户确认材料在哪，一趟几十万 token 却没读一行源码。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from spiritscout.core.models import AgentType, Task, TaskStatus
from spiritscout.ctf.agents import CTFCryptoAgent


def _task() -> Task:
    return Task(task_id="t-1", task_type="ctf_solve", target="local",
                agent_type=AgentType.CTF_CRYPTO, status=TaskStatus.RUNNING,
                payload={"challenge": {"id": "c1", "title": "base64"}})


def _agent(workspace: Path | None) -> CTFCryptoAgent:
    agent = object.__new__(CTFCryptoAgent)
    agent.ctx = SimpleNamespace(
        mode=None, search_enabled=False,
        builtin_ctx={"workspace_root": str(workspace)} if workspace else {})
    return agent


class AttachmentDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_declared_attachments_win(self) -> None:
        task = _task()
        task.payload["challenge"]["attachments"] = ["/declared/a.c", "/declared/b.bin"]
        (self.workspace / "attachments").mkdir()
        (self.workspace / "attachments" / "other.c").write_text("x", encoding="utf-8")
        self.assertEqual(_agent(self.workspace)._attachments_of(task),
                         ["/declared/a.c", "/declared/b.bin"])

    def test_workspace_folder_is_used_when_no_declaration(self) -> None:
        folder = self.workspace / "attachments"
        folder.mkdir()
        (folder / "base64.c").write_text("int main(void){return 0;}\n", encoding="utf-8")
        (folder / "base64.bin").write_bytes(b"\x00\x01")
        found = _agent(self.workspace)._attachments_of(_task())
        self.assertEqual([Path(p).name for p in found], ["base64.bin", "base64.c"])

    def test_missing_folder_is_not_an_error(self) -> None:
        self.assertEqual(_agent(self.workspace)._attachments_of(_task()), [])

    def test_no_workspace_means_no_attachments(self) -> None:
        self.assertEqual(_agent(None)._attachments_of(_task()), [])

    def test_analyze_reports_none_only_when_truly_none(self) -> None:
        agent = _agent(self.workspace)
        self.assertTrue(agent._attachments_of(_task()) == [])


class AttachmentExcerptTests(unittest.IsolatedAsyncioTestCase):
    """正文要排在字符串样本前面，且多条附件时不被回灌上限截掉。"""

    async def test_source_text_survives_multi_attachment_cap(self) -> None:
        folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (folder / "attachments").mkdir()
        names = ["base64.c", "extra1.bin", "extra2.bin", "extra3.bin", "extra4.bin"]
        agent = _agent(folder)
        agent.cache = SimpleNamespace(
            get=lambda *a, **k: None, put=lambda *a, **k: None)
        agent.route_namespace = "test"
        calls: list[dict] = []

        async def call(tool: str, args: dict, **ctx):
            calls.append(args)
            name = Path(str(args["path"])).name
            body = "ALPHABET = a0b1c2d3\n" if name.endswith(".c") else ""
            return SimpleNamespace(ok=True, error="", parsed={
                "magic": "text" if body else "unknown", "size": 20,
                "is_elf": False, "strings": ["x" * 200] * 20,
                "text_excerpt": body, "line_count": 2 if body else None})

        agent.ctx.tools = SimpleNamespace(call=call)
        task = _task()
        task.payload["challenge"]["attachments"] = [
            str(folder / "attachments" / n) for n in names]
        out = await agent._tool_analyze_attachments(task)
        self.assertTrue(out.ok)
        self.assertIn("ALPHABET = a0b1c2d3", out.text, "正文被截掉了")
        self.assertIn("正文（base64.c）", out.text)
        self.assertEqual(len(calls), len(names))


class MaterialsMessageTests(unittest.TestCase):
    """文本附件正文要进常驻 system 消息：否则压缩一折，模型就以为自己没读过。"""

    def _agent_with(self, folder: Path) -> CTFCryptoAgent:
        agent = _agent(folder)
        agent.agent_id = "ctf_crypto-1"
        agent.ctx.audit = SimpleNamespace(log=lambda *a, **k: None)
        return agent

    def test_source_text_is_placed_in_materials_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "attachments").mkdir()
            source = folder / "attachments" / "base64.c"
            source.write_text("ALPHABET = xyz\nint main(void){return 0;}\n", encoding="utf-8")
            (folder / "attachments" / "blob.bin").write_bytes(b"\x00\x01\x02")
            task = _task()
            agent = self._agent_with(folder)
            state: dict = {}
            block = agent._materials_message(task, state)
            self.assertIn("【题目材料·常驻上下文】", block)
            self.assertIn("ALPHABET = xyz", block)
            self.assertIn("base64.c", block)
            self.assertNotIn("blob.bin", block, "二进制不该被当材料读进来")
            # 第二次直接复用，不再重算（前缀稳定，缓存命中）
            self.assertEqual(agent._materials_message(task, state), block)

    def test_no_text_attachment_means_no_block_and_no_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "attachments").mkdir()
            (folder / "attachments" / "a.bin").write_bytes(b"\x00\x01")
            task = _task()
            state: dict = {}
            self.assertEqual(self._agent_with(folder)._materials_message(task, state), "")
            self.assertNotIn("materials_block", state)

    def test_works_even_when_the_session_declares_no_attachments(self) -> None:
        """现场：用户直接拖附件建会话，challenge["attachments"] 是空的。"""
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "attachments").mkdir()
            (folder / "attachments" / "solve.py").write_text("print('hi')\n", encoding="utf-8")
            block = self._agent_with(folder)._materials_message(_task(), {})
            self.assertIn("print('hi')", block)

    def test_total_block_stays_within_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "attachments").mkdir()
            for index in range(6):
                (folder / "attachments" / f"f{index}.py").write_text(
                    "x = '" + "y" * 3000 + "'\n", encoding="utf-8")
            block = self._agent_with(folder)._materials_message(_task(), {})
            self.assertLessEqual(len(block), 6800)


class StageHintTests(unittest.TestCase):
    """附件题两段式推进：先只算中间值，再拿打印出来的常量求解。"""

    def _agent_with(self, tmp: str) -> CTFCryptoAgent:
        folder = Path(tmp)
        (folder / "attachments").mkdir(exist_ok=True)
        (folder / "attachments" / "base64.c").write_text("int main(void){}\n", encoding="utf-8")
        agent = _agent(folder)
        agent.agent_id = "ctf_crypto-1"
        agent.ctx.audit = SimpleNamespace(log=lambda *a, **k: None)
        return agent

    def test_first_stage_asks_for_intermediate_values_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hint = self._agent_with(tmp)._stage_hint(_task(), {})
            self.assertIsNotNone(hint)
            self.assertEqual(hint["key"], "compute")
            self.assertIn("阶段 1/2", hint["text"])
            self.assertIn("中间量", hint["text"])

    def test_second_stage_replays_what_was_printed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = {"executions": 1,
                     "last_stdout": "ALPHABET=a0b1c2d3e4f5g6h7i8j9ZYXWVUTSRQPON+klmnopqrABCDEFGHIJKLM/"}
            hint = self._agent_with(tmp)._stage_hint(_task(), state)
            self.assertEqual(hint["key"], "solve")
            self.assertIn("阶段 2/2", hint["text"])
            self.assertIn("a0b1c2d3", hint["text"], "打印过的常量必须回灌，否则模型从零重推")
            self.assertIn("逆运算", hint["text"])

    def test_ran_but_printed_nothing_goes_back_to_stage_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hint = self._agent_with(tmp)._stage_hint(_task(), {"executions": 2})
            self.assertEqual(hint["key"], "compute")
            self.assertIn("没打印出可用的常量", hint["text"])

    def test_url_only_challenge_gets_no_stage_hint(self) -> None:
        agent = _agent(None)
        task = _task()
        task.payload["challenge"]["url"] = "http://t/"
        self.assertIsNone(agent._stage_hint(task, {}))


if __name__ == "__main__":
    unittest.main()
