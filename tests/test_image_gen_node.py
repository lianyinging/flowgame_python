"""Unit tests for imageGenNode (OpenAI images.generate)."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src.flowgame.chain.nodes import ImageGenNode


class ImageGenNodeTest(unittest.TestCase):
    def _make_node(self) -> ImageGenNode:
        node = ImageGenNode()
        node.id = "img1"
        node.provider = "openai"
        node.base_url = "https://ark.cn-beijing.volces.com/api/v3"
        node.api_key = "test-key"
        node.model = "doubao-seedream-5-0-260128"
        node.size = "2K"
        node.prompt_template = "{{prompt}}"
        node.response_format = "url"
        node.extra_body_json = '{"watermark": true}'
        node.request_timeout_ms = 120000
        from src.flowgame.chain.parameter import Parameter
        from src.flowgame.chain.enums import DataType, RefType

        p = Parameter(
            id="p1",
            name="prompt",
            data_type=DataType.STRING,
            ref_type=RefType.FIXED,
            value="一只猫",
        )
        node.set_parameters([p])
        return node

    def _make_chain(self, node: ImageGenNode) -> MagicMock:
        chain = MagicMock()
        chain.get_parameter_values.return_value = {"prompt": "一只猫"}
        chain.memory = {}
        chain.stop_error = MagicMock()
        return chain

    @patch("openai.OpenAI")
    def test_generate_success(self, mock_openai_cls):
        node = self._make_node()
        chain = self._make_chain(node)

        item = MagicMock()
        item.url = "https://cdn.example.com/a.png"
        item.b64_json = None
        resp = MagicMock()
        resp.data = [item]
        resp.model_dump.return_value = {"data": [{"url": item.url}]}

        client = MagicMock()
        client.images.generate.return_value = resp
        mock_openai_cls.return_value = client

        def resolve_side_effect(chain, node, name, default=None):
            if name == "prompt":
                return "一只猫"
            return default

        with patch(
            "src.flowgame.chain.nodes.resolve_named_field",
            side_effect=resolve_side_effect,
        ):
            result = node.execute(chain)

        self.assertTrue(result["success"])
        self.assertEqual(result["url"], "https://cdn.example.com/a.png")
        kwargs = client.images.generate.call_args.kwargs
        self.assertEqual(kwargs["model"], "doubao-seedream-5-0-260128")
        self.assertEqual(kwargs["size"], "2K")

    @patch("src.flowgame.chain.nodes.requests.post")
    def test_dashscope_qwen_image(self, mock_post):
        node = self._make_node()
        node.provider = "dashscope"
        node.base_url = "https://dashscope.aliyuncs.com/api/v1"
        node.model = "qwen-image-2.0-pro"
        node.size = "2048*2048"
        node.extra_body_json = '{"prompt_extend": true}'
        chain = self._make_chain(node)

        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "output": {
                "choices": [
                    {
                        "message": {
                            "content": [
                                {"image": "https://cdn.example.com/qwen.png"}
                            ]
                        }
                    }
                ]
            }
        }
        mock_post.return_value = resp

        def resolve_side_effect(chain, node, name, default=None):
            if name == "prompt":
                return "一只猫"
            return default

        with patch(
            "src.flowgame.chain.nodes.resolve_named_field",
            side_effect=resolve_side_effect,
        ):
            result = node.execute(chain)

        self.assertTrue(result["success"])
        self.assertEqual(result["url"], "https://cdn.example.com/qwen.png")
        called_url = mock_post.call_args[0][0]
        self.assertIn("multimodal-generation/generation", called_url)
        body = mock_post.call_args.kwargs["json"]
        self.assertEqual(body["model"], "qwen-image-2.0-pro")
        self.assertEqual(body["parameters"]["size"], "2048*2048")
        content = body["input"]["messages"][0]["content"]
        self.assertEqual(content, [{"text": "一只猫"}])

    @patch("src.flowgame.chain.nodes.requests.post")
    def test_dashscope_image_edit(self, mock_post):
        node = self._make_node()
        node.provider = "dashscope"
        node.base_url = "https://dashscope.aliyuncs.com/api/v1"
        node.model = "qwen-image-2.0-pro"
        node.size = "2048*2048"
        chain = self._make_chain(node)
        chain.get_parameter_values.return_value = {
            "prompt": "把背景改成星空",
            "imageUrl": "https://cdn.example.com/src.png",
        }

        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "output": {
                "choices": [
                    {
                        "message": {
                            "content": [
                                {"image": "https://cdn.example.com/edited.png"}
                            ]
                        }
                    }
                ]
            }
        }
        mock_post.return_value = resp

        def resolve_side_effect(chain, node, name, default=None):
            if name == "prompt":
                return "把背景改成星空"
            return default

        with patch(
            "src.flowgame.chain.nodes.resolve_named_field",
            side_effect=resolve_side_effect,
        ):
            result = node.execute(chain)

        self.assertTrue(result["success"])
        body = mock_post.call_args.kwargs["json"]
        content = body["input"]["messages"][0]["content"]
        self.assertEqual(content[0], {"image": "https://cdn.example.com/src.png"})
        self.assertEqual(content[1], {"text": "把背景改成星空"})

    @patch("src.flowgame.chain.nodes.requests.post")
    def test_dashscope_image_url_array_base64(self, mock_post):
        """imageUrl 为 base64 数组时应拆成多张参考图。"""
        from src.flowgame.chain.parameter import Parameter
        from src.flowgame.chain.enums import DataType, RefType

        node = self._make_node()
        node.provider = "dashscope"
        node.base_url = "https://dashscope.aliyuncs.com/api/v1"
        node.model = "qwen-image-2.0-pro"
        node.size = "1024*1024"
        images = [
            "data:image/png;base64,AAA",
            "data:image/png;base64,BBB",
            "data:image/png;base64,CCC",
        ]
        node.set_parameters(
            [
                Parameter(
                    id="p1",
                    name="prompt",
                    data_type=DataType.STRING,
                    ref_type=RefType.FIXED,
                    value="多图融合",
                ),
                Parameter(
                    id="p2",
                    name="imageUrl",
                    data_type=DataType.ARRAY_STRING,
                    ref_type=RefType.REF,
                    ref="start.images",
                ),
            ]
        )
        chain = MagicMock()
        chain.memory = {"start.images": images}
        chain.get = lambda ref: chain.memory.get(ref)
        chain.get_parameter_values.return_value = {
            "prompt": "多图融合",
            "imageUrl": images,
        }
        chain.stop_error = MagicMock()

        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "output": {
                "choices": [
                    {"message": {"content": [{"image": "https://cdn.example.com/out.png"}]}}
                ]
            }
        }
        mock_post.return_value = resp

        with patch(
            "src.flowgame.chain.nodes.resolve_named_field",
            side_effect=lambda *a, **k: "多图融合" if a[2] == "prompt" else None,
        ):
            result = node.execute(chain)

        self.assertTrue(result["success"], result.get("errorMessage"))
        content = mock_post.call_args.kwargs["json"]["input"]["messages"][0]["content"]
        self.assertEqual(
            content,
            [
                {"image": images[0]},
                {"image": images[1]},
                {"image": images[2]},
                {"text": "多图融合"},
            ],
        )

    @patch("src.flowgame.chain.nodes.requests.post")
    def test_dashscope_image_url_single_string(self, mock_post):
        node = self._make_node()
        node.provider = "dashscope"
        node.base_url = "https://dashscope.aliyuncs.com/api/v1"
        node.model = "qwen-image-2.0-pro"
        node.size = "1024*1024"
        chain = self._make_chain(node)
        chain.get_parameter_values.return_value = {
            "prompt": "改背景",
            "imageUrl": "data:image/png;base64,SINGLE",
        }

        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "output": {
                "choices": [
                    {"message": {"content": [{"image": "https://cdn.example.com/out.png"}]}}
                ]
            }
        }
        mock_post.return_value = resp

        with patch(
            "src.flowgame.chain.nodes.resolve_named_field",
            side_effect=lambda *a, **k: "改背景" if a[2] == "prompt" else None,
        ):
            result = node.execute(chain)

        self.assertTrue(result["success"])
        content = mock_post.call_args.kwargs["json"]["input"]["messages"][0]["content"]
        self.assertEqual(
            content,
            [
                {"image": "data:image/png;base64,SINGLE"},
                {"text": "改背景"},
            ],
        )

    def test_missing_api_key(self):
        node = self._make_node()
        node.api_key = ""
        chain = self._make_chain(node)

        def resolve_side_effect(chain, node, name, default=None):
            if name == "prompt":
                return "一只猫"
            return default

        with patch(
            "src.flowgame.chain.nodes.resolve_named_field",
            side_effect=resolve_side_effect,
        ):
            result = node.execute(chain)
        self.assertFalse(result["success"])
        self.assertIn("API Key", result["errorMessage"])


if __name__ == "__main__":
    unittest.main()
