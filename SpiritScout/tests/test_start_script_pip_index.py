"""启动脚本的依赖下载源：默认国内镜像、可换源、镜像失败自动退官方源。

`start-local.ps1` 是 PowerShell 脚本，没法 import；但它把源解析单独做成了
`Resolve-PipIndex` / `-ShowPipIndex`，装依赖的 `Invoke-PipInstall` 又能用 AST 抠出来
单独跑（桩 python 记录参数），所以两条最要紧的行为都能真跑一遍而不是读文本猜。

没有 PowerShell 的环境（部分 Linux CI）整体 skip，不算失败。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "start-local.ps1"
MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"
OFFICIAL = "https://pypi.org/simple"


def _powershell() -> str | None:
    """找一个能跑的 PowerShell：Windows 优先 powershell.exe，跨平台退 pwsh。"""
    for name in ("powershell", "powershell.exe", "pwsh", "pwsh.exe"):
        found = shutil.which(name)
        if found:
            return found
    return None


PWSH = _powershell()


def _run(args: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    merged = dict(os.environ)
    merged.pop("SPIRITSCOUT_PIP_INDEX", None)
    if env:
        merged.update(env)
    return subprocess.run(
        [PWSH, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=merged, timeout=120,
    )


def _index_of(stdout: str) -> str:
    for line in stdout.splitlines():
        if line.startswith("PIP_INDEX="):
            return line.split("=", 1)[1].strip()
    return ""


def _label_of(stdout: str) -> str:
    for line in stdout.splitlines():
        if line.startswith("PIP_INDEX_LABEL="):
            return line.split("=", 1)[1].strip()
    return ""


@unittest.skipIf(PWSH is None, "没有 PowerShell，跳过启动脚本的源解析测试")
class PipIndexResolutionTests(unittest.TestCase):
    """装依赖默认走国内源，还有换源与退官方源的两条路。"""

    def setUp(self) -> None:
        self.assertTrue(SCRIPT.is_file(), f"缺启动脚本：{SCRIPT}")

    def test_default_is_domestic_mirror(self) -> None:
        result = _run(["-ShowPipIndex"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_index_of(result.stdout), MIRROR)
        self.assertIn("清华", _label_of(result.stdout))

    def test_env_variable_overrides_default(self) -> None:
        result = _run(["-ShowPipIndex"],
                      env={"SPIRITSCOUT_PIP_INDEX": "https://mirrors.aliyun.com/pypi/simple/"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_index_of(result.stdout), "https://mirrors.aliyun.com/pypi/simple/")
        self.assertNotIn("清华", _label_of(result.stdout), "自定义源不该还挂清华的名")

    def test_parameter_beats_env_variable(self) -> None:
        result = _run(["-ShowPipIndex", "-PipIndex", "https://mirrors.ustc.edu.cn/pypi/simple"],
                      env={"SPIRITSCOUT_PIP_INDEX": "https://mirrors.aliyun.com/pypi/simple/"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_index_of(result.stdout), "https://mirrors.ustc.edu.cn/pypi/simple")

    def test_official_keyword_switches_back(self) -> None:
        for word in ("official", "pypi", "default"):
            with self.subTest(word=word):
                result = _run(["-ShowPipIndex", "-PipIndex", word])
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(_index_of(result.stdout), OFFICIAL)
                self.assertIn("官方", _label_of(result.stdout))

    def test_bare_word_is_rejected_with_hint(self) -> None:
        result = _run(["-ShowPipIndex", "-PipIndex", "tuna"])
        self.assertNotEqual(result.returncode, 0, "少了协议的裸词必须报错，不能悄悄装到别的源上")
        self.assertIn("完整地址", result.stderr + result.stdout)


@unittest.skipIf(PWSH is None, "没有 PowerShell，跳过启动脚本的源回退测试")
@unittest.skipIf(os.name != "nt", "桩 python 用 cmd 批处理写的，只在 Windows 上跑")
class MirrorFallbackTests(unittest.TestCase):
    """镜像装不下时自动退官方源重试一次，并把后续步骤切到官方源。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        # 桩 python：把收到的参数追加进 calls.txt；源是那台死掉的 127.0.0.1:9 就返回 7
        # （模拟镜像装不下），其余一律成功——这样「镜像通」和「镜像挂」两条路都能测。
        stub = self.dir / "stub.cmd"
        stub.write_text(
            "@echo off\r\n"
            'echo %* >> "%~dp0calls.txt"\r\n'
            'echo %* | findstr /c:"127.0.0.1:9" >nul 2>&1 && exit /b 7\r\n'
            "exit /b 0\r\n",
            encoding="ascii",
        )
        self.stub = stub
        self.calls = self.dir / "calls.txt"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run_fallback(self, accepted_index: str) -> subprocess.CompletedProcess:
        # 用 AST 把 Invoke-PipInstall 从脚本里原样抠出来跑：测的是真代码，不是复制品
        harness = self.dir / "harness.ps1"
        harness.write_text(
            "$ErrorActionPreference = 'Stop'\n"
            f"$src = '{SCRIPT}'\n"
            "$tokens = $null; $errors = $null\n"
            "$ast = [System.Management.Automation.Language.Parser]::ParseFile($src, [ref]$tokens, [ref]$errors)\n"
            "$fn = $ast.Find({ param($n) $n -is "
            "[System.Management.Automation.Language.FunctionDefinitionAst] -and "
            "$n.Name -eq 'Invoke-PipInstall' }, $true)\n"
            f"$script:venvPy = '{self.stub}'\n"
            f"$root = '{REPO_ROOT}'\n"
            f"$script:pipIndex = '{accepted_index}'\n"
            f"$script:OfficialIndex = '{OFFICIAL}'\n"
            "Invoke-Expression $fn.Extent.Text\n"
            "$code = Invoke-PipInstall 'SpiritScout'\n"
            'Write-Host "RESULT=$code"\n'
            'Write-Host "INDEX=$script:pipIndex"\n',
            # 仓库路径里有中文，PowerShell 5.1 读无 BOM 的 UTF-8 会乱码到把引号拆坏
            encoding="utf-8-sig",
        )
        return subprocess.run(
            [PWSH, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
        )

    def test_mirror_failure_falls_back_to_official(self) -> None:
        result = self._run_fallback("https://127.0.0.1:9/simple")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RESULT=0", result.stdout, "回退后应当算成功")
        self.assertIn(f"INDEX={OFFICIAL}", result.stdout, "后续步骤要跟着切到官方源")

        calls = [line.strip() for line in self.calls.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(calls), 2, "镜像失败只该重试一次，不是无限重试")
        self.assertIn("--index-url https://127.0.0.1:9/simple", calls[0])
        self.assertIn(f"--index-url {OFFICIAL}", calls[1])
        self.assertIn("--editable SpiritScout", calls[1])

    def test_success_on_mirror_does_not_touch_official(self) -> None:
        result = self._run_fallback(MIRROR)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RESULT=0", result.stdout)
        calls = [line.strip() for line in self.calls.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(calls), 1, "镜像通了就不该再多打一次官方源")
        self.assertIn(f"--index-url {MIRROR}", calls[0])


if __name__ == "__main__":
    unittest.main()
