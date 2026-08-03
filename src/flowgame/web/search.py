"""Web search with merge / URL dedupe.

网页搜索节点当前仅开放腾讯新闻（Playwright，``qq_news``）。
其它历史引擎 id 在 normalize 时忽略并回退默认。
"""
from __future__ import annotations

import html
import logging
import os
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import quote_plus, unquote, urlparse

import requests

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (compatible; FlowGameBot/1.0; +https://flowgame.mgdeep.com)"
)
DEFAULT_TIMEOUT = 20
# 节点可选引擎：仅腾讯新闻
ALLOWED_ENGINES = ("qq_news",)
# 历史引擎（付费或已下架），normalize 时忽略
LEGACY_PAID_ENGINES = frozenset(
    {
        "tavily",
        "bing",
        "google_news",
        "duckduckgo",
        "wikipedia",
        "sina_news",
    }
)
DEFAULT_ENGINES = ["qq_news"]


def _clean_text(raw: str) -> str:
    text = html.unescape(raw or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _unwrap_ddg_url(href: str) -> str:
    if "uddg=" in href:
        m = re.search(r"uddg=([^&]+)", href)
        if m:
            return unquote(m.group(1))
    if href.startswith("//"):
        return "https:" + href
    return href


def _normalize_url_key(url: str) -> str:
    return url.split("?")[0].rstrip("/").lower()


def _doc(
    title: str,
    content: str,
    url: str,
    engine: str,
    *,
    source: str = "",
) -> Dict[str, Any]:
    return {
        "title": title,
        "content": content,
        "url": url,
        "engine": engine,
        "source": source or engine,
    }


def _xml_text(el: ET.Element, names: tuple[str, ...]) -> str:
    for name in names:
        child = el.find(name)
        if child is not None and (child.text or "").strip():
            return (child.text or "").strip()
        if child is not None and list(child):
            return "".join(child.itertext()).strip()
    return ""


def _xml_link(el: ET.Element) -> str:
    link = el.find("link")
    if link is not None:
        if (link.text or "").strip():
            return (link.text or "").strip()
        href = link.attrib.get("href")
        if href:
            return href.strip()
    link = el.find("{http://www.w3.org/2005/Atom}link")
    if link is not None:
        return (link.attrib.get("href") or link.text or "").strip()
    return ""


def topic_rss_feeds(search_query: str) -> List[Dict[str, str]]:
    """按检索词拼动态 RSS（与 demo_ai_news.topic_rss_feeds 对齐，不含固定行业源）。"""
    q = quote_plus(search_query.strip() or "news")
    feeds = [
        {
            "name": "Google News",
            "url": f"https://news.google.com/rss/search?q={q}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        },
        {
            "name": "Google News (EN)",
            "url": f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en",
        },
        {
            "name": "Hacker News",
            "url": f"https://hnrss.org/newest?q={q}",
        },
    ]
    if re.search(r"\bai\b|人工智能|llm|大模型", search_query, flags=re.I):
        q2 = quote_plus("artificial intelligence OR LLM")
        feeds.insert(
            2,
            {
                "name": "Google News AI",
                "url": f"https://news.google.com/rss/search?q={q2}&hl=en-US&gl=US&ceid=US:en",
            },
        )
    return feeds


def fetch_rss_feed(
    feed_url: str,
    source_name: str,
    *,
    limit: int,
    engine: str = "google_news",
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    try:
        resp = requests.get(
            feed_url,
            timeout=DEFAULT_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as exc:  # noqa: BLE001
        logger.warning("rss fetch failed source=%s err=%s", source_name, exc)
        return out

    items = root.findall(".//item")
    if not items:
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        items = root.findall(".//atom:entry", ns) or root.findall(
            ".//{http://www.w3.org/2005/Atom}entry"
        )

    for item in items[: max(1, limit)]:
        title = _clean_text(
            _xml_text(item, ("title", "{http://www.w3.org/2005/Atom}title"))
        )
        link = _xml_link(item).strip()
        desc = _clean_text(
            _xml_text(
                item,
                (
                    "description",
                    "summary",
                    "{http://www.w3.org/2005/Atom}summary",
                ),
            )
        )
        if not title or not link:
            continue
        if urlparse(link).scheme not in ("http", "https"):
            continue
        out.append(
            _doc(title, desc[:500], link, engine, source=source_name)
        )
        if len(out) >= limit:
            break
    return out


def search_google_news(keyword: str, limit: int) -> List[Dict[str, Any]]:
    """主题 RSS：Google News（中/英）+ Hacker News，与 demo Scout 主通道一致。"""
    feeds = topic_rss_feeds(keyword)
    per_feed = max(3, min(limit, 12))
    merged: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for feed in feeds:
        hits = fetch_rss_feed(
            feed["url"], feed["name"], limit=per_feed, engine="google_news"
        )
        for doc in hits:
            key = _normalize_url_key(str(doc.get("url") or ""))
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(doc)
            if len(merged) >= limit:
                return merged
    return merged


def _search_duckduckgo_once(query: str, limit: int) -> List[Dict[str, Any]]:
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    resp = requests.get(
        url,
        timeout=DEFAULT_TIMEOUT,
        headers={"User-Agent": USER_AGENT},
    )
    resp.raise_for_status()
    html_text = resp.text
    out: List[Dict[str, Any]] = []

    for m in re.finditer(
        r'class="result__a"[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>'
        r'.*?class="result__snippet"[^>]*>(?P<snippet>.*?)</(?:a|td|div)',
        html_text,
        flags=re.I | re.S,
    ):
        title = _clean_text(m.group("title"))
        real = _unwrap_ddg_url(html.unescape(m.group("href")))
        snippet = _clean_text(m.group("snippet"))
        if title and real and urlparse(real).scheme in ("http", "https"):
            out.append(
                _doc(title, snippet[:500], real, "duckduckgo", source="DuckDuckGo")
            )
        if len(out) >= limit:
            break

    if not out:
        for m in re.finditer(
            r'class="result__a"[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
            html_text,
            flags=re.I | re.S,
        ):
            title = _clean_text(m.group("title"))
            real = _unwrap_ddg_url(html.unescape(m.group("href")))
            if title and real and urlparse(real).scheme in ("http", "https"):
                out.append(
                    _doc(title, "", real, "duckduckgo", source="DuckDuckGo")
                )
            if len(out) >= limit:
                break
    return out


def search_duckduckgo(keyword: str, limit: int) -> List[Dict[str, Any]]:
    """DuckDuckGo HTML；与 demo 一样尝试多个检索变体后合并去重。"""
    queries = [keyword, f"{keyword} news"]
    if keyword.lower() in {"ai", "人工智能"}:
        queries.extend(["artificial intelligence", "LLM AI news"])

    merged: List[Dict[str, Any]] = []
    seen: set[str] = set()
    per_q = max(3, min(limit, 12))
    for q in queries:
        try:
            hits = _search_duckduckgo_once(q, per_q)
        except Exception as exc:  # noqa: BLE001
            logger.warning("duckduckgo query=%r failed: %s", q, exc)
            continue
        for doc in hits:
            key = _normalize_url_key(str(doc.get("url") or ""))
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(doc)
            if len(merged) >= limit:
                return merged
    return merged


def search_wikipedia(keyword: str, limit: int) -> List[Dict[str, Any]]:
    """MediaWiki search API — free, no API key."""
    lang = (os.getenv("WIKIPEDIA_LANG") or "zh").strip() or "zh"
    lang = re.sub(r"[^a-zA-Z\-]", "", lang) or "zh"
    api = f"https://{lang}.wikipedia.org/w/api.php"
    resp = requests.get(
        api,
        params={
            "action": "query",
            "list": "search",
            "srsearch": keyword,
            "srlimit": min(max(limit, 1), 20),
            "format": "json",
            "utf8": 1,
        },
        timeout=DEFAULT_TIMEOUT,
        headers={"User-Agent": USER_AGENT},
    )
    resp.raise_for_status()
    payload = resp.json() if resp.content else {}
    hits = (
        payload.get("query", {}).get("search")
        if isinstance(payload, dict)
        else None
    )
    out: List[Dict[str, Any]] = []
    if not isinstance(hits, list):
        return out
    for item in hits:
        if not isinstance(item, dict):
            continue
        title = _clean_text(str(item.get("title") or ""))
        snippet = _clean_text(str(item.get("snippet") or ""))
        if not title:
            continue
        page_url = (
            f"https://{lang}.wikipedia.org/wiki/"
            f"{quote_plus(title.replace(' ', '_'))}"
        )
        out.append(
            _doc(title, snippet[:800], page_url, "wikipedia", source="Wikipedia")
        )
        if len(out) >= limit:
            break
    return out


def search_qq_news(keyword: str, limit: int = 10) -> List[Dict[str, Any]]:
    """腾讯新闻搜索（Playwright，可选渠道）。"""
    from src.flowgame.playwright_scripts import playwright_enabled
    from src.flowgame.playwright_scripts._browser import pages_for_limit
    from src.flowgame.playwright_scripts.qq_news import crawl

    if not playwright_enabled():
        raise RuntimeError(
            "Playwright 未启用或未安装。请确认已 pip install -r requirements.txt "
            "&& playwright install chromium（Docker 镜像已内置）"
        )
    pages = pages_for_limit(limit, per_page=10)
    raw = crawl(keyword=keyword, pages=pages)
    out: List[Dict[str, Any]] = []
    for item in raw:
        title = _clean_text(str(item.get("title") or ""))
        url = str(item.get("url") or "").strip()
        if not title or not url:
            continue
        content = _clean_text(str(item.get("summary") or ""))
        out.append(_doc(title, content[:800], url, "qq_news", source="腾讯新闻"))
        if len(out) >= limit:
            break
    return out


def search_sina_news(keyword: str, limit: int = 10) -> List[Dict[str, Any]]:
    """新浪新闻搜索（Playwright，可选渠道）。"""
    from src.flowgame.playwright_scripts import playwright_enabled
    from src.flowgame.playwright_scripts._browser import pages_for_limit
    from src.flowgame.playwright_scripts.sina_news import crawl

    if not playwright_enabled():
        raise RuntimeError(
            "Playwright 未启用或未安装。请确认已 pip install -r requirements.txt "
            "&& playwright install chromium（Docker 镜像已内置）"
        )
    pages = pages_for_limit(limit, per_page=10)
    raw = crawl(keyword=keyword, pages=pages)
    out: List[Dict[str, Any]] = []
    for item in raw:
        title = _clean_text(str(item.get("title") or ""))
        url = str(item.get("url") or "").strip()
        if not title or not url:
            continue
        content = _clean_text(str(item.get("summary") or ""))
        source = _clean_text(str(item.get("source") or "")) or "新浪新闻"
        out.append(_doc(title, content[:800], url, "sina_news", source=source))
        if len(out) >= limit:
            break
    return out


def _engine_func(engine_id: str):
    """Resolve by name at call time so tests can patch module functions."""
    mapping = {
        "google_news": search_google_news,
        "duckduckgo": search_duckduckgo,
        "wikipedia": search_wikipedia,
        "qq_news": search_qq_news,
        "sina_news": search_sina_news,
    }
    return mapping.get(engine_id)


def normalize_engines(raw: Any) -> List[str]:
    if raw is None:
        return list(DEFAULT_ENGINES)
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return list(DEFAULT_ENGINES)
        if text.startswith("["):
            import json

            try:
                parsed = json.loads(text)
                raw = parsed
            except json.JSONDecodeError:
                raw = re.split(r"[,|]", text)
        else:
            raw = re.split(r"[,|]", text)
    if not isinstance(raw, (list, tuple)):
        return list(DEFAULT_ENGINES)
    out: List[str] = []
    for item in raw:
        key = str(item).strip().lower()
        if key in LEGACY_PAID_ENGINES:
            continue
        if key in ALLOWED_ENGINES and key not in out:
            out.append(key)
    return out or list(DEFAULT_ENGINES)


def search_web(
    keyword: str,
    engines: Optional[Sequence[str]] = None,
    limit: int = 10,
) -> Dict[str, Any]:
    """
    Run selected engines (in parallel), merge by URL, return:
    { documents, errors, engines }
    """
    query = (keyword or "").strip()
    real_limit = max(1, min(int(limit or 10), 50))
    engine_ids = normalize_engines(engines)
    if not query:
        return {
            "documents": [],
            "errors": ["搜索关键字为空"],
            "engines": engine_ids,
        }

    per_engine_limit = max(real_limit, 5)
    documents: List[Dict[str, Any]] = []
    errors: List[str] = []
    seen: set[str] = set()

    def run_one(engine_id: str) -> tuple[str, List[Dict[str, Any]], Optional[str]]:
        fn = _engine_func(engine_id)
        if not fn:
            return engine_id, [], f"未知搜索引擎: {engine_id}"
        try:
            return engine_id, fn(query, per_engine_limit), None
        except Exception as exc:  # noqa: BLE001
            logger.warning("web search engine=%s failed: %s", engine_id, exc)
            return engine_id, [], f"{engine_id}: {exc}"

    if len(engine_ids) == 1:
        _, hits, err = run_one(engine_ids[0])
        if err:
            errors.append(err)
        for doc in hits:
            key = _normalize_url_key(str(doc.get("url") or ""))
            if not key or key in seen:
                continue
            seen.add(key)
            documents.append(doc)
            if len(documents) >= real_limit:
                break
    else:
        with ThreadPoolExecutor(max_workers=min(4, len(engine_ids))) as pool:
            futures = {pool.submit(run_one, eid): eid for eid in engine_ids}
            for fut in as_completed(futures):
                _, hits, err = fut.result()
                if err:
                    errors.append(err)
                for doc in hits:
                    key = _normalize_url_key(str(doc.get("url") or ""))
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    documents.append(doc)
                    if len(documents) >= real_limit:
                        break
                if len(documents) >= real_limit:
                    break

    documents = documents[:real_limit]
    return {
        "documents": documents,
        "errors": errors,
        "engines": engine_ids,
    }
