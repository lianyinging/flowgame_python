"""Base workflow node."""
from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional

from src.flowgame.chain.condition import NodeCondition
from src.flowgame.chain.edge import ChainEdge
from src.flowgame.chain.parameter import Parameter

if TYPE_CHECKING:
    from src.flowgame.chain.chain import Chain


class ChainNode:
    def __init__(self) -> None:
        self.id: Optional[str] = None
        self.name: Optional[str] = None
        self.description: Optional[str] = None
        self.node_type: Optional[str] = None
        self.async_exec: bool = False
        self.inward_edges: List[ChainEdge] = []
        self.outward_edges: List[ChainEdge] = []
        self.condition: Optional[NodeCondition] = None
        self.parameters: List[Parameter] = []
        self.output_defs: List[Parameter] = []

    def execute(self, chain: "Chain") -> Dict[str, object]:
        raise NotImplementedError

    def add_outward_edge(self, edge: ChainEdge) -> None:
        self.outward_edges.append(edge)

    def add_inward_edge(self, edge: ChainEdge) -> None:
        self.inward_edges.append(edge)


class BaseNode(ChainNode):
    def set_parameters(self, parameters: List[Parameter]) -> None:
        self.parameters = parameters or []

    def add_output_def(self, parameter: Parameter) -> None:
        self.output_defs.append(parameter)
