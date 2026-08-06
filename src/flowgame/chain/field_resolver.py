"""Resolve node data fields from input parameters (ref / fixed) or legacy templates."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Dict, Optional

from src.flowgame.chain.enums import RefType
from src.flowgame.chain.template import format_template

if TYPE_CHECKING:
    from src.flowgame.chain.base_node import ChainNode
    from src.flowgame.chain.chain import Chain

_SELF_TEMPLATE = re.compile(r"^\{\{\s*([\w.]+)\s*\}\}$")


def _is_self_template(text: str, name: str) -> bool:
    m = _SELF_TEMPLATE.match((text or "").strip())
    return bool(m and m.group(1) == name)


def resolve_named_field(
    chain: "Chain",
    node: "ChainNode",
    name: str,
    legacy: Optional[str] = None,
) -> str:
    """Prefer input parameter named ``name``; fall back to ``legacy`` with template expansion."""
    params_map = chain.get_parameter_values(node)
    for parameter in node.parameters or []:
        if parameter.name != name:
            continue
        ref_type = parameter.ref_type or RefType.REF
        if ref_type == RefType.FIXED:
            raw = parameter.value if parameter.value is not None else legacy
            text = str(raw).strip() if raw is not None else ""
            # 避免 fixed 值写成 {{name}} 时自引用死循环
            if text and _is_self_template(text, name):
                return format_template(legacy, params_map) if legacy else ""
            return format_template(raw, params_map) if raw else ""
        if ref_type == RefType.REF:
            ref = parameter.ref or ""
            value = chain.get(ref) if ref else None
            if value is None and ref and "." not in ref:
                value = chain._resolve_bare_field(ref)
            if value is None and ref and "." in ref:
                value = chain.memory.get(ref.split(".")[-1])
            if value is not None:
                text = str(value).strip()
                if text and not _is_self_template(text, name):
                    return str(value)
            if parameter.default_value is not None:
                default = str(parameter.default_value).strip()
                if default and not _is_self_template(default, name):
                    return str(parameter.default_value)
            return format_template(legacy, params_map) if legacy else ""
        if ref_type == RefType.INPUT:
            return str(parameter.ref or "")
    return format_template(legacy, params_map)


def resolve_config_template_field(
    chain: "Chain",
    node: "ChainNode",
    field_value: Optional[str],
    template_root: Optional[Dict[str, Any]] = None,
) -> str:
    """解析厂家/模型/Key：支持字面量或 {{param}}；避免入参自引用 {{apiKey}}→{{apiKey}}。"""
    raw = (field_value or "").strip()
    if not raw:
        return ""

    exact = _SELF_TEMPLATE.match(raw)
    if exact:
        name = exact.group(1)
        resolved = resolve_named_field(chain, node, name, None)
        text = (resolved or "").strip()
        if text and not _is_self_template(text, name) and "{{" not in text:
            return text
        # 入参未解析到有效值时，勿把 {{apiKey}} 原文送给上游
        return ""

    safe_root: Dict[str, Any] = {}
    for key, value in (template_root or {}).items():
        if isinstance(value, str):
            v = value.strip()
            if _is_self_template(v, str(key)):
                continue
            if v == raw:
                continue
        safe_root[key] = value
    return format_template(raw, safe_root).strip()
