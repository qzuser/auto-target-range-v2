"""工具纠错提示：模型给错参数时，错误里要说清「你给的是什么」。

真实跑题时暴露的两个坑：

- `python`/`shell` 的内容参数被模型换成自创键名（`script`/`arguments`），
  旧提示只说「需要 code 参数」，模型判断不出是键名写错还是没传，
  于是原样重试六次，把回合烧空。
- `action` 填了表外的近义词（如 `read`）时，旧提示只列合法值，
  不说收到的是什么，模型同样无法自我纠正。
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, Mock

from spiritscout.core.models import RunMode, Scope
from spiritscout.ctf.agents import _missing_exec_param
from spiritscout.policy.engine import PolicyEngine
from spiritscout.policy.scope import ScopeGuard
from spiritscout.tools.registry import ToolRegistry
from spiritscout.tools.spec import ToolKind, ToolResult, ToolSpec


def _registry(fn: AsyncMock) -> ToolRegistry:
    registry = ToolRegistry(
        Mock(), policy=PolicyEngine(RunMode.CTF, ScopeGuard(Scope(local_analysis=True))))
    registry.register_builtin("sandbox_exec", fn, ToolSpec(
        name="sandbox_exec", kind=ToolKind.BUILTIN, action_required=True,
        allowed_params={"code", "language", "timeout", "action", "log_name"}))
    return registry


class MissingExecParamHintTests(unittest.TestCase):
    def test_hint_names_the_field_and_what_arrived(self) -> None:
        text = _missing_exec_param("python", "code", {"script": "print(1)", "action": "analysis"})
        self.assertIn('"code"', text)
        self.assertIn("Python 代码", text)
        self.assertIn("action、script", text)

    def test_hint_handles_shell_and_empty_args(self) -> None:
        text = _missing_exec_param("shell", "command", {})
        self.assertIn('"command"', text)
        self.assertIn("shell 命令", text)
        self.assertIn("空参数", text)


class ActionCategoryHintTests(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_action_echoes_supplied_value(self) -> None:
        fn = AsyncMock(return_value=ToolResult(tool="sandbox_exec", ok=True))
        result = await _registry(fn).call("sandbox_exec", {"code": "print(1)", "action": "read"})
        self.assertFalse(result.ok)
        self.assertIn("'read'", result.error)
        self.assertIn("analysis", result.error)
        fn.assert_not_awaited()

    async def test_valid_action_still_runs(self) -> None:
        fn = AsyncMock(return_value=ToolResult(tool="sandbox_exec", ok=True, stdout="ok"))
        result = await _registry(fn).call("sandbox_exec", {"code": "print(1)", "action": "analysis"})
        self.assertTrue(result.ok)
        fn.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
