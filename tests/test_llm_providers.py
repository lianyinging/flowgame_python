"""预置模型厂家解析单元测试。"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src.flowgame.llm import (
    LlmClient,
    infer_provider_from_url,
    normalize_provider_id,
    resolve_provider_base_url,
)


class ProviderResolveTests(unittest.TestCase):
    def test_infer_from_url(self) -> None:
        self.assertEqual(
            infer_provider_from_url("https://api.deepseek.com/chat/completions"),
            "deepseek",
        )
        self.assertEqual(
            infer_provider_from_url("https://api.openai.com/v1/chat/completions"),
            "openai",
        )
        self.assertEqual(
            infer_provider_from_url(
                "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
            ),
            "qwen",
        )

    def test_normalize_provider(self) -> None:
        self.assertEqual(normalize_provider_id("DeepSeek"), "deepseek")
        self.assertEqual(
            normalize_provider_id("", legacy_url="https://api.moonshot.cn/v1"),
            "moonshot",
        )
        self.assertEqual(normalize_provider_id("unknown"), "deepseek")

    def test_chat_uses_provider_base_not_custom_url(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "ok"}}],
        }
        with patch(
            "src.flowgame.llm.client.requests.post",
            return_value=mock_resp,
        ) as mock_post:
            result = LlmClient().chat(
                [{"role": "user", "content": "hi"}],
                provider="deepseek",
                model="deepseek-v4-flash",
                api_key="sk-x",
                base_url="https://evil.example.com",  # 应被忽略
            )
        self.assertTrue(result.ok)
        called_url = mock_post.call_args[0][0]
        self.assertIn("api.deepseek.com", called_url)
        self.assertNotIn("evil.example.com", called_url)
        self.assertEqual(
            resolve_provider_base_url("deepseek"),
            "https://api.deepseek.com",
        )


if __name__ == "__main__":
    unittest.main()
