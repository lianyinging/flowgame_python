"""共享 Playwright 浏览器启动与并发锁。"""

from __future__ import annotations

import logging
import os
import threading
from contextlib import contextmanager
from typing import Iterator

logger = logging.getLogger(__name__)

# sync Playwright 不宜多线程同时起浏览器，搜索多引擎并行时串行化
_BROWSER_LOCK = threading.Lock()

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def env_headless() -> bool:
    raw = (os.getenv("FLOWGAME_PLAYWRIGHT_HEADLESS") or "true").strip().lower()
    return raw not in ("0", "false", "no", "off")


def env_delay() -> float:
    try:
        return max(0.0, float(os.getenv("FLOWGAME_PLAYWRIGHT_DELAY") or "1.0"))
    except ValueError:
        return 1.0


def env_max_pages() -> int:
    try:
        return max(1, min(10, int(os.getenv("FLOWGAME_PLAYWRIGHT_MAX_PAGES") or "3")))
    except ValueError:
        return 3


def pages_for_limit(limit: int, *, per_page: int = 10) -> int:
    """按目标条数估算翻页数，并受 FLOWGAME_PLAYWRIGHT_MAX_PAGES 上限约束。"""
    need = max(1, int(limit or 10))
    pages = max(1, (need + per_page - 1) // per_page)
    return min(pages, env_max_pages())


@contextmanager
def chromium_page(*, headless: bool | None = None, viewport: dict | None = None):
    """启动 Chromium 并 yield page；退出时关闭浏览器。"""
    from playwright.sync_api import sync_playwright

    hl = env_headless() if headless is None else headless
    vp = viewport or {"width": 1440, "height": 900}

    with _BROWSER_LOCK:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=hl)
            try:
                context = browser.new_context(
                    user_agent=USER_AGENT,
                    locale="zh-CN",
                    viewport=vp,
                )
                page = context.new_page()
                yield page
            finally:
                browser.close()
