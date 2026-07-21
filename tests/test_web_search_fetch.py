"""Unit tests for webSearchNode / fetchUrlNode helpers."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src.flowgame.web.fetch import _html_to_text, fetch_url_document
from src.flowgame.web.search import (
    normalize_engines,
    search_google_news,
    search_web,
    topic_rss_feeds,
)


class NormalizeEnginesTest(unittest.TestCase):
    def test_default(self):
        self.assertEqual(
            normalize_engines(None),
            ["google_news", "duckduckgo"],
        )
        self.assertEqual(
            normalize_engines(""),
            ["google_news", "duckduckgo"],
        )

    def test_array_and_csv(self):
        self.assertEqual(
            normalize_engines(["wikipedia", "duckduckgo", "wikipedia"]),
            ["wikipedia", "duckduckgo"],
        )
        self.assertEqual(
            normalize_engines("google_news,duckduckgo"),
            ["google_news", "duckduckgo"],
        )

    def test_json_string(self):
        self.assertEqual(
            normalize_engines('["wikipedia","duckduckgo"]'),
            ["wikipedia", "duckduckgo"],
        )

    def test_legacy_paid_ignored(self):
        self.assertEqual(
            normalize_engines(["tavily", "bing"]),
            ["google_news", "duckduckgo"],
        )


class TopicRssFeedsTest(unittest.TestCase):
    def test_contains_google_news_and_hn(self):
        feeds = topic_rss_feeds("新能源汽车")
        names = [f["name"] for f in feeds]
        self.assertIn("Google News", names)
        self.assertIn("Google News (EN)", names)
        self.assertIn("Hacker News", names)
        self.assertTrue(any("news.google.com/rss/search" in f["url"] for f in feeds))

    def test_ai_extra_feed(self):
        feeds = topic_rss_feeds("AI 大模型")
        names = [f["name"] for f in feeds]
        self.assertIn("Google News AI", names)


class HtmlToTextTest(unittest.TestCase):
    def test_strip_tags(self):
        html = "<html><head><title>T</title></head><body><p>Hello <b>World</b></p></body></html>"
        text = _html_to_text(html)
        self.assertIn("Hello", text)
        self.assertIn("World", text)
        self.assertNotIn("<b>", text)


class SearchWebTest(unittest.TestCase):
    @patch("src.flowgame.web.search.search_duckduckgo")
    def test_merge_dedupe(self, mock_ddg):
        mock_ddg.return_value = [
            {
                "title": "A",
                "content": "a",
                "url": "https://example.com/a",
                "engine": "duckduckgo",
            },
            {
                "title": "A2",
                "content": "a2",
                "url": "https://example.com/a?x=1",
                "engine": "duckduckgo",
            },
        ]
        result = search_web("query", engines=["duckduckgo"], limit=10)
        self.assertEqual(len(result["documents"]), 1)
        self.assertEqual(result["documents"][0]["title"], "A")

    def test_empty_keyword(self):
        result = search_web("  ", engines=["duckduckgo"], limit=5)
        self.assertEqual(result["documents"], [])
        self.assertTrue(result["errors"])

    @patch("src.flowgame.web.search.requests.get")
    def test_google_news_rss(self, mock_get):
        xml = b"""<?xml version="1.0"?>
        <rss><channel>
          <item>
            <title>Hello News</title>
            <link>https://example.com/hello</link>
            <description>Snippet here</description>
          </item>
        </channel></rss>"""
        resp = MagicMock()
        resp.status_code = 200
        resp.content = xml
        resp.raise_for_status = MagicMock()
        mock_get.return_value = resp
        docs = search_google_news("hello", limit=5)
        self.assertGreaterEqual(len(docs), 1)
        self.assertEqual(docs[0]["title"], "Hello News")
        self.assertEqual(docs[0]["engine"], "google_news")


class FetchUrlTest(unittest.TestCase):
    def test_invalid_url(self):
        result = fetch_url_document("ftp://x")
        self.assertTrue(result["errorMessage"])

    @patch.dict("os.environ", {"FLOWGAME_JINA_ENABLED": "false"}, clear=False)
    @patch("src.flowgame.web.fetch.requests.Session")
    def test_html_fetch_fallback(self, mock_session_cls):
        session = MagicMock()
        mock_session_cls.return_value = session
        resp = MagicMock()
        resp.status_code = 200
        resp.url = "https://example.com/page"
        resp.headers = {"Content-Type": "text/html; charset=utf-8"}
        resp.text = "<html><title>Hi</title><body><p>" + ("Body text " * 20) + "</p></body></html>"
        resp.raise_for_status = MagicMock()
        session.get.return_value = resp
        result = fetch_url_document("https://example.com/page", max_chars=1000)
        self.assertEqual(result["title"], "Hi")
        self.assertIn("Body text", result["content"])
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(result["fetchMethod"], "requests+strip")
        self.assertFalse(result["errorMessage"])

    @patch.dict("os.environ", {"FLOWGAME_JINA_ENABLED": "true"}, clear=False)
    @patch("src.flowgame.web.fetch.requests.Session")
    def test_jina_preferred(self, mock_session_cls):
        session = MagicMock()
        mock_session_cls.return_value = session
        jina_resp = MagicMock()
        jina_resp.status_code = 200
        jina_resp.text = (
            "Title: Jina Title\n\n"
            + ("Readable markdown body from jina reader. " * 10)
        )
        session.get.return_value = jina_resp
        result = fetch_url_document("https://example.com/page", max_chars=2000)
        self.assertEqual(result["fetchMethod"], "jina")
        self.assertEqual(result["title"], "Jina Title")
        self.assertIn("Readable markdown", result["content"])
        self.assertFalse(result["errorMessage"])
        # 只应调用 Jina，不降级
        called_url = session.get.call_args[0][0]
        self.assertTrue(str(called_url).startswith("https://r.jina.ai/"))



if __name__ == "__main__":
    unittest.main()
