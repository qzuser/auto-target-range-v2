"""CTF 模式只在「纯文本、无链接、无附件」时才要求补赛题清单。

赛题附件多是 zip/rar/7z 这类压缩包，按后缀设白名单会把正常题目挡在门外。
这里锁住三件事：有附件就放行、有 URL 就放行、什么都没有才拦。
"""
import unittest

from spiritscout.core.models import RunMode
from spiritscout.launch import LaunchRequest, prepare_launch

MESSAGE = "CTF 模式需要赛题清单"


class CtfChallengeRequirementTests(unittest.TestCase):
    def test_plain_text_without_links_or_uploads_is_rejected(self) -> None:
        req = LaunchRequest(mode=RunMode.CTF, mission="stega3", has_uploads=False)
        with self.assertRaises(Exception) as ctx:
            prepare_launch(req)
        self.assertIn(MESSAGE, str(ctx.exception))

    def test_upload_lifts_the_requirement(self) -> None:
        """带了附件（不论后缀）就不该再要求赛题清单。"""
        plan = prepare_launch(
            LaunchRequest(mode=RunMode.CTF, mission="stega3", has_uploads=True))
        self.assertEqual(plan.authorization.mode, RunMode.CTF)

    def test_mission_url_lifts_the_requirement(self) -> None:
        plan = prepare_launch(LaunchRequest(
            mode=RunMode.CTF, mission="题目在 http://challenge.local:8080/ 上", has_uploads=False))
        self.assertEqual(plan.authorization.mode, RunMode.CTF)

    def test_auto_mode_is_never_blocked(self) -> None:
        """智能模式不在这里拦：意图由运行期模型裁决。"""
        plan = prepare_launch(LaunchRequest(mode=None, mission="stega3"))
        self.assertIn(plan.authorization.mode, (RunMode.CTF, RunMode.SRC))


if __name__ == "__main__":
    unittest.main()
