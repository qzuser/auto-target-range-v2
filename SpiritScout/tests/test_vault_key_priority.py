"""密钥注入的优先级：加密密钥库 > 配置里写死的 > 环境变量兜底。

这条链决定"没填 key 也能进控制台"能不能成立：控制台启动只加载配置，
配置里不再引用环境变量占位符，所以缺 key 不再是启动失败，而只是这一轮
没有可用凭据——用户到「模型」页填一次就进库了。
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from spiritscout.config.settings import ModelEntry  # noqa: E402
from spiritscout.web import vault  # noqa: E402

_ENV_NAMES = ("SPIRITSCOUT_REMOTE_LLM_KEY", "SPIRITSCOUT_LLM_KEY_ZEROHH")


def _entry(api_key: str = "", provider_ref: str = "zerohh") -> ModelEntry:
    return ModelEntry(
        model="cn:deepseek-v4.1-flash",
        provider_ref=provider_ref,
        api_key=api_key,
        context_window=131072,
    )


class ApplyKeysPriorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        vault.configure(str(Path(self._tmp.name)))
        self._saved = {name: os.environ.pop(name, None) for name in _ENV_NAMES}

    def tearDown(self) -> None:
        for name, value in self._saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        self._tmp.cleanup()

    def test_vault_key_wins_over_config(self) -> None:
        vault.set_key("zerohh", "from-vault")
        out = vault.apply_keys([_entry("from-yaml")])
        self.assertEqual(out[0].api_key, "from-vault")

    def test_config_key_survives_without_vault(self) -> None:
        out = vault.apply_keys([_entry("from-yaml")])
        self.assertEqual(out[0].api_key, "from-yaml")

    def test_env_used_when_vault_and_config_are_empty(self) -> None:
        os.environ["SPIRITSCOUT_REMOTE_LLM_KEY"] = "from-env"
        out = vault.apply_keys([_entry()])
        self.assertEqual(out[0].api_key, "from-env")

    def test_provider_specific_env_wins_over_generic(self) -> None:
        os.environ["SPIRITSCOUT_REMOTE_LLM_KEY"] = "generic"
        os.environ["SPIRITSCOUT_LLM_KEY_ZEROHH"] = "specific"
        out = vault.apply_keys([_entry()])
        self.assertEqual(out[0].api_key, "specific")

    def test_no_key_anywhere_stays_empty_and_does_not_raise(self) -> None:
        # 这是"没填 key 也能进控制台"的底线：不抛异常、留空、启动照常。
        out = vault.apply_keys([_entry()])
        self.assertEqual(out[0].api_key, "")

    def test_entry_without_provider_ref_is_untouched(self) -> None:
        os.environ["SPIRITSCOUT_REMOTE_LLM_KEY"] = "from-env"
        out = vault.apply_keys([_entry(api_key="", provider_ref="")])
        self.assertEqual(out[0].api_key, "")


if __name__ == "__main__":
    unittest.main()
