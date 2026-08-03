"""腾讯新闻渠道单元测试（默认 Mock，不启动浏览器）。"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src.flowgame.tools.web_search import ensure_web_search_import_path
from src.flowgame.tools.web_search.channel import tenxunxinwen
from src.flowgame.tools.web_search.channel.tenxunxinwen import search as search_fn
from src.flowgame.tools.web_search.channel.tenxunxinwen.crawler import (
    build_url,
    fetch_article,
)

_BROWSER = "src.flowgame.playwright_scripts._browser"
_CRAWLER = "src.flowgame.tools.web_search.channel.tenxunxinwen.crawler"


class TenxunxinwenImportTests(unittest.TestCase):
    def test_ensure_path_and_short_import(self) -> None:
        ensure_web_search_import_path()
        from web_search.channel.tenxunxinwen import search  # noqa: WPS433

        self.assertTrue(callable(search))
        self.assertEqual(tenxunxinwen.CHANNEL_ID, "tenxunxinwen")


class TenxunxinwenSearchTests(unittest.TestCase):
    def test_build_url(self) -> None:
        url = build_url("小红书", 3)
        self.assertIn("news.qq.com/search", url)
        self.assertIn("page=3", url)

    def test_search_requires_keyword(self) -> None:
        with self.assertRaises(ValueError):
            search_fn("  ")

    def test_search_fetches_content(self) -> None:
        mock_page = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__.return_value = mock_page
        mock_cm.__exit__.return_value = False

        with patch(
            "src.flowgame.playwright_scripts.playwright_enabled",
            return_value=True,
        ), patch(f"{_BROWSER}.pages_for_limit", return_value=1), patch(
            f"{_BROWSER}.env_headless", return_value=True
        ), patch(f"{_BROWSER}.env_delay", return_value=0), patch(
            f"{_BROWSER}.chromium_page", mock_cm
        ), patch(
            f"{_CRAWLER}.crawl",
            return_value=[
                {
                    "title": "标题A",
                    "summary": "摘要A",
                    "url": "https://news.qq.com/rain/a/1",
                }
            ],
        ) as mock_crawl, patch(
            f"{_CRAWLER}.fetch_article",
            return_value={
                "title": "详情标题A",
                "content": "这是足够长的正文内容。" * 10,
                "url": "https://news.qq.com/rain/a/1",
                "fetchMethod": "playwright",
                "errorMessage": "",
            },
        ) as mock_fetch:
            items = search_fn(keyword="测试", limit=10, fetch_content=True, delay=0)

        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]["contentFetched"])
        self.assertIn("足够长的正文", items[0]["content"])
        self.assertEqual(items[0]["summary"], "摘要A")
        self.assertEqual(items[0]["pageTitle"], "详情标题A")
        mock_crawl.assert_called_once()
        mock_fetch.assert_called_once()

    def test_search_without_content(self) -> None:
        mock_page = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__.return_value = mock_page
        mock_cm.__exit__.return_value = False

        with patch(
            "src.flowgame.playwright_scripts.playwright_enabled",
            return_value=True,
        ), patch(f"{_BROWSER}.pages_for_limit", return_value=1), patch(
            f"{_BROWSER}.env_headless", return_value=True
        ), patch(f"{_BROWSER}.env_delay", return_value=0), patch(
            f"{_BROWSER}.chromium_page", mock_cm
        ), patch(
            f"{_CRAWLER}.crawl",
            return_value=[
                {
                    "title": "标题A",
                    "summary": "摘要A",
                    "url": "https://news.qq.com/rain/a/1",
                }
            ],
        ):
            items = search_fn(keyword="测试", limit=10, fetch_content=False)

        self.assertEqual(len(items), 1)
        self.assertFalse(items[0]["contentFetched"])
        self.assertEqual(items[0]["content"], "摘要A")


class TenxunxinwenFetchArticleTests(unittest.TestCase):
    @patch(f"{_CRAWLER}.fetch_article_via_playwright")
    def test_fetch_article_uses_playwright_when_long(self, mock_pw) -> None:
        mock_pw.return_value = {
            "title": "T",
            "content": "正文" * 40,
            "url": "https://example.com/a",
            "fetchMethod": "playwright",
            "errorMessage": "",
        }
        doc = fetch_article("https://example.com/a")
        self.assertEqual(doc["fetchMethod"], "playwright")
        self.assertGreater(len(doc["content"]), 60)

    @patch(f"{_CRAWLER}.fetch_article_via_playwright")
    @patch("src.flowgame.web.fetch.fetch_url_document")
    def test_fetch_article_fallback(self, mock_doc, mock_pw) -> None:
        mock_pw.return_value = {
            "title": "",
            "content": "短",
            "url": "https://example.com/a",
            "fetchMethod": "playwright",
            "errorMessage": "正文过短",
        }
        mock_doc.return_value = {
            "title": "Jina标题",
            "content": "回退正文" * 30,
            "fetchMethod": "jina",
            "errorMessage": "",
        }
        doc = fetch_article("https://example.com/a")
        self.assertEqual(doc["fetchMethod"], "jina")
        self.assertIn("回退正文", doc["content"])


if __name__ == "__main__":
    unittest.main()
