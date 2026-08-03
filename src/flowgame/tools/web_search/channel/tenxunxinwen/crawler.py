"""腾讯新闻搜索渠道（Playwright）。

目标页: https://news.qq.com/search?query=...&page=...
列表字段: title / summary / url；可选继续打开 url 抓取正文 content。

可独立运行::

    python -m web_search.channel.tenxunxinwen.crawler --keyword 小红书 --limit 3 --fetch-content
"""

from __future__ import annotations

import argparse
import logging
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import quote

logger = logging.getLogger(__name__)

CHANNEL_ID = "tenxunxinwen"
CHANNEL_LABEL = "腾讯新闻"
SEARCH_URL = "https://news.qq.com/search?query={keyword}&page={page}"
DEFAULT_MAX_CONTENT_CHARS = 6000
MIN_CONTENT_CHARS = 60

# 在详情页提取正文（腾讯 rain 稿 + 通用兜底）
_EXTRACT_ARTICLE_JS = """() => {
  const pickText = (el) => (el && (el.innerText || el.textContent) || '').trim();
  const title =
    pickText(document.querySelector('h1')) ||
    pickText(document.querySelector('.title')) ||
    (document.querySelector('meta[property="og:title"]')?.content || '') ||
    document.title ||
    '';

  const candidates = [
    '#ArticleContent',
    '.ArticleContent',
    '.content-article',
    '#article-content',
    '.article-content',
    '.rich_media_content',
    'article',
    '[class*="content-article"]',
    '[class*="article-content"]',
    'main',
  ];
  let body = '';
  for (const sel of candidates) {
    const el = document.querySelector(sel);
    const t = pickText(el);
    if (t && t.length > 80) {
      body = t;
      break;
    }
  }
  if (!body) {
    const ps = Array.from(document.querySelectorAll('p'))
      .map((p) => pickText(p))
      .filter((t) => t.length > 20);
    body = ps.join('\\n\\n');
  }
  return { title: title.trim(), content: body.trim() };
}"""


def build_url(keyword: str, page: int) -> str:
    return SEARCH_URL.format(keyword=quote(keyword), page=page)


def extract_items(page) -> List[Dict[str, Any]]:
    return page.evaluate(
        """() => {
            const cards = Array.from(
                document.querySelectorAll('a.hover-link[href*="/rain/a/"]')
            );
            const seen = new Set();
            const items = [];

            for (const a of cards) {
                if (!a.href || seen.has(a.href)) continue;
                seen.add(a.href);

                const titleEl = a.querySelector('p.title');
                const descEl = a.querySelector('p.description');
                const title = (
                    titleEl?.getAttribute('title') ||
                    titleEl?.innerText ||
                    ''
                ).trim();
                if (!title) continue;

                items.push({
                    title,
                    summary: (
                        descEl?.getAttribute('title') ||
                        descEl?.innerText ||
                        ''
                    ).trim(),
                    url: a.href,
                });
            }
            return items;
        }"""
    )


def _normalize_text(raw: str) -> str:
    text = re.sub(r"\s+", " ", (raw or "").replace("\xa0", " ")).strip()
    return text


def extract_article_from_page(page) -> Dict[str, str]:
    """从当前已打开的详情页抽取 title / content。"""
    try:
        data = page.evaluate(_EXTRACT_ARTICLE_JS) or {}
    except Exception:  # noqa: BLE001
        logger.debug("extract_article_from_page evaluate failed", exc_info=True)
        data = {}
    return {
        "title": _normalize_text(str(data.get("title") or "")),
        "content": str(data.get("content") or "").strip(),
    }


def fetch_article_via_playwright(
    url: str,
    *,
    page=None,
    headless: Optional[bool] = None,
    max_chars: int = DEFAULT_MAX_CONTENT_CHARS,
    timeout_ms: int = 45000,
) -> Dict[str, Any]:
    """用 Playwright 打开 url 抓正文。

    若传入已有 ``page``，复用该页（不关闭浏览器）；否则自启浏览器。
    """
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    from src.flowgame.playwright_scripts._browser import chromium_page, env_headless

    target = (url or "").strip()
    result: Dict[str, Any] = {
        "title": "",
        "content": "",
        "url": target,
        "fetchMethod": "playwright",
        "errorMessage": "",
    }
    if not target:
        result["errorMessage"] = "URL 为空"
        return result

    limit = max(500, int(max_chars or DEFAULT_MAX_CONTENT_CHARS))

    def _run(p) -> Dict[str, Any]:
        try:
            p.goto(target, wait_until="domcontentloaded", timeout=timeout_ms)
            p.wait_for_timeout(800)
        except PlaywrightTimeoutError as exc:
            result["errorMessage"] = f"页面加载超时: {exc}"
            return result
        except Exception as exc:  # noqa: BLE001
            result["errorMessage"] = str(exc)
            return result
        extracted = extract_article_from_page(p)
        body = (extracted.get("content") or "").strip()
        result["title"] = extracted.get("title") or ""
        result["content"] = body[:limit]
        if len(body) < MIN_CONTENT_CHARS:
            result["errorMessage"] = (
                f"正文过短（<{MIN_CONTENT_CHARS} 字符），可能被拦截或选择器未命中"
            )
        return result

    if page is not None:
        return _run(page)

    real_headless = env_headless() if headless is None else headless
    with chromium_page(headless=real_headless) as p:
        return _run(p)


def fetch_article(
    url: str,
    *,
    page=None,
    headless: Optional[bool] = None,
    max_chars: int = DEFAULT_MAX_CONTENT_CHARS,
    hint_title: str = "",
) -> Dict[str, Any]:
    """抓取单篇正文：优先 Playwright，失败/过短则回退 ``fetch_url_document``（Jina/requests）。"""
    pw = fetch_article_via_playwright(
        url, page=page, headless=headless, max_chars=max_chars
    )
    body = (pw.get("content") or "").strip()
    if len(body) >= MIN_CONTENT_CHARS:
        if hint_title and not pw.get("title"):
            pw["title"] = hint_title
        return pw

    try:
        from src.flowgame.web.fetch import fetch_url_document

        doc = fetch_url_document(
            url, max_chars=max_chars, hint_title=hint_title or pw.get("title") or None
        )
        if (doc.get("content") or "").strip():
            return {
                "title": doc.get("title") or pw.get("title") or hint_title,
                "content": doc.get("content") or "",
                "url": url,
                "fetchMethod": doc.get("fetchMethod") or "fetch_url_document",
                "errorMessage": doc.get("errorMessage") or "",
            }
    except Exception as exc:  # noqa: BLE001
        logger.info("fetch_url_document fallback failed url=%s err=%s", url, exc)
        if not pw.get("errorMessage"):
            pw["errorMessage"] = str(exc)

    if hint_title and not pw.get("title"):
        pw["title"] = hint_title
    return pw


def crawl(
    keyword: str,
    pages: int = 2,
    start_page: int = 1,
    headless: Optional[bool] = None,
    delay: Optional[float] = None,
    *,
    page=None,
) -> List[Dict[str, Any]]:
    """爬取腾讯新闻搜索结果（原始字段 title / summary / url）。

    若传入 ``page``，在已有 Playwright 页上翻页（不关闭浏览器）。
    """
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    from src.flowgame.playwright_scripts._browser import (
        chromium_page,
        env_delay,
        env_headless,
    )

    results: List[Dict[str, Any]] = []
    seen_urls: set[str] = set()
    end_page = start_page + max(1, pages) - 1
    real_delay = env_delay() if delay is None else max(0.0, delay)
    real_headless = env_headless() if headless is None else headless

    def _crawl_on(p) -> List[Dict[str, Any]]:
        nonlocal results
        for page_no in range(start_page, end_page + 1):
            url = build_url(keyword, page_no)
            logger.info("%s 抓取第 %d 页: %s", CHANNEL_ID, page_no, url)
            try:
                p.goto(url, wait_until="domcontentloaded", timeout=60000)
                p.wait_for_selector(
                    'a.hover-link[href*="/rain/a/"]',
                    timeout=20000,
                )
                p.wait_for_timeout(1000)
            except PlaywrightTimeoutError:
                logger.warning(
                    "%s 第 %d 页超时或无结果，停止翻页", CHANNEL_ID, page_no
                )
                break

            items = extract_items(p)
            if not items:
                logger.warning(
                    "%s 第 %d 页未解析到结果，停止翻页", CHANNEL_ID, page_no
                )
                break

            added = 0
            for item in items:
                href = str(item.get("url") or "").strip()
                if not href or href in seen_urls:
                    continue
                seen_urls.add(href)
                results.append(
                    {
                        "title": str(item.get("title") or "").strip(),
                        "summary": str(item.get("summary") or "").strip(),
                        "url": href,
                    }
                )
                added += 1

            logger.info(
                "%s 第 %d 页新增 %d 条，累计 %d 条",
                CHANNEL_ID,
                page_no,
                added,
                len(results),
            )
            if page_no < end_page and real_delay > 0:
                time.sleep(real_delay)
        return results

    if page is not None:
        return _crawl_on(page)

    with chromium_page(headless=real_headless) as p:
        return _crawl_on(p)


def search(
    keyword: str,
    *,
    limit: int = 10,
    pages: Optional[int] = None,
    start_page: int = 1,
    headless: Optional[bool] = None,
    delay: Optional[float] = None,
    fetch_content: bool = True,
    max_content_chars: int = DEFAULT_MAX_CONTENT_CHARS,
) -> List[Dict[str, Any]]:
    """腾讯新闻联网搜索（Agent / 动态代码入口）。

    ``fetch_content=True``（默认）时，会对每条结果的 url 打开详情页抓取正文，
    写入 ``content``；``summary`` 仍为搜索列表摘要。

    Returns:
        列表，每项含 title / summary / content / url / channel / source / engine /
        contentFetched / fetchMethod（抓正文时）等。
    """
    from src.flowgame.playwright_scripts import playwright_enabled
    from src.flowgame.playwright_scripts._browser import (
        chromium_page,
        env_delay,
        env_headless,
        pages_for_limit,
    )

    kw = (keyword or "").strip()
    if not kw:
        raise ValueError("keyword 不能为空")
    if not playwright_enabled():
        raise RuntimeError(
            "Playwright 未启用或未安装。请确认已 pip install -r requirements.txt "
            "&& playwright install chromium（Docker 镜像已内置）"
        )

    need = max(1, int(limit or 10))
    page_count = (
        max(1, int(pages))
        if pages is not None
        else pages_for_limit(need, per_page=10)
    )
    real_headless = env_headless() if headless is None else headless
    real_delay = env_delay() if delay is None else max(0.0, delay)

    out: List[Dict[str, Any]] = []

    with chromium_page(headless=real_headless) as page:
        raw = crawl(
            keyword=kw,
            pages=page_count,
            start_page=start_page,
            delay=real_delay,
            page=page,
        )
        for item in raw:
            title = str(item.get("title") or "").strip()
            url = str(item.get("url") or "").strip()
            if not title or not url:
                continue
            summary = str(item.get("summary") or "").strip()
            row: Dict[str, Any] = {
                "title": title,
                "summary": summary,
                "content": summary[:800],
                "url": url,
                "channel": CHANNEL_ID,
                "source": CHANNEL_LABEL,
                "engine": CHANNEL_ID,
                "contentFetched": False,
                "fetchMethod": "",
                "errorMessage": "",
            }
            if fetch_content:
                logger.info("%s 抓取正文: %s", CHANNEL_ID, url)
                article = fetch_article(
                    url,
                    page=page,
                    max_chars=max_content_chars,
                    hint_title=title,
                )
                body = (article.get("content") or "").strip()
                row["fetchMethod"] = str(article.get("fetchMethod") or "")
                row["errorMessage"] = str(article.get("errorMessage") or "")
                if body:
                    row["content"] = body
                    row["contentFetched"] = True
                    if article.get("title") and len(str(article["title"])) > 2:
                        # 详情页标题通常更完整，可选覆盖
                        row["pageTitle"] = str(article["title"]).strip()
                if real_delay > 0:
                    time.sleep(min(real_delay, 1.5))
            out.append(row)
            if len(out) >= need:
                break

    return out


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="腾讯新闻搜索（Playwright）")
    parser.add_argument("--keyword", "-k", default="小红书", help="搜索关键词")
    parser.add_argument("--limit", "-n", type=int, default=10, help="最多返回条数")
    parser.add_argument(
        "--pages", "-p", type=int, default=None, help="抓取页数（默认按 limit 估算）"
    )
    parser.add_argument("--start-page", type=int, default=1, help="起始页码")
    parser.add_argument("--headed", action="store_true", help="显示浏览器窗口")
    parser.add_argument("--delay", type=float, default=None, help="翻页间隔秒数")
    parser.add_argument(
        "--fetch-content",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="是否打开结果 URL 抓取正文（默认开启；--no-fetch-content 关闭）",
    )
    parser.add_argument(
        "--max-content-chars",
        type=int,
        default=DEFAULT_MAX_CONTENT_CHARS,
        help=f"正文最大字符数，默认 {DEFAULT_MAX_CONTENT_CHARS}",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    items = search(
        keyword=args.keyword,
        limit=args.limit,
        pages=args.pages,
        start_page=args.start_page,
        headless=not args.headed,
        delay=args.delay,
        fetch_content=bool(args.fetch_content),
        max_content_chars=args.max_content_chars,
    )
    if not items:
        logger.error("未抓取到任何数据")
        return 2
    print(f"共 {len(items)} 条（fetch_content={args.fetch_content}）")
    for item in items[:5]:
        print(f"  · {item['title']}")
        print(f"    {item['url']}")
        if item.get("contentFetched"):
            preview = (item.get("content") or "")[:80].replace("\n", " ")
            print(f"    正文({item.get('fetchMethod')}): {preview}…")
        elif args.fetch_content:
            print(f"    正文失败: {item.get('errorMessage') or 'unknown'}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    raise SystemExit(main())
