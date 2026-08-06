"""LlmClient / URL 规范化 / 内容提取单元测试。"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src.flowgame.llm import (
    LlmClient,
    extract_chat_content,
    normalize_chat_completions_url,
)


class NormalizeUrlTests(unittest.TestCase):
    def test_full_path_unchanged(self) -> None:
        url = "https://api.deepseek.com/v1/chat/completions"
        self.assertEqual(normalize_chat_completions_url(url), url)

    def test_root_appends_v1(self) -> None:
        self.assertEqual(
            normalize_chat_completions_url("https://api.deepseek.com"),
            "https://api.deepseek.com/v1/chat/completions",
        )

    def test_v1_suffix(self) -> None:
        self.assertEqual(
            normalize_chat_completions_url("https://api.deepseek.com/v1"),
            "https://api.deepseek.com/v1/chat/completions",
        )


class ExtractContentTests(unittest.TestCase):
    def test_content_field(self) -> None:
        payload = {
            "choices": [{"message": {"content": "hello"}}],
        }
        self.assertEqual(extract_chat_content(payload), "hello")

    def test_reasoning_fallback(self) -> None:
        payload = {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "reasoning_content": '{"employeeId":"e1"}',
                    }
                }
            ],
        }
        self.assertIn("employeeId", extract_chat_content(payload))


class LlmClientChatTests(unittest.TestCase):
    def test_success(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "ok"}}],
        }
        with patch(
            "src.flowgame.llm.client.requests.post",
            return_value=mock_resp,
        ) as mock_post:
            result = LlmClient(
                api_key="sk-x",
                base_url="https://api.deepseek.com",
                model="deepseek-chat",
            ).chat([{"role": "user", "content": "hi"}])
        self.assertTrue(result.ok)
        self.assertEqual(result.content, "ok")
        args, kwargs = mock_post.call_args
        self.assertIn("/chat/completions", args[0])
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer sk-x")

    def test_http_error(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.json.return_value = {"error": {"message": "bad key"}}
        with patch(
            "src.flowgame.llm.client.requests.post",
            return_value=mock_resp,
        ):
            result = LlmClient(api_key="bad").chat(
                [{"role": "user", "content": "hi"}],
                base_url="https://api.deepseek.com",
                model="deepseek-chat",
            )
        self.assertFalse(result.ok)
        self.assertIn("bad key", result.error)
        self.assertEqual(result.to_legacy_dict()["error"], result.error)


if __name__ == "__main__":
    unittest.main()
