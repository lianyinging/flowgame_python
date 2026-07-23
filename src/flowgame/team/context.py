"""Context Engineering：主控看摘要，子 Agent 按 input_keys 装箱。"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from src.flowgame.team.builtin import SUB_AGENT_SPECS


def clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…（已截断，原长 {len(text)} 字）"


def _value_type_name(val: Any) -> str:
    if val is None:
        return "null"
    if isinstance(val, bool):
        return "boolean"
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return "number"
    if isinstance(val, str):
        return "string"
    if isinstance(val, list):
        return "array"
    if isinstance(val, dict):
        return "object"
    return "other"


def _is_empty(val: Any) -> bool:
    if val is None:
        return True
    if isinstance(val, str):
        return not val.strip()
    if isinstance(val, (list, dict)):
        return len(val) == 0
    return False


class ContextEngine:
    def __init__(
        self,
        master_field_limit: int = 500,
        worker_field_limit: int = 3500,
        recent_trace_limit: int = 8,
    ) -> None:
        self.master_field_limit = master_field_limit
        self.worker_field_limit = worker_field_limit
        self.recent_trace_limit = recent_trace_limit

    def status_card(self, state: Dict[str, Any], keys: List[str]) -> Dict[str, Any]:
        """主控看板：从黑板投影为 JSON 对象（非 Markdown 文本）。

        每个 key 对应：
        {
          "empty": bool,
          "type": "string"|"array"|...,
          "chars": int,          # 序列化后字符数（空则为 0）
          "itemCount": int?,     # 仅 array
          "preview": str         # 截断预览；empty 时为 ""
        }
        """
        card: Dict[str, Any] = {}
        for key in keys:
            val = state.get(key)
            empty = _is_empty(val)
            entry: Dict[str, Any] = {
                "empty": empty,
                "type": _value_type_name(val),
                "chars": 0,
                "preview": "",
            }
            if isinstance(val, list):
                entry["itemCount"] = len(val)
            if empty:
                card[key] = entry
                continue

            if isinstance(val, (list, dict)):
                try:
                    serialized = json.dumps(val, ensure_ascii=False, default=str)
                except TypeError:
                    serialized = str(val)
            else:
                serialized = str(val)

            entry["chars"] = len(serialized)
            entry["preview"] = clip(serialized, self.master_field_limit)
            card[key] = entry
        return card

    def status_card_json(
        self,
        state: Dict[str, Any],
        keys: List[str],
        *,
        indent: Optional[int] = 2,
    ) -> str:
        """看板 JSON 字符串（内置主控 Prompt / 日志用）。"""
        return json.dumps(
            self.status_card(state, keys),
            ensure_ascii=False,
            indent=indent,
        )

    def pack_for_master(
        self,
        state: Dict[str, Any],
        trace: List[Dict[str, Any]],
        step_idx: int,
        max_steps: int,
        status_keys: List[str],
    ) -> str:
        recent = trace[-self.recent_trace_limit :]
        trace_lines = []
        for item in recent:
            trace_lines.append(
                f"- step={item.get('step')} action={item.get('action')} "
                f"agent={item.get('next_agent')} "
                f"ok={item.get('ok')} note={item.get('note')}"
            )
        card_json = self.status_card_json(state, status_keys)
        return (
            f"当前步数：{step_idx}/{max_steps}\n\n"
            f"## 状态卡片（JSON）\n{card_json}\n\n"
            f"## 最近调度轨迹\n"
            + ("\n".join(trace_lines) if trace_lines else "- （尚无）")
            + "\n\n请输出下一步决策 JSON。"
        )

    def pack_for_worker(
        self,
        role_name: str,
        state: Dict[str, Any],
        focus: str,
        input_keys: List[str] | None = None,
    ) -> Dict[str, str]:
        keys = input_keys
        if keys is None:
            spec = SUB_AGENT_SPECS.get(role_name) or {}
            keys = list(spec.get("input_keys") or [])
        packed: Dict[str, str] = {"focus": (focus or "按你的职责完成任务").strip()}
        for key in keys:
            packed[key] = clip(str(state.get(key) or ""), self.worker_field_limit)
        return packed
