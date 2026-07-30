"""企业微信机器人渠道（群 Webhook + 智能机器人 WebSocket）。

动态代码示例::

    from wecom import aibot

    result = aibot.send_markdown("你好", chatid="群chatid或单聊userid")

或::

    from wecom import webhook

    result = webhook.send_markdown("**测试**")
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent


def ensure_wecom_import_path() -> str:
    """把本目录加入 ``sys.path``，使 ``from wecom import aibot`` 可用。

    注意：不用 ``scripts`` 包名，避免与 ``media_channel/xiaohongshu`` 冲突。
    """
    root = str(_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    return root


ensure_wecom_import_path()
