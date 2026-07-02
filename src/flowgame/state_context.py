"""状态机 Redis 键与 JSON 状态文档。"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.flowgame.chain.template import format_template
from src.flowgame.key_prefix import get_redis_key_prefix

_PLACEHOLDER = re.compile(r"\{\{\s*(.+?)\s*}}")


def get_flow_state_redis_prefix() -> str:
    return f"{get_redis_key_prefix()}flow_state:"


def _sanitize_namespace(value: str) -> str:
    """命名空间为固定段，禁止冒号以免与 Key 结构分隔符混淆。"""
    text = (value or "").strip()
    if not text:
        return ""
    return text.replace(":", "_").replace(" ", "_")


def _sanitize_entity_key(value: str) -> str:
    """Key 模板渲染结果：保留用户写的冒号，仅压缩空白。"""
    text = (value or "").strip()
    if not text:
        return ""
    return text.replace(" ", "_")


def build_state_redis_key(namespace: str, entity_key: str) -> str:
    ns = _sanitize_namespace(namespace or "default") or "default"
    entity = _sanitize_entity_key(entity_key)
    if not entity:
        raise ValueError("状态 Key 渲染结果为空，请检查 Key 模板与输入参数")
    return f"{get_flow_state_redis_prefix()}{ns}:{entity}"


def render_state_key_template(
    template: str,
    chain_memory: Dict[str, Any],
    param_values: Dict[str, Any],
    method_key: Optional[str] = None,
) -> str:
    merged = dict(chain_memory or {})
    merged.update(param_values or {})
    if method_key and str(method_key).strip():
        merged.setdefault("methodKey", str(method_key).strip())
    rendered = format_template(template or "{{entityKey}}", merged).strip()
    return rendered


def deep_merge_payload(base: Any, patch: Any) -> Dict[str, Any]:
    if patch is None:
        if isinstance(base, dict):
            return dict(base)
        return {}
    if not isinstance(patch, dict):
        return {}
    base_obj = dict(base) if isinstance(base, dict) else {}
    result = dict(base_obj)
    for key, val in patch.items():
        prev = result.get(key)
        if (
            isinstance(prev, dict)
            and not isinstance(prev, list)
            and isinstance(val, dict)
            and not isinstance(val, list)
        ):
            result[key] = deep_merge_payload(prev, val)
        else:
            result[key] = val
    return result


def parse_payload_value(raw: Any) -> Dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def parse_state_document(raw: Any) -> Optional[Dict[str, Any]]:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_state_document(
    *,
    status: str,
    progress: Any = None,
    message: Any = None,
    payload: Any = None,
    updated_by: str = "",
) -> Dict[str, Any]:
    doc: Dict[str, Any] = {
        "status": str(status or "").strip(),
        "updatedAt": utc_now_iso(),
        "updatedBy": (updated_by or "").strip(),
        "payload": parse_payload_value(payload),
    }
    if progress is not None and str(progress).strip() != "":
        try:
            doc["progress"] = float(progress)
        except (TypeError, ValueError):
            pass
    if message is not None and str(message).strip():
        doc["message"] = str(message).strip()
    return doc


def flatten_state_outputs(state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not state:
        return {
            "state": {},
            "status": "",
            "progress": None,
            "message": "",
            "payload": {},
        }
    payload = state.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    progress = state.get("progress")
    return {
        "state": state,
        "status": str(state.get("status") or ""),
        "progress": progress if progress is not None else None,
        "message": str(state.get("message") or ""),
        "payload": payload,
    }


def resolve_method_key_from_chain(chain: Any) -> str:
    mk = chain.memory.get("methodKey") if getattr(chain, "memory", None) else None
    if mk is not None and str(mk).strip():
        return str(mk).strip()
    for node in getattr(chain, "nodes", []) or []:
        node_mk = getattr(node, "method_key", None)
        if node_mk and str(node_mk).strip():
            return str(node_mk).strip()
    return "default"


def empty_state_result() -> Dict[str, Any]:
    return {
        "success": False,
        "exists": False,
        "deleted": False,
        "redisKey": "",
        "state": {},
        "previousState": {},
        "lastState": {},
        "status": "",
        "progress": None,
        "message": "",
        "payload": {},
        "ttlSeconds": -2,
        "changedFields": [],
        "errorMessage": "",
    }
