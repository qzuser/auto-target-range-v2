"""沙箱路径改写：Windows 工作区路径必须能在 Git Bash 与本机 Python 两边都用。

模型看到的是 `C:\\Users\\...`，写进命令时常变成 `/C:/Users/...`——bash 里直接
No such file or directory。实测一条路线 57 条 shell 调用全栽在这上面。
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from spiritscout.tools.sandbox import (
    _host_shell,
    _to_host_python_paths,
    _to_host_shell_paths,
    sandbox_exec,
)

WINDOWS = os.name == "nt"


class PathRewriteUnitTests(unittest.TestCase):
    @unittest.skipUnless(WINDOWS, "只在 Windows 上改写盘符路径")
    def test_windows_paths_become_msys_form(self) -> None:
        self.assertEqual(_to_host_shell_paths(r"ls C:\Users\admin\x"), "ls /c/Users/admin/x")
        self.assertEqual(_to_host_shell_paths("ls /C:/Users/admin/x"), "ls /c/Users/admin/x")
        self.assertEqual(_to_host_shell_paths("ls C:/Users/admin/x"), "ls /c/Users/admin/x")

    @unittest.skipUnless(WINDOWS, "只在 Windows 上改写盘符路径")
    def test_rewrite_is_idempotent_and_leaves_unix_paths_alone(self) -> None:
        once = _to_host_shell_paths(r"cat C:\tmp\a.txt /tmp/b")
        self.assertEqual(once, "cat /c/tmp/a.txt /tmp/b")
        self.assertEqual(_to_host_shell_paths(once), once)

    @unittest.skipUnless(WINDOWS, "只在 Windows 上改写盘符路径")
    def test_python_literals_get_drive_form(self) -> None:
        self.assertEqual(_to_host_python_paths("open('/c/x/y.txt')"), "open('c:/x/y.txt')")
        self.assertEqual(_to_host_python_paths('Path("/d/data")'), 'Path("d:/data")')
        # 普通 POSIX 路径与多字母段不动
        self.assertEqual(_to_host_python_paths("open('/tmp/x')"), "open('/tmp/x')")
        self.assertEqual(_to_host_python_paths("open('/usr/bin/x')"), "open('/usr/bin/x')")


@unittest.skipUnless(WINDOWS and _host_shell() is not None, "需要 Git Bash（host 后端）")
class SandboxPathIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    async def test_shell_accepts_all_three_path_spellings(self) -> None:
        raw = str(self.workspace)
        spellings = [raw, "C:" + raw[2:], "/C:" + raw[2:].replace("\\", "/")]
        for spelling in spellings:
            result = await sandbox_exec(f"ls {spelling}", language="shell",
                                        workspace_root=raw, timeout=30)
            self.assertTrue(result.ok, f"执行失败: {result.error}")
            self.assertEqual(result.returncode, 0,
                             f"{spelling} 没被改写成 bash 认得的形式: {result.stderr[:200]}")

    async def test_python_script_survives_msys_style_path(self) -> None:
        posix = _to_host_shell_paths(str(self.workspace))
        code = (f"import pathlib\n"
                f"print('EXISTS', pathlib.Path(r'{posix}').is_dir())\n")
        result = await sandbox_exec(code, language="python",
                                    workspace_root=str(self.workspace), timeout=30)
        self.assertTrue(result.ok, f"执行失败: {result.error}")
        self.assertIn("EXISTS True", result.stdout or "")

    async def test_attachments_are_reachable_by_their_natural_name(self) -> None:
        """模型最自然的写法是 `cat attachments/<文件名>`：工作目录里必须有这个入口。

        实际工作目录是 `sandbox/<题>/`，附件在 `workspace/attachments`，晚一步就是
        `No such file`——实测一条路线 95 次 shell 调用全栽在这里。
        """
        (self.workspace / "attachments").mkdir(exist_ok=True)
        (self.workspace / "attachments" / "base64.c").write_text(
            "int main(void){return 0;}\n", encoding="utf-8")
        result = await sandbox_exec("cat attachments/base64.c", language="shell",
                                    workspace_root=str(self.workspace),
                                    workspace_scope="mission-1", timeout=30)
        self.assertTrue(result.ok, f"执行失败: {result.error}")
        self.assertEqual(result.returncode, 0, (result.stderr or "")[:200])
        self.assertIn("int main(void)", result.stdout or "")
        # 结果头里仍要给真实路径，模型换目录时用得上
        self.assertTrue((result.parsed or {}).get("attachments_dir"))


if __name__ == '__main__':
    unittest.main()
