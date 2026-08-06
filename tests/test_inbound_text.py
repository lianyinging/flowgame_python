"""入站 @前缀剥除测试。"""
from __future__ import annotations

import unittest

from src.flowgame.robot_channel.inbound_text import strip_at_mention_prefix


class StripAtMentionTests(unittest.TestCase):
    def test_at_name_space_content(self):
        self.assertEqual(
            strip_at_mention_prefix("@情报助手 帮我查一下", bot_name="情报助手"),
            "帮我查一下",
        )

    def test_generic_without_bot_name(self):
        self.assertEqual(
            strip_at_mention_prefix("@SomeBot 你好世界"),
            "你好世界",
        )

    def test_zero_width_space(self):
        self.assertEqual(
            strip_at_mention_prefix("@机器人\u200b请处理", bot_name="机器人"),
            "请处理",
        )

    def test_no_mention(self):
        self.assertEqual(strip_at_mention_prefix("直接说话"), "直接说话")

    def test_empty(self):
        self.assertEqual(strip_at_mention_prefix(""), "")
        self.assertEqual(strip_at_mention_prefix("   "), "")


if __name__ == "__main__":
    unittest.main()
