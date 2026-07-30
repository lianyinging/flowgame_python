"""小红书自动化运营（集成自 xiaohongshu-skill / redbook）。

动态代码示例::

    from scripts import feed

    detail = feed.feed_detail(
        feed_id="笔记id",
        xsec_token="搜索结果里的token",
        load_comments=True,
        max_comments=20,
        headless=True,
    )
    result = detail

Cookie / 浏览器数据默认在 ``~/.xiaohongshu/``（与原 skill 一致）。
"""
from __future__ import annotations

import sys
from pathlib import Path

_XHS_ROOT = Path(__file__).resolve().parent


def ensure_scripts_import_path() -> str:
    """把本目录加入 ``sys.path``，使 ``from scripts import feed`` 可用。"""
    root = str(_XHS_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    return root


# 包被 import 时即注册路径，便于非动态代码场景
ensure_scripts_import_path()
