"""企业微信「群机器人」Webhook 发送（仅主动推送，不能收消息）。"""
from __future__ import annotations

from typing import Any

import requests

from ._util import resolve_webhook_key

WEBHOOK_URL = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={key}"


def send_text(
    content: str,
    *,
    key: str | None = None,
    mentioned_list: list[str] | None = None,
    timeout: float = 15,
) -> dict[str, Any]:
    """发送文本。``mentioned_list`` 可传 ``['@all']`` 或成员 userid。"""
    webhook_key = resolve_webhook_key(key)
    text: dict[str, Any] = {"content": content}
    if mentioned_list:
        text["mentioned_list"] = mentioned_list
    payload = {"msgtype": "text", "text": text}
    resp = requests.post(WEBHOOK_URL.format(key=webhook_key), json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    return {"ok": data.get("errcode") == 0, "response": data}


def send_markdown(
    content: str,
    *,
    key: str | None = None,
    timeout: float = 15,
) -> dict[str, Any]:
    """发送 markdown。"""
    webhook_key = resolve_webhook_key(key)
    payload = {"msgtype": "markdown", "markdown": {"content": content}}
    resp = requests.post(WEBHOOK_URL.format(key=webhook_key), json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    return {"ok": data.get("errcode") == 0, "response": data}
