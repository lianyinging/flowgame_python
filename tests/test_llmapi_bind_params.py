"""LlmApiNode：厂家 / 模型 / API Key 支持 {{入参}} 模板替换。"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src.flowgame.chain.enums import DataType, RefType
from src.flowgame.chain.nodes import LlmApiNode
from src.flowgame.chain.parameter import Parameter
from src.flowgame.llm.client import LlmChatResult


class LlmApiNodeTemplateBindTest(unittest.TestCase):
    def test_template_fields_resolved_from_input_params(self) -> None:
        node = LlmApiNode()
        node.id = "llm1"
        node.model_provider = "{{modelProvider}}"
        node.model_name = "{{modelName}}"
        node.api_key = "{{apiKey}}"
        node.user_prompt = "hi"
        node.set_parameters(
            [
                Parameter(
                    id="p_provider",
                    name="modelProvider",
                    data_type=DataType.STRING,
                    ref_type=RefType.FIXED,
                    value="openai",
                ),
                Parameter(
                    id="p_model",
                    name="modelName",
                    data_type=DataType.STRING,
                    ref_type=RefType.FIXED,
                    value="gpt-4o-mini",
                ),
                Parameter(
                    id="p_key",
                    name="apiKey",
                    data_type=DataType.STRING,
                    ref_type=RefType.FIXED,
                    value="sk-bound",
                ),
            ]
        )

        chain = MagicMock()
        chain.memory = {}
        chain.get_parameter_values.return_value = {
            "modelProvider": "openai",
            "modelName": "gpt-4o-mini",
            "apiKey": "sk-bound",
        }
        chain.get.return_value = None

        with patch("src.flowgame.llm.LlmClient") as mock_cls:
            mock_cls.return_value.chat.return_value = LlmChatResult(
                ok=True,
                content="pong",
                raw={},
            )
            result = node.execute(chain)

        self.assertEqual(result["output"], "pong")
        kwargs = mock_cls.return_value.chat.call_args.kwargs
        self.assertEqual(kwargs["provider"], "openai")
        self.assertEqual(kwargs["model"], "gpt-4o-mini")
        self.assertEqual(kwargs["api_key"], "sk-bound")

    def test_self_ref_api_key_template_fails_clearly(self) -> None:
        """入参 fixed 也写成 {{apiKey}} 时，不能把原文送给 DeepSeek。"""
        node = LlmApiNode()
        node.id = "llm_bad"
        node.model_provider = "deepseek"
        node.model_name = "deepseek-chat"
        node.api_key = "{{apiKey}}"
        node.user_prompt = "hi"
        node.set_parameters(
            [
                Parameter(
                    id="p_key",
                    name="apiKey",
                    data_type=DataType.STRING,
                    ref_type=RefType.FIXED,
                    value="{{apiKey}}",
                ),
            ]
        )
        chain = MagicMock()
        chain.memory = {}
        chain.get_parameter_values.return_value = {"apiKey": "{{apiKey}}"}
        chain.get.return_value = None

        result = node.execute(chain)
        self.assertIn("API Key 模板未解析", result["errorMessage"])
        # 不应把原文当作 Key 发给上游（此前 401 里会出现 ****ey}}）
        self.assertNotEqual((result.get("errorMessage") or "").strip(), "{{apiKey}}")

    def test_literal_fields_unchanged(self) -> None:
        node = LlmApiNode()
        node.id = "llm2"
        node.model_provider = "deepseek"
        node.model_name = "deepseek-chat"
        node.api_key = "sk-data"
        node.user_prompt = "hi"
        node.set_parameters([])

        chain = MagicMock()
        chain.memory = {}
        chain.get_parameter_values.return_value = {}

        with patch("src.flowgame.llm.LlmClient") as mock_cls:
            mock_cls.return_value.chat.return_value = LlmChatResult(
                ok=True,
                content="ok",
                raw={},
            )
            node.execute(chain)

        kwargs = mock_cls.return_value.chat.call_args.kwargs
        self.assertEqual(kwargs["provider"], "deepseek")
        self.assertEqual(kwargs["model"], "deepseek-chat")
        self.assertEqual(kwargs["api_key"], "sk-data")


if __name__ == "__main__":
    unittest.main()
