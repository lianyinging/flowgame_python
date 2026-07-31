"""入出参映射与执行结果解析。"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from src.flowgame.robot_channel.models import FieldMapping


def apply_input_mapping(
    inbound: Mapping[str, Any],
    mappings: List[FieldMapping],
) -> Dict[str, Any]:
    """把入站消息字段映射为流程 variables。"""
    variables: Dict[str, Any] = {}
    for m in mappings:
        if not m.source or not m.target:
            continue
        if m.source in inbound:
            variables[m.target] = inbound[m.source]
    return variables


def extract_business_payload(result: Any) -> Dict[str, Any]:
    """从 /execute 返回结构中取出业务输出字典。"""
    if not isinstance(result, dict):
        return {}
    if (
        "apiOutput" in result
        or "endNodeOutput" in result
        or "nodeExecutions" in result
    ):
        payload = (
            result.get("apiOutput")
            or result.get("endNodeOutput")
            or result.get("lastNodeOutput")
            or {}
        )
        return dict(payload) if isinstance(payload, dict) else {}
    return dict(result)


def _resolve_source_value(payload: Mapping[str, Any], source: str) -> Any:
    if source in payload:
        return payload[source]
    # 兼容 assistantMessage 为 {content: "..."} 的对话结束形态
    if "." in source:
        cur: Any = payload
        for part in source.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return None
            cur = cur[part]
        return cur
    return None


def coerce_reply_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, dict):
        for key in ("content", "text", "message", "markdown"):
            inner = value.get(key)
            if isinstance(inner, str) and inner.strip():
                return inner.strip()
        return None
    return str(value)


def coerce_reply_files(value: Any) -> List[str]:
    """把 filePath / 路径列表规范成本地路径字符串列表。"""
    if value is None:
        return []
    if isinstance(value, str):
        path = value.strip()
        return [path] if path else []
    if isinstance(value, (list, tuple)):
        paths: List[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                paths.append(item.strip())
            elif isinstance(item, dict):
                for key in ("path", "filePath", "filepath", "file"):
                    inner = item.get(key)
                    if isinstance(inner, str) and inner.strip():
                        paths.append(inner.strip())
                        break
        return paths
    if isinstance(value, dict):
        for key in ("path", "filePath", "filepath", "file", "files"):
            if key in value:
                return coerce_reply_files(value.get(key))
    return []


def apply_output_mapping(
    result: Any,
    mappings: List[FieldMapping],
) -> Dict[str, Any]:
    """从流程结果映射出机器人动作字段（reply_markdown / reply_text / reply_file）。"""
    payload = extract_business_payload(result)
    actions: Dict[str, Any] = {}
    for m in mappings:
        if not m.source or not m.target:
            continue
        raw = _resolve_source_value(payload, m.source)
        if m.target in {"reply_markdown", "reply_text"}:
            text = coerce_reply_text(raw)
            if text:
                actions[m.target] = text
        elif m.target == "reply_file":
            files = coerce_reply_files(raw)
            if files:
                # 多条映射到 reply_file 时合并去重（保序）
                existing = actions.get("reply_file") or []
                merged: List[str] = list(existing) if isinstance(existing, list) else []
                for p in files:
                    if p not in merged:
                        merged.append(p)
                actions["reply_file"] = merged
        elif raw is not None:
            actions[m.target] = raw
    return actions
