"""Workflow edge definition."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.flowgame.chain.condition import EdgeCondition


@dataclass
class ChainEdge:
    id: Optional[str] = None
    source: Optional[str] = None
    target: Optional[str] = None
    condition: Optional[EdgeCondition] = None
    branch: Optional[str] = None
