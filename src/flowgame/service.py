"""FlowGame execute service (IFlowGameExecuteService port)."""
from __future__ import annotations

import json
import queue
import threading
from typing import Any, Dict, Generator, List, Mapping, Optional

import logging

logger = logging.getLogger(__name__)
from src.flowgame.chain.enums import ChainStatus
from src.flowgame.chain.nodes import StartApiNode, resolve_output_by_defs
from src.flowgame.chain.parameter import Parameter
from src.flowgame.parser.base_parser import (
    get_data,
    get_end_node_output_defs_from_workflow,
    get_http_node_default_output_defs,
    parse_parameters_array,
)
from src.flowgame.tinyflow import Tinyflow
from src.flowgame.tinyflow_config import TinyflowRuntime
from src.flowgame.workflow_start_api_rules import validate_start_api_workflow
from src.flowgame.workflow_talk_rules import (
    find_start_talk_data,
    validate_assistant_message,
    validate_talk_start_workflow,
    validate_talk_start_workflow_for_page,
)
from src.flowgame.execution_logging import log_workflow_event
from src.flowgame.talk.renderer import render_talk_page
from src.flowgame.workflow_store import (
    FlowGameWorkflowStoreError,
    load_workflow_json_by_method_key,
)


class FlowGameExecuteError(Exception):
    pass


class ResolvedRequest:
    def __init__(self, workflow_json: str, variables: Optional[Dict[str, Any]]) -> None:
        self.workflow_json = workflow_json
        self.variables = variables


class FlowGameExecuteService:
    _SKIP_HTTP_HEADERS = frozenset(
        {
            "host",
            "connection",
            "content-length",
            "content-type",
            "accept",
            "accept-encoding",
            "accept-language",
            "user-agent",
            "cookie",
            "transfer-encoding",
            "expect",
            "cache-control",
            "pragma",
            "origin",
            "referer",
            "x-forwarded-for",
            "x-forwarded-host",
            "x-forwarded-proto",
            "x-real-ip",
            "userid",
            "user-id",
        }
    )

    def execute(
        self,
        body: Dict[str, Any],
        user_id: Optional[Any] = None,
        *,
        http_headers: Optional[Mapping[str, str]] = None,
    ) -> Dict[str, Any]:
        resolved = self.resolve_request(body, http_headers=http_headers)
        return self.execute_workflow(resolved.workflow_json, resolved.variables, user_id=user_id)

    def iter_execute_stream(
        self,
        body: Dict[str, Any],
        user_id: Optional[Any] = None,
        *,
        http_headers: Optional[Mapping[str, str]] = None,
    ) -> Generator[str, None, None]:
        """NDJSON 流：node_started / node_finished / workflow_finished / workflow_error。"""
        try:
            resolved = self.resolve_request(body, http_headers=http_headers)
        except FlowGameExecuteError as exc:
            yield self._stream_line("workflow_error", {"message": str(exc)})
            return

        event_queue: queue.Queue = queue.Queue()

        def on_progress(event: str, data: Dict[str, Any]) -> None:
            event_queue.put(self._stream_line(event, data))

        def run() -> None:
            try:
                self.execute_workflow(
                    resolved.workflow_json,
                    resolved.variables,
                    user_id=user_id,
                    progress_callback=on_progress,
                )
            except FlowGameExecuteError as exc:
                event_queue.put(self._stream_line("workflow_error", {"message": str(exc)}))
            except Exception as exc:
                logger.error("Tinyflow 流式执行失败", exc_info=True)
                event_queue.put(
                    self._stream_line("workflow_error", {"message": f"工作流执行失败：{exc}"})
                )
            finally:
                event_queue.put(None)

        thread = threading.Thread(target=run, name="flowgame-execute-stream", daemon=True)
        thread.start()

        while True:
            item = event_queue.get()
            if item is None:
                break
            yield item
        thread.join(timeout=0.1)

    @staticmethod
    def _stream_line(event: str, data: Dict[str, Any]) -> str:
        from src.flowgame.chain.js_engine import ensure_json_serializable

        safe_data = ensure_json_serializable(data)
        return json.dumps({"event": event, "data": safe_data}, ensure_ascii=False) + "\n"

    def execute_workflow(
        self,
        workflow_json: str,
        variables: Optional[Dict[str, Any]] = None,
        user_id: Optional[Any] = None,
        *,
        progress_callback: Optional[Any] = None,
    ) -> Dict[str, Any]:
        if not workflow_json or not str(workflow_json).strip():
            raise FlowGameExecuteError("工作流定义不能为空")
        try:
            json.loads(workflow_json)
        except json.JSONDecodeError as exc:
            raise FlowGameExecuteError("工作流定义必须是合法的 JSON") from exc

        try:
            validate_start_api_workflow(workflow_json)
        except ValueError as exc:
            raise FlowGameExecuteError(str(exc)) from exc

        params = self._build_params(variables, user_id)
        node_count = 0
        try:
            workflow_obj = json.loads(workflow_json)
            node_count = len(workflow_obj.get("nodes") or [])
        except json.JSONDecodeError:
            pass
        log_workflow_event(
            "workflow_started",
            extra={
                "userId": user_id,
                "nodeCount": node_count,
                "variableKeys": list((variables or {}).keys()),
            },
        )
        try:
            runtime = TinyflowRuntime(data=workflow_json)
            tinyflow = Tinyflow(workflow_json, runtime=runtime)
            chain = tinyflow.to_chain()
            if progress_callback:
                chain.progress_callback = progress_callback
            chain.execute_for_result(params)
            response = self._collect_chain_response(chain, workflow_json)
            logger.info("Tinyflow 执行完成 status=%s", response.get("status"))
            log_workflow_event(
                "workflow_finished",
                extra={
                    "status": response.get("status"),
                    "message": response.get("message"),
                },
            )
            if progress_callback:
                progress_callback("workflow_finished", response)
            return response
        except FlowGameExecuteError as exc:
            log_workflow_event("workflow_error", message=str(exc))
            raise
        except Exception as exc:
            logger.error("Tinyflow 工作流执行失败", exc_info=True)
            log_workflow_event("workflow_error", message=str(exc))
            raise FlowGameExecuteError(f"工作流执行失败：{exc}") from exc

    def resolve_request(
        self,
        body: Dict[str, Any],
        *,
        http_headers: Optional[Mapping[str, str]] = None,
    ) -> ResolvedRequest:
        if not body:
            raise FlowGameExecuteError("请求体不能为空")

        method_key = body.get("methodKey")
        if method_key is not None and str(method_key).strip():
            method_key = str(method_key).strip()
            try:
                workflow_json = load_workflow_json_by_method_key(method_key)
            except FlowGameWorkflowStoreError as exc:
                raise FlowGameExecuteError(str(exc)) from exc
            self._validate_method_key_in_workflow(workflow_json, method_key)
            variables = self._extract_variables(body)
            variables = self._merge_http_headers(variables, http_headers)
            return ResolvedRequest(workflow_json, variables)

        variables: Optional[Dict[str, Any]] = None
        if "workflow" in body:
            workflow = body.get("workflow")
            vars_obj = body.get("variables")
            if isinstance(vars_obj, dict):
                variables = self._strip_body_headers(dict(vars_obj))
            elif vars_obj is not None:
                raise FlowGameExecuteError("variables 必须为 JSON 对象")
        else:
            workflow = body

        if workflow is None:
            raise FlowGameExecuteError("请求体需包含 methodKey 或 workflow")

        workflow_json = self.to_workflow_json(workflow)
        variables = self._merge_http_headers(variables, http_headers)
        return ResolvedRequest(workflow_json, variables)

    @staticmethod
    def _strip_body_headers(variables: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not variables:
            return variables
        cleaned = dict(variables)
        cleaned.pop("headers", None)
        return cleaned or None

    @staticmethod
    def _extract_variables(body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        vars_obj = body.get("variables")
        if isinstance(vars_obj, dict):
            return FlowGameExecuteService._strip_body_headers(dict(vars_obj))
        if vars_obj is not None:
            raise FlowGameExecuteError("variables 必须为 JSON 对象")
        reserved = {"methodKey", "workflow", "variables", "headers"}
        extra = {k: v for k, v in body.items() if k not in reserved}
        return extra or None

    @classmethod
    def _merge_http_headers(
        cls,
        variables: Optional[Dict[str, Any]],
        http_headers: Optional[Mapping[str, str]],
    ) -> Optional[Dict[str, Any]]:
        result: Dict[str, Any] = dict(variables) if variables else {}
        result.pop("headers", None)
        if not http_headers:
            return result or None
        custom: Dict[str, str] = {}
        for key, value in http_headers.items():
            if not key or key.lower() in cls._SKIP_HTTP_HEADERS:
                continue
            if value is None:
                continue
            custom[key] = str(value)
        if custom:
            result["headers"] = custom
        return result or None

    def _validate_method_key_in_workflow(self, workflow_json: str, method_key: str) -> None:
        api_data = self.find_start_api_from_workflow(workflow_json)
        if not api_data:
            return
        configured = api_data.get("methodKey")
        if configured and str(configured).strip() and str(configured).strip() != method_key:
            raise FlowGameExecuteError(
                f"methodKey 与流程配置不一致，期望：{configured}"
            )

    @staticmethod
    def to_workflow_json(workflow: Any) -> str:
        if workflow is None:
            return ""
        if isinstance(workflow, str):
            text = workflow.strip()
            return text
        return json.dumps(workflow, ensure_ascii=False)

    def _build_params(
        self, variables: Optional[Dict[str, Any]], user_id: Optional[Any]
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if variables:
            params.update(variables)
        if user_id is not None and "userId" not in params:
            params["userId"] = user_id
        return params

    def _collect_chain_response(self, chain, workflow_json: str) -> Dict[str, Any]:
        response: Dict[str, Any] = {}
        end_output = self._resolve_end_node_output(chain, workflow_json)
        last_node_output = end_output or chain.execute_result
        if last_node_output:
            sanitized = {
                key: self._sanitize_for_json(value)
                for key, value in last_node_output.items()
            }
            response["lastNodeOutput"] = sanitized
            response["endNodeOutput"] = sanitized

        api_meta = self._collect_api_start_meta(chain, workflow_json, end_output)
        if api_meta:
            response.update(api_meta)

        if chain.status:
            response["status"] = chain.status.value if isinstance(chain.status, ChainStatus) else str(chain.status)
        if chain.message:
            response["message"] = chain.message
        if chain.execution_records:
            response["nodeExecutions"] = [
                {
                    "nodeId": item.get("nodeId"),
                    "nodeName": item.get("nodeName"),
                    "nodeType": item.get("nodeType"),
                    "status": item.get("status"),
                    "durationMs": item.get("durationMs"),
                    "output": (
                        {
                            key: self._sanitize_for_json(value)
                            for key, value in item["output"].items()
                        }
                        if isinstance(item.get("output"), dict)
                        else None
                    ),
                    "error": item.get("error"),
                }
                for item in chain.execution_records
            ]
        return response

    def _collect_api_start_meta(
        self, chain, workflow_json: str, end_output: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        start_api: StartApiNode | None = None
        for node in chain.nodes:
            if isinstance(node, StartApiNode):
                start_api = node
                break
        if not start_api:
            return {}

        meta: Dict[str, Any] = {}
        if start_api.method_key:
            meta["methodKey"] = start_api.method_key
        if start_api.external_url:
            meta["externalUrl"] = start_api.external_url
        if start_api.request_type:
            meta["requestType"] = start_api.request_type
        if start_api.api_description:
            meta["apiDescription"] = start_api.api_description

        end_output = end_output if end_output is not None else self._resolve_end_node_output(
            chain, workflow_json
        )
        output_defs = start_api.output_defs
        if not output_defs:
            output_defs = parse_parameters_array(get_http_node_default_output_defs())

        api_output = start_api.resolve_api_output(chain) if output_defs else {}
        if end_output and self._is_empty_value(api_output.get("body")):
            api_output = dict(api_output)
            api_output["body"] = end_output

        if api_output:
            meta["apiOutput"] = {
                key: self._sanitize_for_json(value)
                for key, value in api_output.items()
            }

        return meta

    def _resolve_end_node_output(self, chain, workflow_json: str) -> Dict[str, Any]:
        output_defs_json = get_end_node_output_defs_from_workflow(workflow_json)
        if output_defs_json:
            output_defs = parse_parameters_array(output_defs_json)
            result = resolve_output_by_defs(chain, output_defs)
            if self._has_effective_output(result):
                return result
        if chain.execute_result and isinstance(chain.execute_result, dict):
            return dict(chain.execute_result)
        return {}

    @staticmethod
    def _output_defs_have_refs(output_defs: List[Parameter]) -> bool:
        def walk(items: List[Parameter]) -> bool:
            for item in items:
                if (item.ref or "").strip():
                    return True
                if item.children and walk(item.children):
                    return True
            return False

        return walk(output_defs)

    @staticmethod
    def _has_effective_output(data: Dict[str, Any]) -> bool:
        return any(
            not FlowGameExecuteService._is_empty_value(value) for value in data.values()
        )

    @staticmethod
    def _is_empty_value(value: Any) -> bool:
        if value is None:
            return True
        if value == "" or value == {} or value == []:
            return True
        return False

    @staticmethod
    def find_start_api_from_workflow(workflow_json: str) -> dict | None:
        try:
            root = json.loads(workflow_json)
        except json.JSONDecodeError:
            return None
        for node_object in root.get("nodes") or []:
            if isinstance(node_object, dict) and node_object.get("type") == "node_start_api":
                return get_data(node_object)
        return None

    @staticmethod
    def _sanitize_for_json(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            return value
        if isinstance(value, (list, tuple)):
            return list(value)
        try:
            return json.loads(json.dumps(value, ensure_ascii=False, default=str))
        except (TypeError, ValueError):
            return str(value)

    def render_talk_html(
        self,
        method_key: str,
        *,
        session_id: Optional[str] = None,
    ) -> str:
        key = (method_key or "").strip()
        if not key:
            raise FlowGameExecuteError("methodKey 不能为空")
        try:
            workflow_json = load_workflow_json_by_method_key(key)
        except FlowGameWorkflowStoreError as exc:
            raise FlowGameExecuteError(str(exc)) from exc
        try:
            validate_talk_start_workflow_for_page(workflow_json)
        except ValueError as exc:
            raise FlowGameExecuteError(str(exc)) from exc

        talk_data = find_start_talk_data(workflow_json) or {}
        configured_key = (talk_data.get("methodKey") or "").strip()
        if configured_key and configured_key != key:
            raise FlowGameExecuteError(f"methodKey 与流程配置不一致，期望：{configured_key}")

        return render_talk_page(
            method_key=key,
            talk_title=str(talk_data.get("talkTitle") or "对话"),
            welcome_message=str(talk_data.get("welcomeMessage") or ""),
            talk_template=str(talk_data.get("talkTemplate") or "default"),
            session_id=session_id or "",
        )

    def execute_talk_message(
        self,
        body: Dict[str, Any],
        user_id: Optional[Any] = None,
        *,
        http_headers: Optional[Mapping[str, str]] = None,
    ) -> Dict[str, Any]:
        if not body:
            raise FlowGameExecuteError("请求体不能为空")

        method_key = str(body.get("methodKey") or "").strip()
        if not method_key:
            raise FlowGameExecuteError("methodKey 不能为空")

        message = body.get("message")
        if message is None or (isinstance(message, str) and not message.strip()):
            raise FlowGameExecuteError("message 不能为空")
        if not isinstance(message, str):
            raise FlowGameExecuteError("message 必须为字符串")

        session_id = body.get("sessionId")
        if session_id is not None and not isinstance(session_id, str):
            raise FlowGameExecuteError("sessionId 必须为字符串")

        try:
            workflow_json = load_workflow_json_by_method_key(method_key)
        except FlowGameWorkflowStoreError as exc:
            raise FlowGameExecuteError(str(exc)) from exc

        try:
            validate_talk_start_workflow(workflow_json)
        except ValueError as exc:
            raise FlowGameExecuteError(str(exc)) from exc

        talk_data = find_start_talk_data(workflow_json) or {}
        configured_key = (talk_data.get("methodKey") or "").strip()
        if configured_key and configured_key != method_key:
            raise FlowGameExecuteError(
                f"methodKey 与流程配置不一致，期望：{configured_key}"
            )

        variables: Dict[str, Any] = {"message": message.strip()}
        if session_id and str(session_id).strip():
            variables["sessionId"] = str(session_id).strip()

        extra_vars = body.get("variables")
        if extra_vars is not None:
            if not isinstance(extra_vars, dict):
                raise FlowGameExecuteError("variables 必须为 JSON 对象")
            variables.update(extra_vars)

        merged_headers = self._merge_http_headers(variables, http_headers)
        result = self.execute_workflow(
            workflow_json,
            merged_headers,
            user_id=user_id,
        )

        end_output = result.get("endNodeOutput") or result.get("lastNodeOutput") or {}
        if not isinstance(end_output, dict):
            raise FlowGameExecuteError("结束节点未返回有效输出")

        assistant_raw = end_output.get("assistantMessage")
        assistant_message = validate_assistant_message(assistant_raw)

        response: Dict[str, Any] = {
            "methodKey": method_key,
            "assistantMessage": assistant_message,
        }
        if session_id and str(session_id).strip():
            response["sessionId"] = str(session_id).strip()
        return response


flow_game_execute_service = FlowGameExecuteService()
