"""动态代码节点：模板解析 + markdown 围栏剥除。"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from src.flowgame.chain.js_engine import strip_markdown_code_fence
from src.flowgame.chain.nodes import CodeNode
from src.flowgame.chain.parameter import Parameter
from src.flowgame.chain.enums import DataType, RefType


class StripMarkdownCodeFenceTests(unittest.TestCase):
    def test_python_fence(self) -> None:
        raw = '```python\nfrom scripts import login\nlogin.logout()\nresult = {"ok": True}\n```'
        out = strip_markdown_code_fence(raw)
        self.assertIn("from scripts import login", out)
        self.assertNotIn("```", out)
        self.assertTrue(out.startswith("from scripts"))

    def test_plain(self) -> None:
        self.assertEqual(strip_markdown_code_fence("result = 1"), "result = 1")


class CodeNodeTemplateTests(unittest.TestCase):
    def test_template_code_param_with_fence(self) -> None:
        node = CodeNode("python")
        node.code = "{{code}}"
        node.output_defs = [
            Parameter(name="res", data_type=DataType.OBJECT, ref_type=RefType.REF)
        ]
        script = (
            '```python\n'
            'result = {"ok": True, "n": 1}\n'
            '```'
        )
        chain = MagicMock()
        chain.memory = {}
        chain.get_parameter_values.return_value = {"code": script}

        out = node.execute(chain)
        # 输出定义只有 res，且与 result 键不重合 → 包一层 { res: {...} }
        payload = out.get("res") if isinstance(out.get("res"), dict) else out
        self.assertEqual(payload.get("ok"), True)
        self.assertEqual(payload.get("n"), 1)

    def test_literal_double_brace_was_set_error(self) -> None:
        """未做模板替换时 eval('{{code}}') 会报 unhashable type: 'set'。"""
        node = CodeNode("python")
        node.code = "{{code}}"
        chain = MagicMock()
        chain.memory = {}
        chain.get_parameter_values.return_value = {
            "code": 'result = {"fixed": True}',
        }
        out = node.execute(chain)
        self.assertEqual(out.get("fixed"), True)


if __name__ == "__main__":
    unittest.main()
