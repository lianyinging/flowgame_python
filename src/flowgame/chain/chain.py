"""Workflow chain execution engine (agents-flex Chain port)."""
from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from src.flowgame.chain.base_node import ChainNode
from src.flowgame.chain.edge import ChainEdge
from src.flowgame.chain.enums import ChainStatus, DataType, RefType
from src.flowgame.chain.exceptions import ChainException, ChainSuspendException
from src.flowgame.chain.parameter import Parameter
from src.flowgame.chain.template import format_template


@dataclass
class _ExecuteNode:
    current_node: ChainNode
    prev_node: Optional[ChainNode]
    from_edge_id: str


def _resolve_path(obj: Any, parts: List[str]) -> Any:
    current = obj
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            idx = int(part)
            current = current[idx] if 0 <= idx < len(current) else None
        else:
            return None
    return current


def _coerce_string_value(value: Any) -> str:
    """将列表等结构转为字符串，供 String 类型参数与模板使用。"""
    if value is None:
        return ""
    if isinstance(value, list):
        if not value:
            return ""
        if len(value) == 1:
            return _coerce_string_value(value[0])
        return "\n".join(_coerce_string_value(item) for item in value)
    return str(value).strip()


class Chain(ChainNode):
    def __init__(self) -> None:
        super().__init__()
        self.id = str(uuid.uuid4())
        self.parent: Optional["Chain"] = None
        self.nodes: List[ChainNode] = []
        self.edges: List[ChainEdge] = []
        self.memory: Dict[str, Any] = {}
        self.execute_result: Optional[Dict[str, Any]] = None
        self.status = ChainStatus.READY
        self.message: Optional[str] = None
        self.exception: Optional[Exception] = None
        self.suspend_nodes: List[ChainNode] = []
        self.suspend_for_parameters: List[Parameter] = []
        self.execution_records: List[Dict[str, Any]] = []
        self.progress_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None
        self._executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="flowgame-chain")

    def _emit_progress(self, event: str, data: Dict[str, Any]) -> None:
        if self.progress_callback:
            self.progress_callback(event, data)

    def add_node(self, node: ChainNode) -> None:
        if not node.id:
            node.id = str(uuid.uuid4())
        if isinstance(node, Chain):
            node.parent = self
        self.nodes.append(node)

    def add_edge(self, edge: ChainEdge) -> None:
        self.edges.append(edge)
        for node in self.nodes:
            if node.id == edge.source:
                node.add_outward_edge(edge)
            elif node.id == edge.target:
                node.add_inward_edge(edge)

    def _resolve_bare_field(self, field: str) -> Any:
        """解析未带节点 id 的字段名（如 content、answer），匹配 memory 中 *.field。"""
        if not field or "." in field:
            return None
        if field in self.memory:
            return self.memory[field]
        suffix = f".{field}"
        matches = {k: v for k, v in self.memory.items() if k.endswith(suffix)}
        if not matches:
            return None
        if len(matches) == 1:
            return next(iter(matches.values()))
        best_key = max(matches.keys(), key=len)
        return matches[best_key]

    def get(self, key: str) -> Any:
        if not key:
            return None
        if key in self.memory:
            return self.memory[key]
        parts = key.split(".")
        for i in range(len(parts), 0, -1):
            try_key = ".".join(parts[:i])
            temp = self.memory.get(try_key)
            if temp is not None:
                remaining = parts[i:]
                if not remaining:
                    return temp
                if isinstance(temp, list):
                    if len(remaining) == 1 and remaining[0].isdigit():
                        idx = int(remaining[0])
                        return temp[idx] if 0 <= idx < len(temp) else None
                    return [_resolve_path(item, remaining) for item in temp]
                return _resolve_path(temp, remaining)
        if "." not in key:
            return self._resolve_bare_field(key)
        return None

    def set(self, key: str, value: Any) -> None:
        self.memory[key] = value

    def get_parameter_values(
        self,
        node: ChainNode,
        parameters: Optional[List[Parameter]] = None,
        format_args: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        params = parameters if parameters is not None else node.parameters
        if not params:
            return {}
        variables: Dict[str, Any] = {}
        for parameter in params:
            ref_type = parameter.ref_type or RefType.REF
            if ref_type == RefType.FIXED:
                value: Any = (
                    format_template(parameter.value, format_args)
                    if format_args
                    else parameter.value
                )
            elif ref_type == RefType.REF:
                ref = parameter.ref or ""
                value = self.get(ref)
                if value is None and ref and "." not in ref:
                    value = self._resolve_bare_field(ref)
                if value is None and ref and "." in ref:
                    value = self.memory.get(ref.split(".")[-1])
                if value is None and parameter.default_value is not None:
                    value = parameter.default_value
            else:
                value = self.get(parameter.name or "")

            if parameter.required and (
                value is None or (isinstance(value, str) and not str(value).strip())
            ):
                if ref_type in (RefType.FIXED, RefType.REF):
                    raise ChainException(
                        f"{node.name} Missing required parameter: {parameter.name}"
                    )
                self.add_suspend_for_parameter(parameter)
                self.suspend(node)
                raise ChainSuspendException(
                    f"{type(node).__name__} Missing required parameter: {parameter.name}"
                )

            if isinstance(value, (list, dict)):
                variables[parameter.name or ""] = value
                continue

            if parameter.data_type in (
                DataType.ARRAY_OBJECT,
                DataType.ARRAY_STRING,
                DataType.ARRAY_NUMBER,
                DataType.ARRAY_BOOLEAN,
                DataType.ARRAY_FILE,
            ) or (
                parameter.data_type in (DataType.OBJECT, None)
                and isinstance(value, (list, dict))
            ):
                pass
            elif parameter.data_type == DataType.STRING or (
                parameter.data_type is None and not isinstance(value, (list, dict))
            ):
                value = _coerce_string_value(value)
            elif value is None or isinstance(value, str):
                text = "" if value is None else str(value).strip()
                if parameter.data_type == DataType.BOOLEAN:
                    value = text.lower() in ("true", "1")
                elif parameter.data_type == DataType.NUMBER and text:
                    try:
                        value = int(text) if "." not in text else float(text)
                    except ValueError:
                        value = text
                else:
                    value = text
            variables[parameter.name or ""] = value
        return variables

    def execute(self, variables: Optional[Dict[str, Any]] = None) -> None:
        self._run_in_lifecycle(variables or {}, self._execute_internal)

    def execute_for_result(
        self, variables: Optional[Dict[str, Any]] = None, ignore_error: bool = False
    ) -> Dict[str, Any]:
        if self.status == ChainStatus.SUSPEND:
            self.resume(variables or {})
        else:
            self._run_in_lifecycle(variables or {}, self._execute_internal)

        if not ignore_error:
            if self.status == ChainStatus.FINISHED_ABNORMAL:
                if self.exception:
                    if isinstance(self.exception, ChainException):
                        raise self.exception
                    raise ChainException(str(self.exception)) from self.exception
                raise ChainException(self.message or "Chain execute error")
            if self.status == ChainStatus.SUSPEND and self.exception:
                raise self.exception
        return self.execute_result or {}

    def resume(self, variables: Dict[str, Any]) -> None:
        self._run_in_lifecycle(variables, self._execute_internal)

    def stop_normal(self, message: str) -> None:
        self.message = message
        self.status = ChainStatus.FINISHED_NORMAL

    def stop_error(self, message: str) -> None:
        self.message = message
        self.status = ChainStatus.FINISHED_ABNORMAL

    def suspend(self, node: ChainNode) -> None:
        if node not in self.suspend_nodes:
            self.suspend_nodes.append(node)
        self.status = ChainStatus.SUSPEND

    def add_suspend_for_parameter(self, parameter: Parameter) -> None:
        self.suspend_for_parameters.append(parameter)

    def _run_in_lifecycle(self, variables: Dict[str, Any], runnable) -> None:
        self.memory.update(variables)
        try:
            self.status = ChainStatus.RUNNING
            try:
                runnable()
            except ChainSuspendException as exc:
                self.exception = exc
                self.status = ChainStatus.SUSPEND
            except Exception as exc:
                self.exception = exc
                self.status = ChainStatus.ERROR
        finally:
            if self.status == ChainStatus.RUNNING:
                self.status = ChainStatus.FINISHED_NORMAL
            elif self.status == ChainStatus.ERROR:
                self.status = ChainStatus.FINISHED_ABNORMAL

    def _execute_internal(self) -> None:
        start_nodes = self._get_start_nodes()
        if not start_nodes:
            return
        execute_nodes = [_ExecuteNode(node, None, "") for node in start_nodes]
        self._do_execute_nodes(execute_nodes)

    def _get_start_nodes(self) -> List[ChainNode]:
        if not self.nodes:
            return []
        if self.suspend_nodes:
            return list(self.suspend_nodes)
        return [n for n in self.nodes if not n.inward_edges]

    def _get_node_by_id(self, node_id: str) -> Optional[ChainNode]:
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None

    def _do_execute_nodes(self, execute_nodes: List[_ExecuteNode]) -> None:
        futures = []
        for item in execute_nodes:
            if item.current_node.async_exec:
                futures.append(self._executor.submit(self._do_execute_node, item))
            else:
                self._do_execute_node(item)
        for future in futures:
            future.result()

    def _record_node_execution(
        self,
        node: ChainNode,
        status: str,
        *,
        output: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        duration_ms: int = 0,
    ) -> None:
        record: Dict[str, Any] = {
            "nodeId": node.id,
            "nodeName": node.name,
            "nodeType": node.node_type,
            "status": status,
            "durationMs": duration_ms,
        }
        if output is not None:
            record["output"] = output
        if error:
            record["error"] = error
        self.execution_records.append(record)
        self._emit_progress("node_finished", dict(record))

    def _do_execute_node(self, execute_node: _ExecuteNode) -> None:
        if self.status != ChainStatus.RUNNING:
            return
        current = execute_node.current_node
        if current.condition and not current.condition.check_node(self):
            self._record_node_execution(current, "skipped")
            return

        self._emit_progress(
            "node_started",
            {
                "nodeId": current.id,
                "nodeName": current.name,
                "nodeType": current.node_type,
            },
        )

        started = time.perf_counter()
        try:
            execute_result = current.execute(self)
        except Exception as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            self._record_node_execution(
                current,
                "error",
                error=str(exc),
                duration_ms=duration_ms,
            )
            raise

        duration_ms = int((time.perf_counter() - started) * 1000)
        self.execute_result = execute_result
        output_snapshot = dict(execute_result) if execute_result else None
        self._record_node_execution(
            current,
            "success",
            output=output_snapshot,
            duration_ms=duration_ms,
        )

        if execute_result:
            for key, value in execute_result.items():
                self.memory[f"{current.id}.{key}"] = value

        if self.status != ChainStatus.RUNNING:
            return

        if not current.outward_edges:
            return

        next_execute_nodes: List[_ExecuteNode] = []
        for edge in current.outward_edges:
            if edge.condition and not edge.condition.check_edge(self, edge):
                continue
            next_node = self._get_node_by_id(edge.target or "")
            if next_node:
                next_execute_nodes.append(_ExecuteNode(next_node, current, edge.id or ""))
        if next_execute_nodes:
            self._do_execute_nodes(next_execute_nodes)
