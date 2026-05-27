"""Tinyflow workflow entry (dev.tinyflow.core.Tinyflow port)."""
from __future__ import annotations

from src.flowgame.chain.chain import Chain
from src.flowgame.parser.chain_parser import ChainParser
from src.flowgame.tinyflow_config import TinyflowRuntime


class Tinyflow:
    def __init__(self, flow_data: str, runtime: TinyflowRuntime | None = None) -> None:
        if not flow_data or not str(flow_data).strip():
            raise ValueError("data is empty")
        self._runtime = runtime or TinyflowRuntime(data=flow_data)
        self._runtime.data = flow_data
        self._chain_parser = ChainParser()

    @property
    def data(self) -> str:
        return self._runtime.data

    def to_chain(self) -> Chain:
        return self._chain_parser.parse(self._runtime)
