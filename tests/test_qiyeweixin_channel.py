"""企业微信渠道可被动态代码 import。"""
from __future__ import annotations

import unittest

from src.flowgame.chain.js_engine import eval_python
from src.flowgame.robot_channel.qiyeweixing import ensure_wecom_import_path


class QiyeweixinImportTests(unittest.TestCase):
    def test_ensure_path_and_import_wecom(self):
        ensure_wecom_import_path()
        from wecom import aibot, webhook  # noqa: WPS433

        self.assertTrue(callable(aibot.send_markdown))
        self.assertTrue(callable(webhook.send_text))
        self.assertTrue(callable(aibot.collect_messages))

    def test_eval_python_can_import_wecom(self):
        code = """
from wecom import aibot, webhook
result = {
    "has_send_markdown": callable(aibot.send_markdown),
    "has_webhook": callable(webhook.send_markdown),
}
"""
        out = eval_python(code, {}, {})
        self.assertEqual(
            out,
            {"has_send_markdown": True, "has_webhook": True},
        )

    def test_webhook_requires_key(self):
        ensure_wecom_import_path()
        from wecom import webhook  # noqa: WPS433

        with self.assertRaises(ValueError):
            webhook.send_text("x", key="")


if __name__ == "__main__":
    unittest.main()
