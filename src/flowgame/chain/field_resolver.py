"""Resolve node data fields from input parameters (ref / fixed) or legacy templates."""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from src.flowgame.chain.enums import RefType
from src.flowgame.chain.template import format_template

if TYPE_CHECKING:
    from src.flowgame.chain.base_node import ChainNode
    from src.flowgame.chain.chain import Chain


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
            return format_template(raw, params_map) if raw else ""
        if ref_type == RefType.REF:
            ref = parameter.ref or ""
            value = chain.get(ref)
            if value is None and ref and "." in ref:
                value = chain.memory.get(ref.split(".")[-1])
            if value is not None:
                return str(value)
            if parameter.default_value is not None:
                return str(parameter.default_value)
            return format_template(legacy, params_map) if legacy else ""
        if ref_type == RefType.INPUT:
            return str(parameter.ref or "")
    return format_template(legacy, params_map)
