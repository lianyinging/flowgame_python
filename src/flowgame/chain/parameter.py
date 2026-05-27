"""Workflow parameter definition."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional

from src.flowgame.chain.enums import DataType, RefType


@dataclass
class Parameter:
    id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    data_type: DataType = DataType.STRING
    ref: Optional[str] = None
    ref_type: Optional[RefType] = None
    value: Optional[str] = None
    required: bool = False
    default_value: Optional[str] = None
    children: List["Parameter"] = field(default_factory=list)

    def add_children(self, params: List["Parameter"]) -> None:
        self.children.extend(params)
