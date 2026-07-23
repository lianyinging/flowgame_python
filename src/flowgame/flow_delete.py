"""删除已保存流程（Redis 流程键 + 列表索引），需通过删除密码校验。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.flowgame.flow_delete_auth import assert_flow_delete_password
from src.flowgame.key_prefix import get_flow_list_redis_prefix
from src.flowgame.redis import service as redis_service
from src.flowgame.redis.client import redis_client


def _flow_list_index_key() -> str:
    return f"{get_flow_list_redis_prefix()}__index__"


def _remove_from_flow_list_index(redis_key: str) -> int:
    index_key = _flow_list_index_key()
    if redis_client.exists(index_key) <= 0:
        return 0
    raw = redis_client.get_json(index_key)
    if not isinstance(raw, dict):
        return 0
    items = raw.get("items")
    if not isinstance(items, list):
        return 0
    kept: List[Any] = [
        item
        for item in items
        if not (isinstance(item, dict) and str(item.get("redisKey") or "") == redis_key)
    ]
    removed = len(items) - len(kept)
    if removed <= 0:
        return 0
    redis_client.set_json(index_key, {"items": kept})
    return removed


def delete_saved_flow(
    *,
    redis_key: str,
    delete_password: Optional[str] = None,
) -> Dict[str, Any]:
    assert_flow_delete_password(delete_password)
    redis_service.ensure_redis()
    key = redis_service.normalize_key(redis_key)
    deleted = redis_service.delete_entry(key)
    index_removed = _remove_from_flow_list_index(key)
    return {
        "redisKey": key,
        "deleted": int(deleted.get("deleted") or 0),
        "indexRemoved": index_removed,
    }
