"""
多 Agent 协同：按任意主题抓取网页资讯 → 输出 Markdown 简报

主题不限（科技 / 财经 / 体育 / 政策…），由 --topic / --query 指定。

流程：
  scout     → RSS（含 Google News）+ 网页搜索，汇总候选链接
  fetcher   → 抓取正文（优先 Jina Reader，失败则降级 requests）
  curator   → LLM 去重、聚类、挑选要点
  writer    → LLM 生成结构化 Markdown 简报
  （落盘）  → experiments/loop_agent/output/*.md

运行：
  cd experiments/loop_agent
  python demo_ai_news.py --topic "新能源汽车"
  python demo_ai_news.py --topic "World Cup" --max-articles 8
  python demo_ai_news.py --skip-search
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus, urlparse

import requests
from openai import OpenAI

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(_ROOT / ".env")
except ImportError:
    pass


# ===========================================================================
# Harness：限流 / 超时 / 白名单（防失控抓取）
# ===========================================================================


@dataclass
class HarnessConfig:
    request_timeout_sec: float = 20.0
    max_search_results: int = 12
    max_fetch_articles: int = 8
    max_body_chars: int = 6000  # 单篇进 LLM 的正文上限
    user_agent: str = (
        "FlowGameNewsBot/0.1 (+https://github.com/lianyinging/flowgame_python; research-demo)"
    )
    # 抓取域名粗过滤（仍受 max_fetch 约束）
    blocked_host_substrings: tuple[str, ...] = ("facebook.com", "instagram.com", "tiktok.com")


# 通用资讯源（会按检索词过滤）。动态源见 topic_rss_feeds。
BASE_RSS_FEEDS: List[Dict[str, str]] = [
    {"name": "BBC Technology", "url": "https://feeds.bbci.co.uk/news/technology/rss.xml"},
    {"name": "BBC News", "url": "https://feeds.bbci.co.uk/news/rss.xml"},
    {"name": "TechCrunch", "url": "https://techcrunch.com/feed/"},
    {"name": "The Verge", "url": "https://www.theverge.com/rss/index.xml"},
    {"name": "MIT Technology Review", "url": "https://www.technologyreview.com/feed/"},
    {"name": "Wired", "url": "https://www.wired.com/feed/rss"},
]


# 用户常把「检索主题」和「整理要求」写在一句里，需要拆开
_INSTRUCTION_SPLIT = re.compile(
    r"(?:需要|请|要求|并|而且)?(?:按照|按|用)?(?:段落|条目|要点)?(?:整理|归纳|总结|输出|生成|写成).*$"
)
_FILLER_WORDS = {
    "今日",
    "今天",
    "最新",
    "消息",
    "资讯",
    "新闻",
    "相关",
    "内容",
    "信息",
    "报道",
    "about",
    "latest",
    "news",
    "update",
    "updates",
    "today",
}

# 领域同义词：中文短查询扩成可命中英文稿的关键词
_DOMAIN_SYNONYMS: Dict[str, List[str]] = {
    "ai": ["ai", "artificial intelligence", "llm", "openai", "anthropic", "人工智能", "大模型", "机器学习"],
    "人工智能": ["ai", "artificial intelligence", "llm", "人工智能", "大模型"],
    "大模型": ["llm", "large language model", "gpt", "大模型", "人工智能"],
    "新能源": ["ev", "electric vehicle", "新能源", "电动车", "battery"],
    "芯片": ["chip", "semiconductor", "nvidia", "芯片", "半导体"],
}


@dataclass
class UserIntent:
    """拆分后的用户意图。"""

    raw: str
    search_query: str  # 用于 RSS / 搜索引擎
    filter_keywords: List[str]  # 用于相关性过滤（含同义词）
    requirement: str  # 写稿/整理要求


def parse_user_intent(raw_topic: str, requirement: str = "") -> UserIntent:
    """
    把「今日ai相关最新消息，需要按照段落整理好重要信息」
    拆成 search_query≈ai，requirement≈按段落整理重要信息。
    """
    raw = (raw_topic or "").strip()
    req = (requirement or "").strip()

    # 从整句里拆出后半段写作要求
    if not req and raw:
        m = re.search(r"[，,;；]\s*((?:需要|请|要求).+)$", raw)
        if m:
            req = m.group(1).strip()
            raw_core = raw[: m.start()].strip()
        else:
            m2 = _INSTRUCTION_SPLIT.search(raw)
            if m2 and m2.start() > 0:
                req = raw[m2.start() :].strip()
                raw_core = raw[: m2.start()].strip(" ，,。.")
            else:
                raw_core = raw
    else:
        raw_core = raw

    if not req:
        req = "按段落整理重要信息，结构清晰，标注来源"

    cores: List[str] = []

    # 1) 先抠英文/数字词（中文粘连时也能抽出 ai / llm）
    for tok in re.findall(r"[A-Za-z][A-Za-z0-9\-]*", raw_core):
        cores.append(tok.lower())

    # 2) 抠已知中文领域词
    for phrase in ("人工智能", "大模型", "机器学习", "新能源汽车", "芯片"):
        if phrase in raw_core:
            cores.append(phrase)

    # 3) 去掉填充词后再按空白/标点切
    stripped = raw_core
    for w in sorted(_FILLER_WORDS, key=len, reverse=True):
        stripped = re.sub(re.escape(w), " ", stripped, flags=re.I)
    stripped = re.sub(r"[A-Za-z][A-Za-z0-9\-]*", " ", stripped)  # 英文已单独收集
    parts = re.split(r"[\s,，、|/·.。]+", stripped.lower())
    for p in parts:
        p = p.strip()
        if p and p not in _FILLER_WORDS and len(p) >= 2:
            cores.append(p)

    # 去重保序
    seen: set[str] = set()
    uniq: List[str] = []
    for c in cores:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    cores = uniq

    if not cores:
        if re.search(r"\bai\b|人工智能|大模型|llm", raw_core, flags=re.I):
            cores = ["ai"]
        else:
            cores = [raw_core.strip()] if raw_core.strip() else ["news"]

    search_query = " ".join(cores[:6]).strip() or "news"

    # 扩展同义词，便于英文 RSS 命中
    keywords: List[str] = []
    for c in cores:
        keywords.append(c)
        for syn in _DOMAIN_SYNONYMS.get(c, []):
            keywords.append(syn.lower())
    seen_k: set[str] = set()
    filter_keywords: List[str] = []
    for k in keywords:
        if k not in seen_k:
            seen_k.add(k)
            filter_keywords.append(k)

    return UserIntent(
        raw=raw_topic.strip(),
        search_query=search_query,
        filter_keywords=filter_keywords or [search_query],
        requirement=req,
    )


def topic_rss_feeds(search_query: str) -> List[Dict[str, str]]:
    """按「检索词」拼动态 RSS（不要把写作要求塞进 URL）。"""
    q = quote_plus(search_query.strip() or "news")
    # 额外给 AI 类补一条更干净的英文查询
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
    return feeds + BASE_RSS_FEEDS


def _matches_keywords(text: str, keywords: List[str]) -> bool:
    """命中任一关键词即相关（关键词已含同义词，从宽召回）。"""
    if not keywords:
        return True
    hay = (text or "").lower()
    return any(k.lower() in hay for k in keywords if k)


# ===========================================================================
# 网页搜索 + 抓取（工具层，供子 Agent 调用）
# ===========================================================================


@dataclass
class Candidate:
    title: str
    url: str
    snippet: str = ""
    source: str = ""
    published: str = ""


@dataclass
class Article:
    title: str
    url: str
    source: str
    published: str
    body: str
    fetch_method: str = ""


class WebToolkit:
    """搜索 / RSS / 抓取。失败要可降级，不让整条流水线挂死。"""

    def __init__(self, cfg: HarnessConfig) -> None:
        self.cfg = cfg
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": cfg.user_agent})

    def _allowed(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return not any(b in host for b in self.cfg.blocked_host_substrings)

    def fetch_rss(
        self,
        feed_url: str,
        source_name: str,
        keywords: Optional[List[str]] = None,
    ) -> List[Candidate]:
        out: List[Candidate] = []
        try:
            resp = self.session.get(feed_url, timeout=self.cfg.request_timeout_sec)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
        except Exception as exc:  # noqa: BLE001
            print(f"  ⚠ RSS 失败 [{source_name}]: {exc}")
            return out

        # RSS 2.0 item / Atom entry
        items = root.findall(".//item")
        if not items:
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            items = root.findall(".//atom:entry", ns) or root.findall(
                ".//{http://www.w3.org/2005/Atom}entry"
            )

        # 主题检索型 RSS 已按 query 召回，不再二次过滤
        loose = source_name.startswith("Google News") or source_name == "Hacker News"

        for item in items[: self.cfg.max_search_results]:
            title = _xml_text(item, ("title", "{http://www.w3.org/2005/Atom}title"))
            link = _xml_link(item)
            desc = _xml_text(
                item,
                ("description", "summary", "{http://www.w3.org/2005/Atom}summary"),
            )
            pub = _xml_text(
                item,
                ("pubDate", "published", "updated", "{http://www.w3.org/2005/Atom}published"),
            )
            if not title or not link or not self._allowed(link):
                continue
            blob = f"{title} {desc}"
            if not loose and keywords and not _matches_keywords(blob, keywords):
                continue
            out.append(
                Candidate(
                    title=_clean_text(title),
                    url=link.strip(),
                    snippet=_clean_text(desc)[:280],
                    source=source_name,
                    published=_normalize_date(pub),
                )
            )
        print(f"    → {len(out)} 条")
        return out

    def search_duckduckgo(self, query: str) -> List[Candidate]:
        """
        使用 DuckDuckGo HTML 结果页做轻量搜索（无官方 API Key）。
        页面结构可能变化，失败时返回空列表，由 RSS 兜底。
        """
        out: List[Candidate] = []
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        try:
            resp = self.session.get(url, timeout=self.cfg.request_timeout_sec)
            resp.raise_for_status()
            html_text = resp.text
        except Exception as exc:  # noqa: BLE001
            print(f"  ⚠ DuckDuckGo 搜索失败: {exc}")
            return out

        # 粗解析 result__a / result__snippet
        for m in re.finditer(
            r'class="result__a"[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>'
            r'.*?class="result__snippet"[^>]*>(?P<snippet>.*?)</(?:a|td|div)',
            html_text,
            flags=re.I | re.S,
        ):
            title = _clean_text(m.group("title"))
            href = html.unescape(m.group("href"))
            # DDG 可能包一层 //duckduckgo.com/l/?uddg=
            real = _unwrap_ddg_url(href)
            snippet = _clean_text(m.group("snippet"))
            if not title or not real or not self._allowed(real):
                continue
            out.append(
                Candidate(
                    title=title,
                    url=real,
                    snippet=snippet[:280],
                    source="DuckDuckGo",
                    published="",
                )
            )
            if len(out) >= self.cfg.max_search_results:
                break

        if not out:
            # 宽松：只抓标题链接
            for m in re.finditer(
                r'class="result__a"[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
                html_text,
                flags=re.I | re.S,
            ):
                title = _clean_text(m.group("title"))
                real = _unwrap_ddg_url(html.unescape(m.group("href")))
                if title and real and self._allowed(real):
                    out.append(
                        Candidate(title=title, url=real, source="DuckDuckGo")
                    )
                if len(out) >= self.cfg.max_search_results:
                    break
        return out

    def fetch_article(self, cand: Candidate) -> Optional[Article]:
        """优先 Jina Reader（URL→可读 Markdown），失败降级纯文本抽取。"""
        body = ""
        method = ""

        jina_url = f"https://r.jina.ai/{cand.url}"
        try:
            resp = self.session.get(
                jina_url,
                timeout=self.cfg.request_timeout_sec,
                headers={"Accept": "text/plain"},
            )
            if resp.status_code < 400 and len(resp.text.strip()) > 80:
                body = resp.text.strip()
                method = "jina"
        except Exception:
            body = ""

        if not body:
            try:
                resp = self.session.get(cand.url, timeout=self.cfg.request_timeout_sec)
                resp.raise_for_status()
                body = _html_to_text(resp.text)
                method = "requests+strip"
            except Exception as exc:  # noqa: BLE001
                print(f"  ⚠ 抓取失败 {cand.url}: {exc}")
                return None

        body = body[: self.cfg.max_body_chars]
        if len(body) < 60:
            return None
        return Article(
            title=cand.title,
            url=cand.url,
            source=cand.source,
            published=cand.published,
            body=body,
            fetch_method=method,
        )


def _xml_text(el: ET.Element, names: tuple[str, ...]) -> str:
    for name in names:
        child = el.find(name)
        if child is not None and (child.text or "").strip():
            return (child.text or "").strip()
        # 部分 feed 标题在子节点
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


def _normalize_date(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        m = re.search(r"\d{4}-\d{2}-\d{2}", raw)
        return m.group(0) if m else raw[:32]


def _clean_text(text: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _html_to_text(raw_html: str) -> str:
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", raw_html)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?is)<noscript[^>]*>.*?</noscript>", " ", text)
    text = re.sub(r"(?is)<!--.*?-->", " ", text)
    text = _clean_text(text)
    return text


def _unwrap_ddg_url(href: str) -> str:
    if "uddg=" in href:
        m = re.search(r"uddg=([^&]+)", href)
        if m:
            from urllib.parse import unquote

            return unquote(m.group(1))
    if href.startswith("//"):
        return "https:" + href
    return href


def _dedupe_candidates(items: List[Candidate]) -> List[Candidate]:
    seen = set()
    out: List[Candidate] = []
    for c in items:
        key = c.url.split("?")[0].rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


# ===========================================================================
# LLM 子 Agent
# ===========================================================================


@dataclass
class LlmClient:
    client: OpenAI
    model: str

    def chat(self, system: str, user: str, temperature: float = 0.3) -> str:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
        )
        return (resp.choices[0].message.content or "").strip()


@dataclass
class PipelineState:
    query: str
    search_query: str = ""
    requirement: str = ""
    candidates: List[Candidate] = field(default_factory=list)
    articles: List[Article] = field(default_factory=list)
    curated_json: str = ""
    report_md: str = ""
    trace: List[Dict[str, Any]] = field(default_factory=list)


class ScoutAgent:
    """侦察 Agent：用「检索词」搜，不用整句写作要求。"""

    def __init__(self, web: WebToolkit) -> None:
        self.web = web

    def run(self, intent: UserIntent, feeds: List[Dict[str, str]]) -> List[Candidate]:
        print(f"\n▶ [scout] 原始输入：{intent.raw!r}")
        print(f"  检索词：{intent.search_query!r}")
        print(f"  过滤词：{intent.filter_keywords[:8]}")
        print(f"  整理要求：{intent.requirement!r}")

        found: List[Candidate] = []
        for feed in feeds:
            print(f"  · RSS {feed['name']}")
            found.extend(
                self.web.fetch_rss(
                    feed["url"], feed["name"], keywords=intent.filter_keywords
                )
            )
            time.sleep(0.3)

        queries = [intent.search_query, f"{intent.search_query} news"]
        if intent.search_query.lower() in {"ai", "人工智能"}:
            queries.extend(["artificial intelligence", "LLM AI news"])

        for q in queries:
            print(f"  · 网页搜索: {q}")
            hits = self.web.search_duckduckgo(q)
            print(f"    → {len(hits)} 条")
            found.extend(hits)
            time.sleep(0.3)

        found = _dedupe_candidates(found)
        before = len(found)
        # 主题检索源 / 已按关键词召回的结果从宽保留
        kept: List[Candidate] = []
        for c in found:
            if c.source.startswith("Google News") or c.source == "Hacker News":
                kept.append(c)
            elif _matches_keywords(f"{c.title} {c.snippet}", intent.filter_keywords):
                kept.append(c)
        found = kept
        print(f"  ✔ 候选链接 {len(found)} 条（过滤前 {before}）")
        return found


class FetcherAgent:
    """抓取 Agent：把链接变成正文。"""

    def __init__(self, web: WebToolkit, max_articles: int) -> None:
        self.web = web
        self.max_articles = max_articles

    def run(self, candidates: List[Candidate]) -> List[Article]:
        print("\n▶ [fetcher] 抓取正文")
        articles: List[Article] = []
        for cand in candidates:
            if len(articles) >= self.max_articles:
                break
            print(f"  · {cand.title[:60]}…")
            art = self.web.fetch_article(cand)
            if art:
                articles.append(art)
                print(f"    ok via {art.fetch_method} ({len(art.body)} chars)")
            time.sleep(0.4)
        print(f"  ✔ 成功抓取 {len(articles)} 篇")
        return articles


class CuratorAgent:
    """策展 Agent：去重聚类、挑重点（Prompt Engineering）。"""

    def __init__(self, llm: LlmClient) -> None:
        self.llm = llm

    def run(self, intent: UserIntent, articles: List[Article]) -> str:
        print("\n▶ [curator] 策展与聚类")
        briefs = []
        for i, a in enumerate(articles, 1):
            briefs.append(
                {
                    "id": i,
                    "title": a.title,
                    "url": a.url,
                    "source": a.source,
                    "published": a.published,
                    "excerpt": a.body[:900],
                }
            )
        user = (
            f"用户关注主题：{intent.search_query}\n"
            f"整理要求：{intent.requirement}\n"
            f"今天 UTC：{datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n\n"
            f"素材 JSON：\n{json.dumps(briefs, ensure_ascii=False, indent=2)}\n\n"
            "请输出 JSON（不要代码围栏），结构：\n"
            "{\n"
            '  "themes": [{"name": "主题名", "article_ids": [1,2], "why": "理由"}],\n'
            '  "top_stories": [{"id": 1, "headline": "...", "takeaway": "一句话看点"}],\n'
            '  "noise_ids": [被判定重复或低质或不相关的 id],\n'
            '  "editor_notes": "给写稿人的注意事项"\n'
            "}"
        )
        text = self.llm.chat(
            system=(
                "你是资深资讯主编。"
                "只基于给定素材判断，禁止编造不存在的链接或事实。"
                "紧扣用户主题，优先最近、高信号、可验证的内容。"
            ),
            user=user,
            temperature=0.2,
        )
        print(text[:600] + ("…" if len(text) > 600 else ""))
        return text


class WriterAgent:
    """写稿 Agent：输出最终 Markdown 简报。"""

    def __init__(self, llm: LlmClient) -> None:
        self.llm = llm

    def run(self, intent: UserIntent, articles: List[Article], curated_json: str) -> str:
        print("\n▶ [writer] 生成 Markdown 简报")
        corpus = []
        for i, a in enumerate(articles, 1):
            corpus.append(
                f"### [{i}] {a.title}\n"
                f"- source: {a.source}\n"
                f"- date: {a.published or 'unknown'}\n"
                f"- url: {a.url}\n\n"
                f"{a.body[:3500]}\n"
            )
        user = (
            f"关注主题：{intent.search_query}\n"
            f"整理要求：{intent.requirement}\n"
            f"生成时间（UTC）：{datetime.now(timezone.utc).isoformat()}\n\n"
            f"策展 JSON：\n{curated_json}\n\n"
            f"文章素材：\n{''.join(corpus)}\n\n"
            "请输出完整 Markdown 简报，必须包含：\n"
            f"1. 标题：「{intent.search_query}」资讯简报 + 日期\n"
            "2. 按段落整理的重要信息（满足用户整理要求）\n"
            "3. 分主题深读（含来源与链接）\n"
            "4. 趋势观察（3 点）\n"
            "5. 资料来源列表（标题 + URL）\n"
            "要求：中文为主；事实必须能对应素材；不要伪造链接；紧扣主题。"
        )
        md = self.llm.chat(
            system=(
                "你是资深撰稿人。只输出 Markdown 正文，不要前言后语。"
                "引用必须带来源链接。严格按「整理要求」组织段落。"
            ),
            user=user,
            temperature=0.4,
        )
        print(md[:800] + ("…" if len(md) > 800 else ""))
        return md


# ===========================================================================
# 编排
# ===========================================================================


def run_pipeline(
    llm: LlmClient,
    intent: UserIntent,
    max_articles: int,
    skip_search: bool,
) -> PipelineState:
    cfg = HarnessConfig(max_fetch_articles=max_articles)
    web = WebToolkit(cfg)
    state = PipelineState(
        query=intent.raw,
        search_query=intent.search_query,
        requirement=intent.requirement,
    )

    scout = ScoutAgent(web)
    feeds = topic_rss_feeds(intent.search_query)
    cands = scout.run(intent, feeds)
    if skip_search:
        cands = [c for c in cands if c.source != "DuckDuckGo"]
    state.candidates = cands
    state.trace.append(
        {
            "agent": "scout",
            "candidates": len(cands),
            "search_query": intent.search_query,
        }
    )

    if not cands:
        state.report_md = (
            f"# 「{intent.search_query}」资讯简报\n\n"
            f"> 生成失败：未找到候选链接。\n"
            f"> 原始输入：{intent.raw}\n"
            f"> 实际检索词：{intent.search_query}\n"
            f"> 建议：`--topic \"AI\" --requirement \"按段落整理重要信息\"`\n"
        )
        return state

    cands_sorted = sorted(
        cands, key=lambda c: (0 if c.published else 1, c.title), reverse=False
    )
    fetcher = FetcherAgent(web, max_articles=max_articles)
    articles = fetcher.run(cands_sorted)
    state.articles = articles
    state.trace.append({"agent": "fetcher", "articles": len(articles)})

    if not articles:
        lines = [
            f"# 「{intent.search_query}」资讯简报（链接版）\n",
            f"- 主题：{intent.search_query}\n",
            f"- 要求：{intent.requirement}\n\n",
        ]
        for c in cands_sorted[:max_articles]:
            lines.append(f"- [{c.title}]({c.url}) — {c.source} {c.published}\n")
        state.report_md = "".join(lines)
        return state

    curator = CuratorAgent(llm)
    curated = curator.run(intent, articles)
    state.curated_json = curated
    state.trace.append({"agent": "curator", "ok": True})

    writer = WriterAgent(llm)
    md = writer.run(intent, articles, curated)
    md += "\n\n---\n\n## 抓取元数据\n\n"
    md += f"- raw: `{intent.raw}`\n"
    md += f"- search_query: `{intent.search_query}`\n"
    md += f"- requirement: `{intent.requirement}`\n"
    md += f"- fetched_at_utc: `{datetime.now(timezone.utc).isoformat()}`\n"
    md += f"- articles: `{len(articles)}`\n"
    for a in articles:
        md += f"- [{a.title}]({a.url}) via `{a.fetch_method}` ({a.source})\n"
    state.report_md = md
    state.trace.append({"agent": "writer", "chars": len(md)})
    return state


def save_outputs(state: PipelineState, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug_src = state.search_query or state.query
    slug = re.sub(r"\s+", "_", slug_src.strip())[:40] or "topic"
    slug = re.sub(r"[^\w\u4e00-\u9fff\-]+", "", slug) or "topic"
    md_path = out_dir / f"{stamp}_{slug}_news.md"
    json_path = out_dir / f"{stamp}_{slug}_news.json"
    md_path.write_text(state.report_md + "\n", encoding="utf-8")
    payload = {
        "topic": state.query,
        "search_query": state.search_query,
        "requirement": state.requirement,
        "trace": state.trace,
        "candidates": [c.__dict__ for c in state.candidates],
        "articles": [
            {
                "title": a.title,
                "url": a.url,
                "source": a.source,
                "published": a.published,
                "fetch_method": a.fetch_method,
                "body_chars": len(a.body),
            }
            for a in state.articles
        ],
        "curated_json": state.curated_json,
        "report_md": state.report_md,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return md_path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="多 Agent 按主题抓取网页资讯 → Markdown")
    p.add_argument(
        "--topic",
        "--query",
        dest="topic",
        default="",
        help="检索主题，建议简短，如：AI / 新能源汽车",
    )
    p.add_argument(
        "--requirement",
        default="",
        help="整理/写作要求，如：按段落整理重要信息",
    )
    p.add_argument("--max-articles", type=int, default=8, help="最多抓取正文篇数")
    p.add_argument(
        "--skip-search",
        action="store_true",
        help="只走 RSS，跳过 DuckDuckGo（更稳、更少被封）",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip().rstrip("/")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip()
    if not api_key or api_key == "your-deepseek-api-key":
        print("请先在仓库根目录 .env 配置 DEEPSEEK_API_KEY。")
        sys.exit(1)

    topic = (args.topic or "").strip()
    if not topic:
        topic = input("请输入要抓取的主题（建议简短，如 AI）：").strip()
    if not topic:
        print("主题不能为空。")
        sys.exit(1)

    intent = parse_user_intent(topic, args.requirement)
    print(f"base_url={base_url} model={model}")
    print(
        f"raw={intent.raw!r}\n"
        f"search_query={intent.search_query!r}\n"
        f"requirement={intent.requirement!r}\n"
        f"max_articles={args.max_articles}"
    )

    llm = LlmClient(client=OpenAI(api_key=api_key, base_url=base_url), model=model)
    state = run_pipeline(
        llm=llm,
        intent=intent,
        max_articles=max(3, args.max_articles),
        skip_search=args.skip_search,
    )
    path = save_outputs(state, Path(__file__).resolve().parent / "output")
    print("\n" + "=" * 60)
    print("简报已生成")
    print("=" * 60)
    print(state.report_md[:1200] + ("…" if len(state.report_md) > 1200 else ""))
    print("-" * 60)
    print(f"saved markdown = {path}")
    print(f"saved json     = {path.with_suffix('.json')}")


if __name__ == "__main__":
    main()
