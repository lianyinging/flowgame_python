"""从 Redis 加载 Tinyflow 工作流（与前端 flow_list 存储格式一致）。"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from src.flowgame.key_prefix import get_flow_list_redis_prefix


class FlowGameWorkflowStoreError(Exception):
    pass


def build_flow_redis_key(method_key: str) -> str:
    return f"{get_flow_list_redis_prefix()}{method_key.strip()}"


def _flow_redis_keys_for_load(method_key: str) -> List[str]:
    prefix = get_flow_list_redis_prefix()
    key = (method_key or "").strip()
    if not key:
        return []
    keys: List[str] = []
    if key.startswith(prefix):
        keys.append(key)
        name = key[len(prefix) :].strip()
    else:
        name = key
    if name:
        keys.append(f"{prefix}{name}")
    return list(dict.fromkeys(k for k in keys if k))


def parse_workflow_from_redis_value(value: Any) -> Optional[Dict[str, Any]]:
    if not value or not isinstance(value, dict):
        return None
    workflow = value.get("workflow")
    if isinstance(workflow, dict):
        return workflow
    if isinstance(value.get("nodes"), list) or isinstance(value.get("edges"), list):
        return value
    return None


def load_workflow_json_by_method_key(method_key: str) -> str:
    key = (method_key or "").strip()
    if not key:
        raise FlowGameWorkflowStoreError("methodKey 不能为空")

    from src.flowgame.redis.client import redis_client

    if not redis_client.ping():
        raise FlowGameWorkflowStoreError("Redis 不可用，无法加载工作流")

    payload = None
    for redis_key in _flow_redis_keys_for_load(key):
        if redis_client.exists(redis_key) <= 0:
            continue
        payload = redis_client.get_json(redis_key)
        if payload:
            break

    if not payload:
        raise FlowGameWorkflowStoreError(f"未找到 methodKey 对应的工作流：{key}")

    workflow = parse_workflow_from_redis_value(payload)
    if not workflow:
        raise FlowGameWorkflowStoreError(f"methodKey={key} 的 Redis 数据不是有效的工作流")

    return json.dumps(workflow, ensure_ascii=False)
