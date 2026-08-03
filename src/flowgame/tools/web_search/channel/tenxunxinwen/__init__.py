"""腾讯新闻联网搜索渠道。

动态代码示例::

    from web_search.channel.tenxunxinwen import search

    # 默认会抓取每条 url 的正文到 content
    result = search(keyword=topic, limit=5)

    # 只要搜索列表、不抓正文：
    # result = search(keyword=topic, limit=10, fetch_content=False)
"""
from __future__ import annotations

from .crawler import (
    CHANNEL_ID,
    CHANNEL_LABEL,
    DEFAULT_MAX_CONTENT_CHARS,
    SEARCH_URL,
    build_url,
    crawl,
    extract_article_from_page,
    extract_items,
    fetch_article,
    fetch_article_via_playwright,
    main,
    search,
)

__all__ = [
    "CHANNEL_ID",
    "CHANNEL_LABEL",
    "DEFAULT_MAX_CONTENT_CHARS",
    "SEARCH_URL",
    "build_url",
    "crawl",
    "extract_article_from_page",
    "extract_items",
    "fetch_article",
    "fetch_article_via_playwright",
    "main",
    "search",
]
