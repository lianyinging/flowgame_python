"""联网搜索工具：多渠道聚合入口（渠道实现见 ``channel/``）。"""
from __future__ import annotations

import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent


def ensure_web_search_import_path() -> str:
    """把 ``tools/`` 加入 ``sys.path``，使 ``from web_search…`` / 渠道包可 import。"""
    root = str(_TOOLS_DIR)
    if root not in sys.path:
        sys.path.insert(0, root)
    return root


ensure_web_search_import_path()
