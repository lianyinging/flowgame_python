"""OSS 节点专用参数解析（不改动全局 chain.get_parameter_values）。"""
from __future__ import annotations

import re
import time
from typing import Any, Dict, Optional

from src.flowgame.chain.enums import RefType
from src.flowgame.chain.parameter import Parameter

_PLACEHOLDER = re.compile(r"\{\{\s*(.+?)\s*}}")


def oss_path_string(value: Any) -> str:
    """Object Key 路径：单元素列表取首项，避免 str(list) -> \"['x']\"。"""
    if value is None:
        return ""
    if isinstance(value, list):
        if not value:
            return ""
        if len(value) == 1:
            return oss_path_string(value[0])
        return "\n".join(oss_path_string(item) for item in value)
    return str(value).strip()


def _resolve_oss_parameter(chain: Any, parameter: Parameter) -> Any:
    ref_type = parameter.ref_type or RefType.REF
    value: Any = None
    if ref_type == RefType.FIXED:
        value = parameter.value
    elif ref_type == RefType.REF:
        ref = (parameter.ref or "").strip()
        if ref:
            value = chain.get(ref)
            if value is None and "." not in ref:
                value = chain._resolve_bare_field(ref)
            if value is None and "." in ref:
                value = chain.memory.get(ref.split(".")[-1])
        if value is None and parameter.default_value is not None:
            value = parameter.default_value
        if value is None and parameter.value is not None and str(parameter.value).strip():
            value = parameter.value
    else:
        value = chain.get(parameter.name or "")
        if value is None and parameter.value is not None and str(parameter.value).strip():
            value = parameter.value
    return value


def resolve_oss_parameters(chain: Any, node: Any) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for parameter in node.parameters or []:
        name = (parameter.name or "").strip()
        if not name:
            continue
        result[name] = _resolve_oss_parameter(chain, parameter)
    return result


def oss_content_is_empty(content: Any) -> bool:
    if content is None:
        return True
    if isinstance(content, str):
        return not content.strip()
    if isinstance(content, (list, dict)):
        return len(content) == 0
    return False


def _get_by_path(root: Dict[str, Any], path: str) -> Any:
    if not path:
        return None
    current: Any = root
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
        if current is None:
            return None
    return current


def format_oss_object_key_template(
    template: Optional[str],
    root_map: Optional[Dict[str, Any]] = None,
) -> str:
    """OSS Object Key 模板渲染：仅在此处对占位符做路径字符串规范化。"""
    if not template:
        return ""
    root = root_map or {}

    def replacer(match: re.Match) -> str:
        content = match.group(1).strip()
        parts = re.split(r"\s*\?\?\s*", content, maxsplit=1)
        expr = parts[0].strip()
        default = ""
        if len(parts) == 2:
            default_raw = parts[1].strip()
            if (default_raw.startswith("'") and default_raw.endswith("'")) or (
                default_raw.startswith('"') and default_raw.endswith('"')
            ):
                default = default_raw[1:-1]
            else:
                default = default_raw
        value = _get_by_path(root, expr)
        if value is None:
            return default
        return oss_path_string(value)

    return _PLACEHOLDER.sub(replacer, template).strip()


def render_object_key_template(
    template: str,
    chain_memory: Dict[str, Any],
    param_values: Dict[str, Any],
) -> str:
    merged = dict(chain_memory)
    merged.update(param_values)
    merged.setdefault("timestamp", str(int(time.time() * 1000)))
    return format_oss_object_key_template(template, merged)
