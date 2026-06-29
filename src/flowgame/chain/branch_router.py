"""Exclusive branch routing for ifNode / switchNode."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from src.flowgame.chain.base_node import ChainNode
from src.flowgame.chain.edge import ChainEdge


def _normalize_branch_id(branch_id: str) -> str:
    text = (branch_id or "").strip()
    lower = text.lower()
    if lower == "false":
        return "false"
    if lower == "true":
        return "true"
    if lower == "else":
        return "else"
    return text


def _edge_matches_branch(edge_branch: str, matched_branch: str) -> bool:
    edge_norm = _normalize_branch_id(edge_branch)
    match_norm = _normalize_branch_id(matched_branch)
    if edge_norm == match_norm:
        return True
    if match_norm == "false" and edge_norm == "else":
        return True
    if match_norm == "else" and edge_norm == "false":
        return True
    return False


def select_exclusive_branch_edges(
    outward_edges: List[ChainEdge],
    matched_branch: str,
) -> List[ChainEdge]:
    branch = (matched_branch or "").strip()
    if not branch:
        return []

    selected = [
        edge
        for edge in outward_edges
        if _edge_matches_branch(edge.branch or "", branch)
    ]
    if selected:
        return selected

    edges_list = list(outward_edges)
    if not edges_list:
        return []

    # 未标记 branch 时按出边顺序与 legacy true/false 回退
    if branch in ("true", "branch-0") and edges_list:
        return [edges_list[0]]
    if branch in ("false", "else") and len(edges_list) > 1:
        return [edges_list[1]]
    if len(edges_list) == 1:
        return [edges_list[0]]
    return []


def parse_if_branches_from_data(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = data.get("branches")
    if isinstance(raw, list) and raw:
        result: List[Dict[str, Any]] = []
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                continue
            btype = str(item.get("type") or "if").strip().lower()
            branch_id = str(item.get("id") or "").strip()
            if not branch_id:
                branch_id = "else" if btype == "else" else f"branch-{index}"
            entry: Dict[str, Any] = {"id": branch_id, "type": btype}
            if btype != "else":
                entry["condition"] = item.get("condition")
            result.append(entry)
        if result and result[-1].get("type") != "else":
            result.append({"id": "else", "type": "else"})
        return result

    legacy_condition = data.get("condition")
    if legacy_condition is not None and str(legacy_condition).strip():
        cond = str(legacy_condition).strip() or "true"
        return [
            {"id": "true", "type": "if", "condition": cond},
            {"id": "false", "type": "else"},
        ]
    return [
        {"id": "branch-0", "type": "if", "condition": "true"},
        {"id": "else", "type": "else"},
    ]


def parse_switch_cases_from_data(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = data.get("cases")
    if isinstance(raw, list) and raw:
        result: List[Dict[str, Any]] = []
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                continue
            case_id = str(item.get("id") or "").strip() or f"case-{index}"
            result.append(
                {
                    "id": case_id,
                    "value": item.get("value"),
                    "label": item.get("label"),
                }
            )
        return result
    return [
        {"id": "case-0", "value": "success", "label": "成功"},
        {"id": "case-1", "value": "failed", "label": "失败"},
    ]


def parse_switch_param_ref(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    match = re.match(r"^\{\{\s*(.+?)\s*}}$", text)
    if match:
        return match.group(1).strip()
    return text


def read_switch_key_from_data(data: Dict[str, Any]) -> str:
    key = data.get("switchKey")
    if isinstance(key, str) and key.strip():
        parsed = parse_switch_param_ref(key.strip())
        return parsed or "value"
    return "value"
