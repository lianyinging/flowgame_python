"""Fetch a URL and extract readable text.

对齐 experiments/loop_agent/demo_ai_news.py 的 FetcherAgent / WebToolkit.fetch_article：
  1) 优先 Jina Reader（https://r.jina.ai/{url} → 可读 Markdown）
  2) 失败则 requests 拉取 HTML，再 strip 标签成纯文本
"""
from __future__ import annotations

import html
import logging
import os
import re
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

USER_AGENT = (
    "FlowGameNewsBot/0.1 (+https://flowgame.mgdeep.com; fetchUrlNode)"
)
DEFAULT_TIMEOUT = 20
# 与 demo HarnessConfig.max_body_chars 对齐
DEFAULT_MAX_CHARS = 6000
MIN_BODY_CHARS = 60
JINA_PREFIX = "https://r.jina.ai/"

_CHARSET_RE = re.compile(
    r"charset\s*=\s*['\"]?\s*([a-zA-Z0-9_\-]+)",
    re.I,
)
_META_CHARSET_RE = re.compile(
    r'<meta[^>]+charset=["\']?\s*([a-zA-Z0-9_\-]+)',
    re.I,
)
_META_CONTENT_TYPE_RE = re.compile(
    r'<meta[^>]+http-equiv=["\']?content-type["\']?[^>]+content=["\']([^"\']+)["\']',
    re.I,
)
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _normalize_charset(name: str) -> str:
    raw = (name or "").strip().lower().replace('"', "").replace("'", "")
    if not raw:
        return ""
    aliases = {
        "gb2312": "gb18030",
        "gbk": "gb18030",
        "gb_2312": "gb18030",
        "gb_2312-80": "gb18030",
        "chinese": "gb18030",
        "utf8": "utf-8",
        "utf_8": "utf-8",
        "iso-8859-1": "latin-1",
        "iso8859-1": "latin-1",
        "windows-1252": "cp1252",
    }
    return aliases.get(raw, raw)


def _charset_from_content_type(ctype: str) -> str:
    m = _CHARSET_RE.search(ctype or "")
    return _normalize_charset(m.group(1)) if m else ""


def _charset_from_html_head(raw: bytes) -> str:
    head = raw[:4096].decode("ascii", errors="ignore")
    m = _META_CHARSET_RE.search(head)
    if m:
        return _normalize_charset(m.group(1))
    m = _META_CONTENT_TYPE_RE.search(head)
    if m:
        return _charset_from_content_type(m.group(1))
    return ""


def _decode_bytes(content: bytes, preferred: str = "") -> str:
    """按声明/探测顺序解码，避免中文站被当成 latin-1。"""
    if not content:
        return ""
    candidates = []
    for enc in (
        preferred,
        _charset_from_html_head(content),
        "utf-8",
        "gb18030",
        "big5",
    ):
        enc_n = _normalize_charset(enc)
        if enc_n and enc_n not in candidates:
            candidates.append(enc_n)
    for enc in candidates:
        try:
            text = content.decode(enc)
            # latin-1 几乎总能解，但常把 UTF-8 中文解成 mojibake；优先有 CJK 的结果
            if enc in ("latin-1", "cp1252", "iso-8859-1") and not _CJK_RE.search(text):
                continue
            return text
        except (LookupError, UnicodeDecodeError):
            continue
    return content.decode("utf-8", errors="replace")


def _fix_utf8_mojibake(text: str) -> str:
    """修复「UTF-8 被按 latin-1 解码」的乱码，如 å¹´ä¸­ç»æµŽ… → 年中经济…"""
    if not text or _CJK_RE.search(text):
        return text
    # 典型 mojibake 多含 Ã/Â/å/æ 等 latin 扩展字符
    if not re.search(r"[ÃÂåæçéèêëìíîïðñòóôõöøùúûüýþÿÄÅÆ]", text):
        return text
    try:
        fixed = text.encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return text
    if _CJK_RE.search(fixed) or fixed.count("�") < text.count("�"):
        return fixed
    return text


def _response_text(resp: requests.Response) -> str:
    ctype = str(resp.headers.get("Content-Type") or "")
    preferred = _charset_from_content_type(ctype)
    # 忽略 requests 误判的 ISO-8859-1（中文页无 charset 时很常见）
    if not preferred and resp.encoding and resp.encoding.lower() not in (
        "iso-8859-1",
        "latin-1",
        "ascii",
    ):
        preferred = _normalize_charset(resp.encoding)
    text = _decode_bytes(resp.content or b"", preferred=preferred)
    return _fix_utf8_mojibake(text)


def _clean_text(raw: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _html_to_text(raw_html: str) -> str:
    """与 demo_ai_news._html_to_text 一致。"""
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", raw_html)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?is)<noscript[^>]*>.*?</noscript>", " ", text)
    text = re.sub(r"(?is)<!--.*?-->", " ", text)
    return _clean_text(text)


def _extract_title_from_html(raw_html: str) -> str:
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw_html)
    if m:
        return _clean_text(m.group(1))
    m = re.search(
        r'(?is)<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
        raw_html,
    )
    if m:
        return _clean_text(m.group(1))
    return ""


def _extract_title_from_jina(markdown: str) -> str:
    """Jina 常以 `Title: ...` 开头。"""
    m = re.search(r"(?im)^Title:\s*(.+)$", markdown)
    if m:
        return m.group(1).strip()
    m = re.search(r"(?m)^#\s+(.+)$", markdown)
    if m:
        return m.group(1).strip()
    return ""


def _jina_enabled() -> bool:
    raw = (os.getenv("FLOWGAME_JINA_ENABLED") or "true").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _fetch_via_jina(url: str, timeout: float, session: requests.Session) -> tuple[str, int]:
    """返回 (body, status_code)；失败 body 为空。"""
    jina_url = f"{JINA_PREFIX}{url}"
    resp = session.get(
        jina_url,
        timeout=timeout,
        headers={"Accept": "text/plain; charset=utf-8", "User-Agent": USER_AGENT},
    )
    status = int(resp.status_code or 0)
    text = _fix_utf8_mojibake(_response_text(resp)).strip()
    if status < 400 and len(text) > 80:
        return text, status
    return "", status


def _fetch_via_requests(
    url: str, timeout: float, session: requests.Session
) -> tuple[str, str, int, str]:
    """返回 (body_text, title, status_code, content_type)。"""
    resp = session.get(
        url,
        timeout=timeout,
        headers={"User-Agent": USER_AGENT, "Accept-Charset": "utf-8,gb18030;q=0.8"},
        allow_redirects=True,
    )
    status = int(resp.status_code or 0)
    ctype = str(resp.headers.get("Content-Type") or "")
    resp.raise_for_status()
    raw = _response_text(resp)
    title = _extract_title_from_html(raw) if raw else ""
    ctype_l = ctype.lower()
    if "html" in ctype_l or "<html" in raw[:500].lower() or "<!doctype" in raw[:200].lower():
        body = _html_to_text(raw)
    else:
        body = raw.strip()
    body = _fix_utf8_mojibake(body)
    title = _fix_utf8_mojibake(title)
    return body, title, status, ctype


def fetch_url_document(
    url: str,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    timeout: int = DEFAULT_TIMEOUT,
    hint_title: Optional[str] = None,
) -> Dict[str, Any]:
    """
    抓取单页正文。返回字段与 fetchUrlNode outputDefs 对齐，并额外提供 fetchMethod。
    """
    target = (url or "").strip()
    result: Dict[str, Any] = {
        "title": (hint_title or "").strip(),
        "content": "",
        "url": target,
        "statusCode": 0,
        "contentType": "",
        "fetchMethod": "",
        "errorMessage": "",
    }
    if not target:
        result["errorMessage"] = "URL 为空"
        return result
    parsed = urlparse(target)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        result["errorMessage"] = "仅支持 http/https URL"
        return result

    limit = max(500, int(max_chars or DEFAULT_MAX_CHARS))
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    body = ""
    method = ""
    last_error = ""

    # 1) Jina Reader（与 FetcherAgent 一致）
    if _jina_enabled():
        try:
            body, status = _fetch_via_jina(target, float(timeout), session)
            result["statusCode"] = status
            if body:
                method = "jina"
                result["contentType"] = "text/plain"
                if not result["title"]:
                    result["title"] = _extract_title_from_jina(body)
        except Exception as exc:  # noqa: BLE001
            last_error = f"jina: {exc}"
            logger.info("jina fetch failed url=%s err=%s", target, exc)
            body = ""

    # 2) 降级：直接请求 + HTML strip
    if not body:
        try:
            body, title, status, ctype = _fetch_via_requests(
                target, float(timeout), session
            )
            result["statusCode"] = status
            result["contentType"] = ctype
            method = "requests+strip"
            if not result["title"] and title:
                result["title"] = title
        except Exception as exc:  # noqa: BLE001
            logger.warning("fetch_url failed url=%s err=%s", target, exc)
            result["errorMessage"] = str(exc) or last_error or "抓取失败"
            return result

    body = (body or "")[:limit]
    if len(body) < MIN_BODY_CHARS:
        result["content"] = body
        result["fetchMethod"] = method
        result["errorMessage"] = (
            result["errorMessage"]
            or f"正文过短（<{MIN_BODY_CHARS} 字符），可能被拦截或页面无有效内容"
        )
        return result

    if not result["title"]:
        result["title"] = parsed.path.rsplit("/", 1)[-1] or target

    result["content"] = body
    result["fetchMethod"] = method
    result["errorMessage"] = ""
    return result
