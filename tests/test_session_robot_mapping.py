"""会话机器人映射单元测试。"""
from __future__ import annotations

import unittest

from src.flowgame.robot_channel.mapping import (
    apply_input_mapping,
    apply_output_mapping,
    extract_business_payload,
)
from src.flowgame.robot_channel.models import FieldMapping


class MappingTests(unittest.TestCase):
    def test_input_mapping(self):
        inbound = {
            "text": "你好",
            "target": "chat_abc",
            "userid": "u1",
            "chattype": "group",
        }
        mappings = [
            FieldMapping("text", "message"),
            FieldMapping("target", "chatId"),
            FieldMapping("userid", "userId"),
        ]
        vars_ = apply_input_mapping(inbound, mappings)
        self.assertEqual(
            vars_,
            {"message": "你好", "chatId": "chat_abc", "userId": "u1"},
        )

    def test_output_from_slim_result(self):
        result = {"assistantMessage": "收到了"}
        actions = apply_output_mapping(
            result,
            [FieldMapping("assistantMessage", "reply_markdown")],
        )
        self.assertEqual(actions, {"reply_markdown": "收到了"})

    def test_output_from_full_result_and_nested(self):
        result = {
            "apiOutput": {"assistantMessage": {"content": "嵌套内容"}},
            "nodeExecutions": [],
        }
        actions = apply_output_mapping(
            result,
            [FieldMapping("assistantMessage", "reply_markdown")],
        )
        self.assertEqual(actions, {"reply_markdown": "嵌套内容"})

    def test_output_reply_file_and_text(self):
        result = {
            "assistantMessage": "报告如下",
            "filePath": "/tmp/a.pdf",
        }
        actions = apply_output_mapping(
            result,
            [
                FieldMapping("assistantMessage", "reply_markdown"),
                FieldMapping("filePath", "reply_file"),
            ],
        )
        self.assertEqual(actions["reply_markdown"], "报告如下")
        self.assertEqual(actions["reply_file"], ["/tmp/a.pdf"])

    def test_output_reply_file_list(self):
        result = {"files": ["/a.pdf", "/b.png", "/a.pdf"]}
        actions = apply_output_mapping(
            result,
            [FieldMapping("files", "reply_file")],
        )
        self.assertEqual(actions["reply_file"], ["/a.pdf", "/b.png"])

    def test_extract_business_payload(self):
        self.assertEqual(
            extract_business_payload({"apiOutput": {"a": 1}, "nodeExecutions": []}),
            {"a": 1},
        )
        self.assertEqual(extract_business_payload({"a": 1}), {"a": 1})


if __name__ == "__main__":
    unittest.main()
