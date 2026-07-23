"""新浪新闻搜索爬虫（Playwright）。

目标页: https://search.sina.com.cn/search?q=...&tp=news&page=...
列表字段: title / summary / url（另含 source / time）

可独立运行:
  python -m src.flowgame.playwright_scripts.sina_news --keyword 小红书 --pages 2
"""

from __future__ import annotations

import argparse
import logging
import time
from typing import Any, Dict, List
from urllib.parse import quote

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from src.flowgame.playwright_scripts._browser import (
    chromium_page,
    env_delay,
    env_headless,
)

SEARCH_URL = "https://search.sina.com.cn/search?q={keyword}&tp=news&page={page}"
logger = logging.getLogger(__name__)


def build_url(keyword: str, page: int) -> str:
    return SEARCH_URL.format(keyword=quote(keyword), page=page)


def extract_items(page) -> List[Dict[str, Any]]:
    return page.evaluate(
        """() => {
            const cards = Array.from(document.querySelectorAll('.result-text'));
            return cards.map((card, index) => {
                const titleEl = card.querySelector('.result-title a');
                const introEl = card.querySelector('.result-intro');
                const sourceEl = card.querySelector('.source');
                const timeEl = card.querySelector('.time');
                return {
                    index: index + 1,
                    title: (titleEl?.innerText || '').trim(),
                    url: titleEl?.href || '',
                    summary: (introEl?.innerText || '').trim(),
                    source: (sourceEl?.innerText || '').trim(),
                    time: (timeEl?.innerText || '').trim(),
                };
            }).filter(item => item.title && item.url);
        }"""
    )


def crawl(
    keyword: str,
    pages: int = 1,
    headless: bool | None = None,
    delay: float | None = None,
) -> List[Dict[str, Any]]:
    """爬取新浪新闻搜索结果。"""
    results: List[Dict[str, Any]] = []
    seen_urls: set[str] = set()
    real_pages = max(1, pages)
    real_delay = env_delay() if delay is None else max(0.0, delay)
    real_headless = env_headless() if headless is None else headless

    with chromium_page(
        headless=real_headless,
        viewport={"width": 1280, "height": 900},
    ) as page:
        for page_no in range(1, real_pages + 1):
            url = build_url(keyword, page_no)
            logger.info("sina_news 抓取第 %d/%d 页: %s", page_no, real_pages, url)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_selector(".result-title", timeout=20000)
                page.wait_for_timeout(800)
            except PlaywrightTimeoutError:
                logger.warning("sina_news 第 %d 页超时或无结果，停止翻页", page_no)
                break

            items = extract_items(page)
            if not items:
                logger.warning("sina_news 第 %d 页未解析到结果，停止翻页", page_no)
                break

            added = 0
            for item in items:
                if item["url"] in seen_urls:
                    continue
                seen_urls.add(item["url"])
                results.append(
                    {
                        "title": item["title"],
                        "summary": item["summary"],
                        "url": item["url"],
                        "source": item.get("source") or "",
                        "time": item.get("time") or "",
                    }
                )
                added += 1

            logger.info(
                "sina_news 第 %d 页新增 %d 条，累计 %d 条",
                page_no,
                added,
                len(results),
            )
            if page_no < real_pages and real_delay > 0:
                time.sleep(real_delay)

    return results


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="新浪新闻搜索爬虫（Playwright）")
    parser.add_argument("--keyword", "-k", default="小红书", help="搜索关键词")
    parser.add_argument("--pages", "-p", type=int, default=2, help="抓取页数")
    parser.add_argument("--headed", action="store_true", help="显示浏览器窗口")
    parser.add_argument("--delay", type=float, default=1.0, help="翻页间隔秒数")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    items = crawl(
        keyword=args.keyword,
        pages=args.pages,
        headless=not args.headed,
        delay=args.delay,
    )
    if not items:
        logger.error("未抓取到任何数据")
        return 2
    print(f"共 {len(items)} 条")
    for item in items[:3]:
        print(f"  · {item['title']}")
        print(f"    {item['url']}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    raise SystemExit(main())
