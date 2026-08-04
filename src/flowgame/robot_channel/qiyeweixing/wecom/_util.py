"""公共工具：凭证、会话 ID、异步桥接。"""
from __future__ import annotations

import asyncio
import concurrent.futures
import os
from pathlib import Path
from typing import Any, Coroutine, TypeVar

T = TypeVar("T")

_CHANNEL_ROOT = Path(__file__).resolve().parents[1]
STATE_FILE = _CHANNEL_ROOT / ".last_chatid"
DOWNLOAD_DIR = _CHANNEL_ROOT / "downloads"

ENV_BOT_ID = "FLOWGAME_WECOM_BOT_ID"
ENV_BOT_SECRET = "FLOWGAME_WECOM_BOT_SECRET"
ENV_CHATID = "FLOWGAME_WECOM_CHATID"
ENV_WEBHOOK_KEY = "FLOWGAME_WECOM_WEBHOOK_KEY"
ENV_ROBOT_ID = "FLOWGAME_ROBOT_ID"


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    """在同步动态代码中跑协程；若已在事件循环中则丢到线程里 ``asyncio.run``。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def resolve_bot_creds(bot_id: str | None = None, secret: str | None = None) -> tuple[str, str]:
    bid = (bot_id or os.getenv(ENV_BOT_ID) or "").strip()
    sec = (secret or os.getenv(ENV_BOT_SECRET) or "").strip()
    if not bid or not sec:
        raise ValueError(
            f"缺少智能机器人凭证：请设置环境变量 {ENV_BOT_ID} / {ENV_BOT_SECRET}，"
            "或在调用时传入 bot_id / secret"
        )
    return bid, sec


def resolve_chatid(chatid: str | None = None) -> str:
    cid = (chatid or os.getenv(ENV_CHATID) or load_last_chatid() or "").strip()
    if not cid:
        raise ValueError(
            f"缺少会话 ID：请传入 chatid，或设置 {ENV_CHATID}，"
            "或先收过消息以写入 .last_chatid"
        )
    return cid


def resolve_webhook_key(key: str | None = None) -> str:
    k = (key or os.getenv(ENV_WEBHOOK_KEY) or "").strip()
    if not k:
        raise ValueError(
            f"缺少 Webhook key：请设置 {ENV_WEBHOOK_KEY}，或调用时传入 key="
        )
    return k


def load_last_chatid() -> str:
    if STATE_FILE.is_file():
        return STATE_FILE.read_text(encoding="utf-8").strip()
    return ""


def save_last_chatid(chatid: str) -> None:
    if not chatid:
        return
    STATE_FILE.write_text(chatid, encoding="utf-8")
