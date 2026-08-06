"""入站文本预处理。"""
from __future__ import annotations

import re


def strip_at_mention_prefix(text: str, *, bot_name: str = "") -> str:
    """去掉群聊入站开头的 @机器人名称，只保留用户正文。

    企微常见格式：``@机器人名称 内容``；@ 后可能带零宽字符。
    """
    s = (text or "").replace("\u200b", "").replace("\ufeff", "").strip()
    if not s:
        return s
    name = (bot_name or "").strip()
    if name:
        # 优先按配置的机器人名称精确剥除（允许名称后无空格）
        named = re.sub(rf"^@{re.escape(name)}\s*", "", s, count=1, flags=re.I).strip()
        if named != s:
            return named
    # 通用：去掉开头连续的 @token（以空白分隔）
    return re.sub(r"^(?:@[^\s@]+\s*)+", "", s).strip()
