"""CTF 模式不做输入完备性校验：用户点了执行就开工。

以前缺赛题清单/URL/附件/平台档案会直接报错，把人挡在表单前反复猜「到底
缺哪一项」。现在一律放行：有清单用清单，有 URL 按 URL 合成题，有附件按
离线题合成，什么都没有就拿任务原文当题面——缺的信息由灵枢在运行期自己
开口问。
"""
import unittest

from spiritscout.core.models import RunMode
from spiritscout.launch import LaunchRequest, prepare_launch


class CtfLaunchAlwaysProceedsTests(unittest.TestCase):
    def test_plain_text_alone_still_launches(self) -> None:
        """只有一句任务描述也开工，不再要求补赛题清单。"""
        plan = prepare_launch(
            LaunchRequest(mode=RunMode.CTF, mission="stega3", has_uploads=False))
        self.assertEqual(plan.authorization.mode, RunMode.CTF)
        self.assertTrue(plan.challenges, "至少合成一道题，否则 agent 没有承载体")
        self.assertEqual(plan.challenges[0]["id"], "mission-1")

    def test_mission_text_becomes_the_challenge_title(self) -> None:
        """任务原文行首一句当标题，模型据此判断要做什么。"""
        plan = prepare_launch(LaunchRequest(
            mode=RunMode.CTF, mission="解这道 stega3\n附件里有隐写"))
        self.assertEqual(plan.challenges[0]["title"], "解这道 stega3")
        self.assertIn("stega3", plan.challenges[0]["description"])

    def test_completely_empty_mission_still_launches(self) -> None:
        """连任务描述都没有也给个中性壳，让灵枢自己问用户。"""
        plan = prepare_launch(LaunchRequest(mode=RunMode.CTF))
        self.assertEqual(plan.authorization.mode, RunMode.CTF)
        self.assertEqual(plan.challenges[0]["title"], "CTF 任务")

    def test_upload_lifts_nothing_because_nothing_blocks(self) -> None:
        plan = prepare_launch(
            LaunchRequest(mode=RunMode.CTF, mission="stega3", has_uploads=True))
        self.assertEqual(plan.authorization.mode, RunMode.CTF)

    def test_mission_url_becomes_the_challenge_entry(self) -> None:
        plan = prepare_launch(LaunchRequest(
            mode=RunMode.CTF, mission="题目在 http://challenge.local:8080/ 上"))
        self.assertEqual(plan.authorization.mode, RunMode.CTF)
        self.assertTrue(any(c.get("url") for c in plan.challenges))

    def test_explicit_yaml_is_honoured(self) -> None:
        """给了清单就用清单，不被兜底壳覆盖。"""
        plan = prepare_launch(LaunchRequest(
            mode=RunMode.CTF,
            challenges_yaml="- id: web-01\n  title: 登录绕过\n  url: http://x.local/\n"))
        self.assertEqual(plan.challenges[0]["id"], "web-01")

    def test_auto_mode_still_routes_by_intent(self) -> None:
        """智能模式行为不变：意图由运行期模型裁决。"""
        plan = prepare_launch(LaunchRequest(mode=None, mission="stega3"))
        self.assertIn(plan.authorization.mode, (RunMode.CTF, RunMode.SRC))


class SrcModeStillNeedsTargetTests(unittest.TestCase):
    """SRC 的校验没动：没目标真的无处安放，模型再问也变不出来。"""

    def test_src_without_target_or_upload_is_still_rejected(self) -> None:
        with self.assertRaises(Exception) as ctx:
            prepare_launch(LaunchRequest(mode=RunMode.SRC, mission="看看这个站"))
        self.assertIn("SRC 模式需要目标 URL", str(ctx.exception))

    def test_src_with_upload_is_allowed(self) -> None:
        plan = prepare_launch(
            LaunchRequest(mode=RunMode.SRC, mission="分析附件", has_uploads=True))
        self.assertEqual(plan.authorization.mode, RunMode.SRC)


if __name__ == "__main__":
    unittest.main()
