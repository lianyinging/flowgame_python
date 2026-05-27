"""对话记忆 Redis 键：flow_game:flow_context:{md5(上下文引用值)}"""
from __future__ import annotations

import hashlib
import json
from typing import Any, List, Optional

CONTEXT_REDIS_KEY_PREFIX = "flow_game:flow_context:"


def coerce_context_key_text(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, (dict, list)):
        return json.dumps(raw, ensure_ascii=False, sort_keys=True)
    return str(raw).strip()


def build_context_redis_key(raw_key: Any) -> str:
    text = coerce_context_key_text(raw_key)
    if not text:
        raise ValueError("记忆上下文键引用值为空，请配置 contextKey 引用（如 headers.Authorization）")
    digest = hashlib.md5(text.encode("utf-8")).hexdigest()
    return f"{CONTEXT_REDIS_KEY_PREFIX}{digest}"


def serialize_list_item(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def parse_list_items(items: List[Any]) -> List[Any]:
    parsed: List[Any] = []
    for item in items:
        if not isinstance(item, str):
            parsed.append(item)
            continue
        text = item.strip()
        if not text:
            parsed.append(item)
            continue
        try:
            parsed.append(json.loads(text))
        except json.JSONDecodeError:
            parsed.append(item)
    return parsed


def slice_list_tail(items: List[Any], limit: Optional[int]) -> List[Any]:
    if not limit or limit <= 0:
        return items
    if len(items) <= limit:
        return items
    return items[-limit:]
