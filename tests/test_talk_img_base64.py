"""Unit tests for talk message imgBase64List."""
from __future__ import annotations

import unittest

from src.flowgame.service import FlowGameExecuteError, FlowGameExecuteService


class TalkImgBase64ListTest(unittest.TestCase):
    def test_normalize_caps_at_three(self):
        svc = FlowGameExecuteService()
        self.assertEqual(
            svc._normalize_talk_img_base64_list(
                ["data:image/png;base64,A", "data:image/png;base64,B", "C", "D"]
            ),
            ["data:image/png;base64,A", "data:image/png;base64,B", "C"],
        )

    def test_message_or_images_required(self):
        svc = FlowGameExecuteService()
        with self.assertRaises(FlowGameExecuteError):
            svc.execute_talk_message({"methodKey": "x", "message": ""})


if __name__ == "__main__":
    unittest.main()
