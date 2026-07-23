"""Playwright 搜索脚本包：WebSearchNode 可选渠道（腾讯/新浪新闻等）。"""

from __future__ import annotations

__all__ = [
    "is_playwright_available",
    "playwright_enabled",
]

def is_playwright_available() -> bool:
    try:
        import playwright  # noqa: F401

        return True
    except ImportError:
        return False


def playwright_enabled() -> bool:
    """环境开关；默认在已安装 playwright 时启用。"""
    import os

    raw = (os.getenv("FLOWGAME_PLAYWRIGHT_ENABLED") or "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    return is_playwright_available()
