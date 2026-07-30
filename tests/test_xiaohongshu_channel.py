"""小红书渠道可被动态代码 import。"""
from __future__ import annotations

import unittest

from src.flowgame.chain.js_engine import eval_python
from src.flowgame.media_channel.xiaohongshu import ensure_scripts_import_path


class XiaohongshuImportTests(unittest.TestCase):
    def test_ensure_path_and_import_feed(self):
        ensure_scripts_import_path()
        from scripts import feed  # noqa: WPS433

        self.assertTrue(callable(feed.feed_detail))

    def test_eval_python_can_import_scripts(self):
        code = """
from scripts import feed
result = {"has_feed_detail": callable(feed.feed_detail)}
"""
        out = eval_python(code, {}, {})
        self.assertEqual(out, {"has_feed_detail": True})


if __name__ == "__main__":
    unittest.main()
