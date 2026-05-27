"""Node/edge condition evaluation."""
from __future__ import annotations

from typing import Any, Dict, Optional, Protocol

from src.flowgame.chain.js_engine import eval_js_bool


class NodeCondition(Protocol):
    def check_node(self, chain: "Chain", context: Any = None) -> bool: ...


class EdgeCondition(Protocol):
    def check_edge(self, chain: "Chain", edge: Any = None) -> bool: ...


class JavascriptStringCondition:
    def __init__(self, code: str) -> None:
        self.code = code.strip() if code else ""

    def check_node(self, chain: "Chain", context: Any = None) -> bool:
        extra = {"_context": context} if context is not None else None
        return eval_js_bool(self.code, chain.memory, extra)

    def check_edge(self, chain: "Chain", edge: Any = None) -> bool:
        extra = {"_edge": edge} if edge is not None else None
        return eval_js_bool(self.code, chain.memory, extra)
