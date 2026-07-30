"""Built-in workflow node implementations."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple
import requests

from src.flowgame.chain.base_node import BaseNode
from src.flowgame.chain.chain import Chain
from src.flowgame.chain.enums import DataType, RefType
from src.flowgame.chain.js_engine import eval_js, eval_python
from src.flowgame.chain.parameter import Parameter
from src.flowgame.chain.field_resolver import resolve_named_field
from src.flowgame.chain.template import format_template


def _parse_optional_json_object(raw: Any) -> Dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    text = str(raw).strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _extract_openai_chat_content(payload: Any) -> str:
    """从 OpenAI 兼容 chat.completion 中提取助手文本。

    DeepSeek 等推理模型常把最终答复写在 reasoning_content，而 content 为空；
    此时应回退到 reasoning_content，并尽量抽出其中的 JSON 决策块。
    """
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""

    candidates: List[str] = []
    message = first.get("message")
    if isinstance(message, dict):
        for key in ("content", "reasoning_content", "reasoning"):
            raw = message.get(key)
            if raw is None:
                continue
            text = str(raw).strip()
            if text:
                candidates.append(text)
    text_field = first.get("text")
    if text_field is not None:
        text = str(text_field).strip()
        if text:
            candidates.append(text)

    if not candidates:
        return ""

    # 优先非空 content（已在 candidates[0] 若存在）；若仅有推理字段，尝试抽出 JSON
    primary = candidates[0]
    if primary.lstrip().startswith("{") and primary.rstrip().endswith("}"):
        return primary

    for text in candidates:
        extracted = _extract_trailing_json_object(text)
        if extracted:
            return extracted
    return primary


def _extract_trailing_json_object(text: str) -> str:
    """从混杂文本中提取最后一个完整 JSON 对象（主控决策常见形态）。"""
    raw = (text or "").strip()
    if not raw:
        return ""
    if raw.startswith("{") and raw.endswith("}"):
        try:
            json.loads(raw)
            return raw
        except json.JSONDecodeError:
            pass
    end = raw.rfind("}")
    if end < 0:
        return ""
    depth = 0
    start = -1
    for i in range(end, -1, -1):
        ch = raw[i]
        if ch == "}":
            depth += 1
        elif ch == "{":
            depth -= 1
            if depth == 0:
                start = i
                break
    if start < 0:
        return ""
    candidate = raw[start : end + 1]
    try:
        json.loads(candidate)
        return candidate
    except json.JSONDecodeError:
        return ""


def _format_api_error_message(status_code: int, payload: Any, request_url: str = "") -> str:
    prefix = f"HTTP {status_code}"
    if request_url:
        prefix = f"{prefix} [{request_url}]"
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict):
            msg = err.get("message") or err.get("msg")
            if msg:
                return f"{prefix}: {msg}"
        if payload.get("message"):
            return f"{prefix}: {payload.get('message')}"
        if payload.get("_text"):
            text = str(payload["_text"]).strip()
            if text:
                return f"{prefix}: {text[:500]}"
    return f"{prefix}: 模型接口请求失败"


def normalize_chat_completions_url(url: str) -> str:
    """将仅填域名/根路径的地址补全为 OpenAI 兼容 Chat Completions URL。"""
    text = (url or "").strip().rstrip("/")
    if not text:
        return text
    lower = text.lower()
    if "/chat/completions" in lower:
        return text
    if lower.endswith("/v1"):
        return f"{text}/chat/completions"
    return f"{text}/v1/chat/completions"


def _dict_get_case_insensitive(data: Dict[str, Any], key: str) -> Any:
    if key in data:
        return data[key]
    lower = key.lower()
    for k, v in data.items():
        if k.lower() == lower:
            return v
    return None


def _lookup_request_field(
    chain: Chain,
    name: str,
    ref: str,
    parent_name: Optional[str] = None,
) -> Any:
    """从 execute 入参写入的 chain.memory 中解析字段（支持 headers.newParam 等嵌套）。"""
    name = (name or "").strip()
    ref = (ref or name).strip()
    keys: List[str] = []
    if parent_name and name:
        keys.append(f"{parent_name}.{name}")
    if ref:
        keys.append(ref)
    if name:
        keys.append(name)
    seen: set[str] = set()
    for key in keys:
        if not key or key in seen:
            continue
        seen.add(key)
        value = chain.get(key)
        if value is not None:
            return value
    if parent_name and name:
        parent_val = chain.memory.get(parent_name)
        if isinstance(parent_val, dict):
            found = _dict_get_case_insensitive(parent_val, name)
            if found is not None:
                return found
    if ref and "." in ref:
        value = chain.get(ref)
        if value is not None:
            return value
    bare = ref.split(".")[-1] if ref else name
    if bare and bare in chain.memory:
        return chain.memory.get(bare)
    return None


def _resolve_start_api_output_value(
    chain: Chain,
    output_def: Parameter,
    method_key: Optional[str] = None,
    parent_name: Optional[str] = None,
) -> Any:
    """解析 Api 开始节点 outputDefs，支持 body.text、headers.newParam 等嵌套字段。"""
    if output_def.children:
        obj: Dict[str, Any] = {}
        group_name = (output_def.name or "").strip() or parent_name
        for child in output_def.children:
            child_name = (child.name or "").strip()
            if not child_name:
                continue
            obj[child_name] = _resolve_start_api_output_value(
                chain, child, method_key, parent_name=group_name
            )
        if group_name:
            parent_val = _lookup_request_field(chain, group_name, group_name, parent_name=None)
            if isinstance(parent_val, dict):
                for child in output_def.children:
                    child_name = (child.name or "").strip()
                    if not child_name:
                        continue
                    val = _dict_get_case_insensitive(parent_val, child_name)
                    if val is not None and (
                        child_name not in obj or _is_empty_value(obj.get(child_name))
                    ):
                        obj[child_name] = val
        return obj

    name = (output_def.name or "").strip()
    ref_type = output_def.ref_type or RefType.REF
    if ref_type == RefType.FIXED:
        return output_def.value or output_def.default_value

    ref_key = (output_def.ref or name).strip()
    if ref_type in (RefType.REF, RefType.INPUT):
        value = _lookup_request_field(chain, name, ref_key, parent_name)
        if value is None and name == "methodKey" and method_key:
            value = method_key
        if value is not None:
            return _apply_output_default(value, output_def.default_value)
        if ref_type == RefType.INPUT:
            return output_def.value if output_def.value is not None else output_def.default_value

    return _apply_output_default(None, output_def.default_value)


def _resolve_chain_output_value(
    chain: Chain,
    output_def: Parameter,
    parent_name: Optional[str] = None,
) -> Any:
    """解析结束节点等上游引用（chain.memory 中 nodeId.field）。"""
    if output_def.children:
        obj: Dict[str, Any] = {}
        group_name = (output_def.name or "").strip() or parent_name
        for child in output_def.children:
            child_name = (child.name or "").strip()
            if not child_name:
                continue
            obj[child_name] = _resolve_chain_output_value(
                chain, child, parent_name=group_name
            )
        return obj

    ref_type = output_def.ref_type or RefType.REF
    if ref_type == RefType.FIXED:
        return output_def.value or output_def.default_value

    ref_key = (output_def.ref or output_def.name or "").strip()
    if ref_type in (RefType.REF, RefType.INPUT):
        value = chain.get(ref_key) if ref_key else None
        if value is None and ref_key and "." not in ref_key:
            value = chain._resolve_bare_field(ref_key)
        if value is not None:
            return _apply_output_default(value, output_def.default_value)
        if ref_type == RefType.INPUT:
            return output_def.value if output_def.value is not None else output_def.default_value

    return _apply_output_default(None, output_def.default_value)


def _is_empty_value(value: Any) -> bool:
    if value is None:
        return True
    if value == "" or value == {} or value == []:
        return True
    return False


class StartNode(BaseNode):
    def execute(self, chain: Chain) -> Dict[str, Any]:
        return chain.get_parameter_values(self)


class StartTalkNode(StartNode):
    """对话开始节点：供 GET /talk 打开对话页；执行时透出 message / sessionId / imgBase64List。"""

    def __init__(self) -> None:
        super().__init__()
        self.method_key: Optional[str] = None
        self.talk_template: str = "default"
        self.talk_title: Optional[str] = None
        self.welcome_message: Optional[str] = None

    def execute(self, chain: Chain) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        message = chain.memory.get("message")
        if message is not None:
            result["message"] = message
        session_id = chain.memory.get("sessionId")
        if session_id is not None:
            result["sessionId"] = session_id
        img_list = chain.memory.get("imgBase64List")
        if img_list is not None:
            result["imgBase64List"] = img_list
        return result


class StartApiNode(StartNode):
    """API 接口开始节点：作为外部调用入口，定义对外返回字段映射（无输入参数）。"""

    def __init__(self) -> None:
        super().__init__()
        self.method_key: Optional[str] = None
        self.external_url: Optional[str] = None
        self.request_type: str = "post"
        self.api_description: Optional[str] = None

    def execute(self, chain: Chain) -> Dict[str, Any]:
        """将外部请求体字段写入节点输出（memory 键为 {nodeId}.{name}），供下游 ref 引用。"""
        return self._build_start_outputs(chain)

    def _build_start_outputs(self, chain: Chain) -> Dict[str, Any]:
        if not self.output_defs:
            skip = {"methodKey", "workflow", "variables"}
            return {
                k: v
                for k, v in chain.memory.items()
                if k not in skip and "." not in str(k)
            }

        result: Dict[str, Any] = {}
        for output_def in self.output_defs:
            name = (output_def.name or "").strip()
            if not name:
                continue
            result[name] = _resolve_start_api_output_value(
                chain, output_def, self.method_key
            )
        return result

    def resolve_api_output(self, chain: Chain) -> Dict[str, Any]:
        built = self._build_start_outputs(chain)
        if built:
            return built
        return resolve_output_by_defs(
            chain, self.output_defs, self.method_key, from_request=True
        )


class ForkNode(BaseNode):
    """分叉：同时启动所有出边分支（引擎层强制并行）。"""

    def execute(self, chain: Chain) -> Dict[str, Any]:
        return {
            "forked": True,
            "branches": len(self.outward_edges),
        }


class IfNode(BaseNode):
    """条件选择器：if / else if / else 顺序匹配，互斥路由。"""

    def __init__(self) -> None:
        super().__init__()
        self.condition_expr: Optional[str] = None
        self.branches: List[Dict[str, Any]] = []

    def execute(self, chain: Chain) -> Dict[str, Any]:
        from src.flowgame.chain.branch_router import parse_if_branches_from_data
        from src.flowgame.chain.js_engine import eval_js_bool

        param_scope = chain.get_parameter_values(self)
        branches = self.branches or parse_if_branches_from_data(
            {"condition": self.condition_expr, "branches": []}
        )

        matched_branch: Optional[str] = None
        matched = False
        for branch in branches:
            btype = str(branch.get("type") or "if").strip().lower()
            branch_id = str(branch.get("id") or "").strip() or "else"
            if btype == "else":
                matched_branch = branch_id
                matched = False
                break
            expr = str(branch.get("condition") or "").strip()
            if expr:
                rendered = format_template(expr, param_scope)
                if eval_js_bool(rendered, chain.memory, extra=param_scope):
                    matched_branch = branch_id
                    matched = True
                    break

        if matched_branch is None:
            matched_branch = "else"

        return {"matched": matched, "branch": matched_branch}


class SwitchNode(BaseNode):
    """分支选择器：将输入参数与 case 值做字符串相等匹配。"""

    def __init__(self) -> None:
        super().__init__()
        self.switch_key: str = "value"
        self.cases: List[Dict[str, Any]] = []

    def execute(self, chain: Chain) -> Dict[str, Any]:
        param_scope = chain.get_parameter_values(self)
        key = (self.switch_key or "value").strip() or "value"
        switch_value = param_scope.get(key)
        if switch_value is None:
            switch_value = chain.get(key)
            if switch_value is None:
                switch_value = chain._resolve_bare_field(key)

        switch_text = "" if switch_value is None else str(switch_value).strip()
        for case in self.cases:
            case_id = str(case.get("id") or "").strip()
            case_value_raw = str(case.get("value") or "").strip()
            case_value = (
                format_template(case_value_raw, param_scope).strip()
                if case_value_raw
                else ""
            )
            if case_id and case_value and switch_text == case_value:
                return {
                    "matched": True,
                    "branch": case_id,
                    "switchValue": switch_text,
                }

        return {"matched": False, "branch": "else", "switchValue": switch_text}


class JoinAllNode(BaseNode):
    """汇聚（全部）：等待所有入边上游成功后再执行一次下游。"""

    def execute(self, chain: Chain) -> Dict[str, Any]:
        from src.flowgame.chain.join_barrier import handle_join_arrival

        return handle_join_arrival(
            chain,
            self.id,
            "all",
            chain._join_source_id,
        )


class JoinAnyNode(BaseNode):
    """汇聚（任一）：首个成功上游触发下游，仅执行一次。"""

    def execute(self, chain: Chain) -> Dict[str, Any]:
        from src.flowgame.chain.join_barrier import handle_join_arrival

        return handle_join_arrival(
            chain,
            self.id,
            "any",
            chain._join_source_id,
        )


class EndNode(BaseNode):
    def __init__(self) -> None:
        super().__init__()
        self.name = "end"
        self.normal = True
        self.end_message: Optional[str] = None

    def execute(self, chain: Chain) -> Dict[str, Any]:
        if self.end_message:
            if self.normal:
                chain.stop_normal(self.end_message)
            else:
                chain.stop_error(self.end_message)

        if not self.output_defs:
            return {}

        return resolve_output_by_defs(chain, self.output_defs)


class EndApiNode(EndNode):
    """Api 接口结束：自定义对外输出；可关闭 /execute 过程详情。"""

    def __init__(self) -> None:
        super().__init__()
        self.name = "end_api"
        # True：响应含 nodeExecutions；False：仅自定义 outputDefs
        self.include_execution_details: bool = True


class LlmNode(BaseNode):
    def __init__(self) -> None:
        super().__init__()
        self.llm = None
        self.user_prompt: Optional[str] = None
        self.system_prompt: Optional[str] = None
        self.out_type: str = "text"
        self.top_k: int = 10
        self.top_p: float = 0.8
        self.temperature: float = 0.8

    def execute(self, chain: Chain) -> Dict[str, Any]:
        if not self.user_prompt or not self.llm:
            return {}

        params = chain.get_parameter_values(self)
        user_content = format_template(self.user_prompt, params)
        messages: List[Dict[str, str]] = []
        if self.system_prompt:
            messages.append(
                {"role": "system", "content": format_template(self.system_prompt, params)}
            )
        messages.append({"role": "user", "content": user_content})

        response = self.llm.chat(
            messages,
            temperature=self.temperature,
            top_p=self.top_p,
        )
        if response.get("error"):
            chain.stop_error(str(response["error"]))
            return {}

        content = response.get("content", "")
        out_type = (self.out_type or "text").lower()
        if out_type in ("text", "markdown"):
            if not self.output_defs:
                return {"output": content}
            return {self.output_defs[0].name or "output": content}

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            chain.stop_error(f"Can not parse json: {content} {exc}")
            return {}

        result: Dict[str, Any] = {}
        for output_def in self.output_defs or []:
            result[output_def.name or ""] = parsed.get(output_def.name)
        return result


class LlmApiNode(BaseNode):
    """模型调用：HTTP 请求 OpenAI 兼容 Chat Completions 接口。"""

    def __init__(self) -> None:
        super().__init__()
        self.model_api_url: Optional[str] = None
        self.api_key: Optional[str] = None
        self.model_name: str = "gpt-4o-mini"
        self.auth_type: str = "bearer"
        self.auth_header_name: str = "Authorization"
        self.request_timeout_ms: int = 60000
        self.system_prompt: Optional[str] = None
        self.user_prompt: Optional[str] = None
        self.temperature: float = 0.7
        self.max_tokens: int = 2048
        self.response_format: str = "text"
        self.extra_headers_json: Optional[str] = None
        self.extra_body_json: Optional[str] = None

    def execute(self, chain: Chain) -> Dict[str, Any]:
        raw_url = (self.model_api_url or "").strip()
        if not raw_url:
            return self._failure("模型接口地址未配置")
        url = normalize_chat_completions_url(raw_url)

        params = chain.get_parameter_values(self)
        user_message = resolve_named_field(chain, self, "userMessage", None)
        if user_message:
            params["userMessage"] = user_message

        # 模板根：链路 memory（含 Team 注入的 status_card/topic 等）+ 节点参数
        # 仅认 {{ var }}；{var} 不会被替换（避免破坏 Prompt 里的 JSON 示例）
        template_root: Dict[str, Any] = {**(chain.memory or {}), **params}

        messages: List[Dict[str, str]] = []
        if self.system_prompt:
            system_content = format_template(self.system_prompt, template_root)
            if system_content.strip():
                messages.append({"role": "system", "content": system_content})

        user_content = ""
        if self.user_prompt:
            user_content = format_template(self.user_prompt, template_root)
        elif user_message:
            user_content = user_message

        if not user_content.strip():
            return self._failure("用户提示词与 userMessage 输入均为空")

        messages.append({"role": "user", "content": user_content})

        body: Dict[str, Any] = {
            "model": self.model_name or "gpt-4o-mini",
            "messages": messages,
            "temperature": self.temperature,
        }
        if self.max_tokens > 0:
            body["max_tokens"] = self.max_tokens
        if self.response_format == "json_object":
            body["response_format"] = {"type": "json_object"}

        extra_body = _parse_optional_json_object(self.extra_body_json)
        if extra_body:
            body.update(extra_body)

        headers: Dict[str, str] = {"Content-Type": "application/json"}
        api_key = (self.api_key or "").strip()
        if api_key:
            if self.auth_type == "header":
                header_name = (self.auth_header_name or "Authorization").strip() or "Authorization"
                headers[header_name] = api_key
            else:
                headers["Authorization"] = f"Bearer {api_key}"

        extra_headers = _parse_optional_json_object(self.extra_headers_json)
        for key, value in extra_headers.items():
            if value is not None:
                headers[str(key)] = str(value)

        timeout_sec = max(1.0, self.request_timeout_ms / 1000.0)
        try:
            response = requests.post(url, json=body, headers=headers, timeout=timeout_sec)
        except requests.RequestException as exc:
            chain.stop_error(f"模型接口请求异常: {exc}")
            return self._failure(str(exc))

        raw: Any
        try:
            raw = response.json()
        except ValueError:
            raw = {"_text": response.text}

        if response.status_code >= 400:
            message = _format_api_error_message(response.status_code, raw, url)
            if response.status_code == 404 and raw_url != url:
                message = (
                    f"{message}（已自动补全为 {url}，若仍 404 请在节点填写完整 Chat Completions 地址）"
                )
            chain.stop_error(message)
            return self._failure(message, raw)

        content = _extract_openai_chat_content(raw)
        return {"output": content, "errorMessage": "", "rawResponse": raw}

    def _failure(self, message: str, raw: Any = None) -> Dict[str, Any]:
        return {
            "output": "",
            "errorMessage": message,
            "rawResponse": raw if isinstance(raw, dict) else {},
        }


class CodeNode(BaseNode):
    def __init__(self, engine: str = "js") -> None:
        super().__init__()
        self.engine = (engine or "js").strip().lower()
        self.code: Optional[str] = None

    def execute(self, chain: Chain) -> Dict[str, Any]:
        if not self.code or not str(self.code).strip():
            raise ValueError("Code is null or blank.")
        params = chain.get_parameter_values(self)
        if self.engine in ("python", "py"):
            result = eval_python(self.code, chain.memory, extra=params)
        else:
            result = eval_js(self.code, chain.memory, extra=params)
        return _normalize_code_result(result, self.output_defs)


class HttpNode(BaseNode):
    def __init__(self) -> None:
        super().__init__()
        self.url: Optional[str] = None
        self.method: Optional[str] = None
        self.headers: List[Parameter] = []
        self.body_type: Optional[str] = None
        self.form_data: List[Parameter] = []
        self.form_urlencoded: List[Parameter] = []
        self.body_json: Optional[str] = None
        self.raw_body: Optional[str] = None

    def execute(self, chain: Chain) -> Dict[str, Any]:
        args_map = chain.get_parameter_values(self)
        new_url = format_template(self.url, args_map)
        headers_map = chain.get_parameter_values(self, self.headers, args_map)
        method = (self.method or "GET").upper()

        kwargs: Dict[str, Any] = {"headers": {k: str(v) for k, v in headers_map.items()}, "timeout": 60}
        if method != "GET":
            kwargs.update(self._build_body(chain, args_map))

        response = requests.request(method, new_url, **kwargs)
        result: Dict[str, Any] = {
            "statusCode": response.status_code,
            "headers": dict(response.headers),
        }
        body_text = response.text
        if body_text:
            out_data_type = None
            for output_def in self.output_defs or []:
                if (output_def.name or "").lower() == "body":
                    out_data_type = output_def.data_type
                    break
            if out_data_type in (DataType.OBJECT, DataType.ARRAY_OBJECT, DataType.ARRAY_STRING):
                try:
                    result["body"] = response.json()
                except ValueError:
                    result["body"] = body_text
            else:
                result["body"] = body_text
        return result

    def _build_body(self, chain: Chain, format_args: Dict[str, Any]) -> Dict[str, Any]:
        body_type = self.body_type or "none"
        if body_type == "json":
            body_str = format_template(self.body_json, format_args)
            return {"json": json.loads(body_str) if body_str else {}}
        if body_type == "x-www-form-urlencoded":
            data = chain.get_parameter_values(self, self.form_urlencoded)
            return {"data": data}
        if body_type == "form-data":
            data = chain.get_parameter_values(self, self.form_data, format_args)
            return {"data": data}
        if body_type == "raw":
            return {"data": format_template(self.raw_body, format_args)}
        return {}


class TemplateNode(BaseNode):
    def __init__(self) -> None:
        super().__init__()
        self.template: Optional[str] = None

    def execute(self, chain: Chain) -> Dict[str, Any]:
        params = chain.get_parameter_values(self)
        rendered = format_template(self.template, params)
        output_name = "output"
        if self.output_defs:
            name = self.output_defs[0].name
            if name:
                output_name = name
        return {output_name: rendered}


class LoopNode(BaseNode):
    def __init__(self) -> None:
        super().__init__()
        self.loop_var: Optional[Parameter] = None
        self.loop_chain: Optional[Chain] = None

    def execute(self, chain: Chain) -> Dict[str, Any]:
        if not self.loop_chain or not self.loop_var:
            return {}
        self.loop_chain.parent = chain
        loop_vars = chain.get_parameter_values(self, [self.loop_var])
        value = loop_vars.get(self.loop_var.name or "")
        result: Dict[str, Any] = {}

        def run_iteration(loop_params: Dict[str, Any]) -> None:
            merged = dict(loop_vars)
            merged.update(chain.memory)
            merged.update(loop_params)
            self.loop_chain.execute(merged)
            _fill_loop_result(result, self.output_defs or [], self.loop_chain.memory)

        if isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                run_iteration({"loopItem": item, "index": index})
        elif isinstance(value, (int, float)):
            count = int(value)
            for i in range(count):
                run_iteration({"loopItem": i, "index": i})

        for output_def in self.output_defs or []:
            if output_def.ref_type == RefType.INPUT:
                result[output_def.name or ""] = output_def.ref
        return result


class KnowledgeNode(BaseNode):
    def __init__(self) -> None:
        super().__init__()
        self.knowledge_id: Any = None
        self.knowledge = None
        self.keyword: Optional[str] = None
        self.limit: Optional[str] = None

    def execute(self, chain: Chain) -> Dict[str, Any]:
        if not self.knowledge:
            return {}
        real_keyword = resolve_named_field(chain, self, "keyword", self.keyword)
        if not (real_keyword or "").strip():
            real_keyword = resolve_named_field(chain, self, "text", None)
        real_limit = self._resolve_limit(chain)
        documents = self.knowledge.search(real_keyword, real_limit)
        result: Dict[str, Any] = {"documents": documents}
        if documents:
            first = documents[0]
            if isinstance(first, dict):
                for key in ("title", "content", "documentId", "knowledgeId", "question", "answer"):
                    if key in first and first[key] is not None:
                        result[key] = first[key]
        return result

    def _resolve_limit(self, chain: Chain) -> int:
        real_limit = 10
        limit_str = resolve_named_field(chain, self, "limit", self.limit)
        if limit_str:
            try:
                real_limit = int(limit_str)
            except ValueError:
                pass
        return max(1, min(real_limit, 100))


class KnowledgeNodePlus(KnowledgeNode):
    """知识库 Plus：从 FlowGame Qdrant Collection 检索。"""

    def __init__(self) -> None:
        super().__init__()
        self.collection_name: Optional[str] = None

    def execute(self, chain: Chain) -> Dict[str, Any]:
        if not self.collection_name:
            return {}
        from src.flowgame.tinyflow_config import QdrantCollectionKnowledge

        self.knowledge = QdrantCollectionKnowledge(self.collection_name)
        return super().execute(chain)


def _resolve_node_param(chain: Chain, node: BaseNode, param_name: str) -> Any:
    params = chain.get_parameter_values(node)
    if param_name in params and params[param_name] is not None:
        return params[param_name]
    for parameter in node.parameters or []:
        if (parameter.name or "") != param_name:
            continue
        ref_type = parameter.ref_type or RefType.REF
        if ref_type == RefType.FIXED:
            return parameter.value
        ref = (parameter.ref or "").strip()
        if ref:
            value = chain.get(ref)
            if value is None and "." not in ref:
                value = chain._resolve_bare_field(ref)
            if value is not None:
                return value
    return None


def _memory_write_groups_from_node(node: BaseNode) -> List[Tuple[str, str, str]]:
    """解析多组 contextKey / memoryValue（contextKey2、memoryValue2 …）。"""
    groups: Dict[str, Dict[str, str]] = {}
    for parameter in node.parameters or []:
        name = (parameter.name or "").strip()
        ctx = re.fullmatch(r"contextKey(\d*)", name)
        if ctx:
            suffix = ctx.group(1) or "1"
            groups.setdefault(suffix, {})["context_name"] = name
        val = re.fullmatch(r"memoryValue(\d*)", name)
        if val:
            suffix = val.group(1) or "1"
            groups.setdefault(suffix, {})["value_name"] = name

    result: List[Tuple[str, str, str]] = []
    for suffix in sorted(groups.keys(), key=lambda s: int(s) if str(s).isdigit() else 0):
        entry = groups[suffix]
        if "context_name" in entry and "value_name" in entry:
            result.append((suffix, entry["context_name"], entry["value_name"]))
    if result:
        return result
    if any((p.name or "") == "contextKey" for p in node.parameters or []):
        return [("1", "contextKey", "memoryValue")]
    return []


class MemoryWriteNode(BaseNode):
    """记忆写入：RPUSH 到 flow_game:flow_context:{md5(contextKey)} 列表（支持多组）。"""

    def __init__(self) -> None:
        super().__init__()
        self.max_list_size: int = 0
        self.expire_seconds: int = 0

    def execute(self, chain: Chain) -> Dict[str, Any]:
        from src.flowgame.memory_context import (
            build_context_redis_key,
            serialize_list_item,
        )
        from src.flowgame.redis.client import redis_client

        base = {
            "success": False,
            "redisKey": "",
            "listLength": 0,
            "writtenCount": 0,
            "writes": [],
            "errorMessage": "",
        }
        if not redis_client.ping():
            base["errorMessage"] = "Redis 不可用"
            return base

        groups = _memory_write_groups_from_node(self)
        if not groups:
            base["errorMessage"] = "未配置记忆组（contextKey + memoryValue）"
            return base

        writes: List[Dict[str, Any]] = []
        errors: List[str] = []
        last_key = ""
        last_len = 0
        touched_keys: set[str] = set()

        for suffix, ctx_name, val_name in groups:
            row: Dict[str, Any] = {
                "group": suffix,
                "success": False,
                "redisKey": "",
                "listLength": 0,
                "errorMessage": "",
            }
            context_raw = _resolve_node_param(chain, self, ctx_name)
            memory_value = _resolve_node_param(chain, self, val_name)
            try:
                redis_key = build_context_redis_key(context_raw)
            except ValueError as exc:
                row["errorMessage"] = str(exc)
                errors.append(f"组{suffix}: {exc}")
                writes.append(row)
                continue

            row["redisKey"] = redis_key
            if memory_value is None or (
                isinstance(memory_value, str) and not memory_value.strip()
            ):
                row["errorMessage"] = "memoryValue 引用值为空"
                errors.append(f"组{suffix}: memoryValue 为空")
                writes.append(row)
                continue

            payload = serialize_list_item(memory_value)
            list_len = redis_client.rpush(redis_key, payload)
            if list_len <= 0:
                row["errorMessage"] = "写入 Redis 列表失败"
                errors.append(f"组{suffix}: 写入失败")
                writes.append(row)
                continue

            if self.max_list_size > 0 and list_len > self.max_list_size:
                redis_client.ltrim(redis_key, -self.max_list_size, -1)
                list_len = redis_client.llen(redis_key)

            if self.expire_seconds > 0 and redis_key not in touched_keys:
                redis_client.expire(redis_key, self.expire_seconds)
                touched_keys.add(redis_key)

            row["success"] = True
            row["listLength"] = list_len
            writes.append(row)
            last_key = redis_key
            last_len = list_len

        written = [w for w in writes if w.get("success")]
        return {
            "success": len(written) > 0,
            "redisKey": last_key,
            "listLength": last_len,
            "writtenCount": len(written),
            "writes": writes,
            "errorMessage": "; ".join(errors),
        }


class MemoryReadNode(BaseNode):
    """记忆提取：LRANGE 读取 flow_game:flow_context:{md5(contextKey)} 列表。"""

    def __init__(self) -> None:
        super().__init__()
        self.read_limit: int = 50

    def execute(self, chain: Chain) -> Dict[str, Any]:
        from src.flowgame.memory_context import (
            build_context_redis_key,
            parse_list_items,
            slice_list_tail,
        )
        from src.flowgame.redis.client import redis_client

        empty: Dict[str, Any] = {
            "items": [],
            "redisKey": "",
            "count": 0,
            "errorMessage": "",
        }
        if not redis_client.ping():
            empty["errorMessage"] = "Redis 不可用"
            return empty

        context_raw = _resolve_node_param(chain, self, "contextKey")
        try:
            redis_key = build_context_redis_key(context_raw)
        except ValueError as exc:
            empty["errorMessage"] = str(exc)
            return empty

        limit = self.read_limit
        limit_param = _resolve_node_param(chain, self, "readLimit")
        if limit_param is not None and str(limit_param).strip():
            try:
                limit = max(0, int(float(limit_param)))
            except (TypeError, ValueError):
                pass

        raw_items = redis_client.lrange(redis_key, 0, -1)
        items = parse_list_items(raw_items)
        items = slice_list_tail(items, limit if limit > 0 else None)

        return {
            "items": items,
            "redisKey": redis_key,
            "count": len(items),
            "errorMessage": "",
        }


class StateMachineNode(BaseNode):
    """状态机：Redis String JSON 实体状态（write / read / delete / update）。"""

    def __init__(self) -> None:
        super().__init__()
        self.mode: str = "write"
        self.namespace: str = "default"
        self.key_template: str = "{{entityKey}}"
        self.expire_seconds: int = 0
        self.refresh_ttl: bool = True
        self.default_status: str = "unknown"
        self.fail_if_missing: bool = False
        self.return_last_state: bool = True

    def execute(self, chain: Chain) -> Dict[str, Any]:
        from src.flowgame.redis.client import redis_client
        from src.flowgame.state_context import (
            build_state_document,
            build_state_redis_key,
            deep_merge_payload,
            empty_state_result,
            flatten_state_outputs,
            parse_payload_value,
            parse_state_document,
            render_state_key_template,
            resolve_method_key_from_chain,
        )

        base = empty_state_result()
        if not redis_client.ping():
            base["errorMessage"] = "Redis 不可用"
            return base

        method_key = resolve_method_key_from_chain(chain)
        params = chain.get_parameter_values(self)
        try:
            entity_rendered = render_state_key_template(
                self.key_template,
                chain.memory,
                params,
                method_key=method_key,
            )
            redis_key = build_state_redis_key(
                self.namespace,
                entity_rendered,
            )
        except ValueError as exc:
            base["errorMessage"] = str(exc)
            return base

        base["redisKey"] = redis_key
        mode = (self.mode or "write").strip().lower()
        updated_by = f"flow:{method_key}"

        if mode == "read":
            return self._execute_read(redis_client, redis_key, base)
        if mode == "delete":
            return self._execute_delete(redis_client, redis_key, base)
        if mode == "update":
            return self._execute_update(
                chain, redis_client, redis_key, base, params, updated_by
            )
        return self._execute_write(
            chain, redis_client, redis_key, base, params, updated_by
        )

    def _execute_read(
        self, redis_client, redis_key: str, base: Dict[str, Any]
    ) -> Dict[str, Any]:
        from src.flowgame.state_context import flatten_state_outputs, parse_state_document

        exists = bool(redis_client.exists(redis_key))
        base["exists"] = exists
        if not exists:
            if self.fail_if_missing:
                base["errorMessage"] = "状态 Key 不存在"
                return base
            base["success"] = True
            base["ttlSeconds"] = -2
            base["status"] = self.default_status or "unknown"
            base["payload"] = {}
            base["state"] = {}
            return base

        raw = redis_client.get(redis_key)
        state = parse_state_document(raw) or {}
        flat = flatten_state_outputs(state)
        base.update(flat)
        base["success"] = True
        base["ttlSeconds"] = redis_client.ttl(redis_key)
        return base

    def _execute_delete(
        self, redis_client, redis_key: str, base: Dict[str, Any]
    ) -> Dict[str, Any]:
        from src.flowgame.state_context import flatten_state_outputs, parse_state_document

        exists = bool(redis_client.exists(redis_key))
        base["exists"] = exists
        if not exists:
            if self.fail_if_missing:
                base["errorMessage"] = "状态 Key 不存在"
                return base
            base["success"] = True
            base["deleted"] = False
            return base

        last_state: Dict[str, Any] = {}
        if self.return_last_state:
            raw = redis_client.get(redis_key)
            last_state = parse_state_document(raw) or {}
            flat = flatten_state_outputs(last_state)
            base["lastState"] = flat["state"]
            base["status"] = flat["status"]
            base["payload"] = flat["payload"]

        deleted_count = redis_client.delete(redis_key)
        base["success"] = deleted_count > 0
        base["deleted"] = deleted_count > 0
        return base

    def _execute_write(
        self,
        chain: Chain,
        redis_client,
        redis_key: str,
        base: Dict[str, Any],
        params: Dict[str, Any],
        updated_by: str,
    ) -> Dict[str, Any]:
        from src.flowgame.state_context import (
            build_state_document,
            flatten_state_outputs,
            parse_state_document,
        )

        status = _resolve_node_param(chain, self, "status")
        if status is None or not str(status).strip():
            base["errorMessage"] = "write 模式 status 不能为空"
            return base

        previous = parse_state_document(redis_client.get(redis_key)) or {}
        new_state = build_state_document(
            status=str(status).strip(),
            progress=_resolve_node_param(chain, self, "progress"),
            message=_resolve_node_param(chain, self, "message"),
            payload=_resolve_node_param(chain, self, "payload"),
            updated_by=updated_by,
        )
        if not redis_client.set_json(redis_key, new_state):
            base["errorMessage"] = "写入 Redis 失败"
            return base
        if self.expire_seconds > 0 and self.refresh_ttl:
            redis_client.expire(redis_key, self.expire_seconds)

        flat = flatten_state_outputs(new_state)
        base.update(flat)
        base["previousState"] = previous
        base["success"] = True
        base["exists"] = True
        base["ttlSeconds"] = redis_client.ttl(redis_key)
        return base

    def _execute_update(
        self,
        chain: Chain,
        redis_client,
        redis_key: str,
        base: Dict[str, Any],
        params: Dict[str, Any],
        updated_by: str,
    ) -> Dict[str, Any]:
        from src.flowgame.state_context import (
            build_state_document,
            deep_merge_payload,
            flatten_state_outputs,
            parse_payload_value,
            parse_state_document,
            utc_now_iso,
        )

        previous = parse_state_document(redis_client.get(redis_key))
        exists = previous is not None

        if not exists:
            if self.fail_if_missing:
                base["errorMessage"] = "状态 Key 不存在"
                return base
            status = _resolve_node_param(chain, self, "status")
            if status is None or not str(status).strip():
                base["errorMessage"] = "update 创建新状态时 status 不能为空"
                return base
            new_state = build_state_document(
                status=str(status).strip(),
                progress=_resolve_node_param(chain, self, "progress"),
                message=_resolve_node_param(chain, self, "message"),
                payload=_resolve_node_param(chain, self, "payload"),
                updated_by=updated_by,
            )
            changed = ["status", "progress", "message", "payload"]
        else:
            new_state = dict(previous or {})
            changed: List[str] = []
            status = _resolve_node_param(chain, self, "status")
            if status is not None and str(status).strip():
                new_state["status"] = str(status).strip()
                changed.append("status")
            progress = _resolve_node_param(chain, self, "progress")
            if progress is not None and str(progress).strip() != "":
                try:
                    new_state["progress"] = float(progress)
                except (TypeError, ValueError):
                    pass
                else:
                    changed.append("progress")
            message = _resolve_node_param(chain, self, "message")
            if message is not None and str(message).strip():
                new_state["message"] = str(message).strip()
                changed.append("message")
            payload_raw = _resolve_node_param(chain, self, "payload")
            if payload_raw is not None:
                patch = parse_payload_value(payload_raw)
                if patch:
                    prev_payload = new_state.get("payload")
                    new_state["payload"] = deep_merge_payload(prev_payload, patch)
                    changed.append("payload")
            new_state["updatedAt"] = utc_now_iso()
            new_state["updatedBy"] = updated_by

        if not redis_client.set_json(redis_key, new_state):
            base["errorMessage"] = "更新 Redis 失败"
            return base
        if self.expire_seconds > 0 and self.refresh_ttl:
            redis_client.expire(redis_key, self.expire_seconds)

        flat = flatten_state_outputs(new_state)
        base.update(flat)
        base["previousState"] = previous or {}
        base["changedFields"] = changed
        base["success"] = True
        base["exists"] = True
        base["ttlSeconds"] = redis_client.ttl(redis_key)
        return base


class DatabaseNode(BaseNode):
    """数据库：入参渲染 MyBatis 风格 SQL 模板，默认 MySQL，结果 JSON 数组输出。"""

    def __init__(self) -> None:
        super().__init__()
        self.db_type: str = "mysql"
        self.sql_template: Optional[str] = None

    def execute(self, chain: Chain) -> Dict[str, Any]:
        from src.flowgame.chain.mybatis_sql import json_safe_value, render_mybatis_sql
        from src.flowgame.mysql.client import mysql_utils
        from src.flowgame.settings import get_flowgame_settings

        result: Dict[str, Any] = {
            "success": False,
            "data": [],
            "rowCount": 0,
            "errorMessage": "",
            "executedSql": "",
        }
        template = (self.sql_template or "").strip()
        if not template:
            result["errorMessage"] = "未配置 SQL 模板"
            return result

        db_type = (self.db_type or "mysql").strip().lower()
        if db_type != "mysql":
            result["errorMessage"] = f"暂不支持的数据库类型: {db_type}"
            return result

        cfg = get_flowgame_settings()
        if not (cfg.mysql_host or "").strip():
            result["errorMessage"] = "MySQL 未配置（请设置 MYSQL_HOST 等环境变量）"
            return result

        params = chain.get_parameter_values(self)
        try:
            sql, bind_values = render_mybatis_sql(template, params)
        except Exception as exc:
            result["errorMessage"] = f"SQL 模板解析失败: {exc}"
            return result

        from src.flowgame.chain.mybatis_sql import (
            _is_select_statement,
            split_bind_values_for_statements,
            split_sql_statements,
        )

        try:
            statements = split_sql_statements(sql)
            if not statements:
                result["errorMessage"] = "渲染后的 SQL 为空"
                return result
            stmt_binds = split_bind_values_for_statements(statements, bind_values)
        except Exception as exc:
            result["errorMessage"] = str(exc)
            return result

        from src.flowgame.chain.mybatis_sql import format_executed_sql
        from src.flowgame.execution_logging import log_database_sql

        last_executed_sql = ""
        try:
            with mysql_utils.connection() as conn:
                with conn.cursor() as cursor:
                    last_data: List[Any] = []
                    last_row_count = 0
                    for stmt_text, stmt_binds in zip(statements, stmt_binds):
                        last_executed_sql = format_executed_sql(
                            stmt_text, stmt_binds, cursor=cursor
                        )
                        cursor.execute(stmt_text, stmt_binds)
                        if _is_select_statement(stmt_text):
                            rows = cursor.fetchall() or []
                            last_data = [json_safe_value(dict(row)) for row in rows]
                            last_row_count = len(last_data)
                        else:
                            last_data = []
                            last_row_count = int(cursor.rowcount or 0)
                    result["success"] = True
                    result["data"] = last_data
                    result["rowCount"] = last_row_count
        except Exception as exc:
            result["errorMessage"] = str(exc)
        finally:
            if last_executed_sql:
                result["executedSql"] = last_executed_sql
                log_database_sql(
                    node_id=self.id,
                    node_name=self.name,
                    sql=last_executed_sql,
                )
        return result


class OssNode(BaseNode):
    """对象存储：按 fileType 上传 content（文本或图片 URL）到阿里云 OSS。"""

    def __init__(self) -> None:
        super().__init__()
        self.file_type: str = "txt"
        self.object_key_template: Optional[str] = None
        self.bucket: Optional[str] = None

    def execute(self, chain: Chain) -> Dict[str, Any]:
        from src.flowgame.oss.client import upload_content
        from src.flowgame.oss.params import (
            oss_content_is_empty,
            oss_path_string,
            render_object_key_template,
            resolve_oss_parameters,
        )
        from src.flowgame.settings import get_flowgame_settings

        result: Dict[str, Any] = {
            "success": False,
            "url": "",
            "objectKey": "",
            "fileType": self.file_type or "txt",
            "contentType": "",
            "etag": "",
            "errorMessage": "",
        }

        params = resolve_oss_parameters(chain, self)
        content = params.get("content")
        if oss_content_is_empty(content):
            result["errorMessage"] = (
                "content 为空：请在输入参数中为 content 选择上游引用（如 htmlTemplateNode.html、"
                "httpNode.body.html），或类型选「固定值」粘贴 HTML/文本"
            )
            return result

        object_key = oss_path_string(params.get("objectKey"))
        if not object_key:
            template = (self.object_key_template or "").strip()
            if not template:
                result["errorMessage"] = "未配置 Object Key 模板"
                return result
            object_key = render_object_key_template(
                template,
                chain.memory,
                params,
            )
            if not object_key:
                result["errorMessage"] = "Object Key 渲染结果为空"
                return result

        try:
            cfg = get_flowgame_settings()
            uploaded = upload_content(
                content=content,
                file_type=self.file_type or "txt",
                object_key=object_key,
                bucket=self.bucket,
                settings=cfg,
            )
            result.update(uploaded)
        except Exception as exc:
            result["errorMessage"] = str(exc)
        return result


class SearchEngineNode(BaseNode):
    def __init__(self) -> None:
        super().__init__()
        self.engine: Optional[str] = None
        self.search_engine = None
        self.keyword: Optional[str] = None
        self.limit: Optional[str] = None

    def execute(self, chain: Chain) -> Dict[str, Any]:
        if not self.search_engine:
            return {}
        args_map = chain.get_parameter_values(self)
        real_keyword = format_template(self.keyword, args_map)
        real_limit = 10
        limit_str = format_template(self.limit, args_map)
        if limit_str:
            try:
                real_limit = int(limit_str)
            except ValueError:
                pass
        documents = self.search_engine.search(real_keyword, real_limit)
        return {"documents": documents}


class WebSearchNode(BaseNode):
    """多引擎网页搜索（自定义节点 webSearchNode）。"""

    def __init__(self) -> None:
        super().__init__()
        self.engines: List[str] = ["qq_news"]
        self.keyword: Optional[str] = None
        self.limit: Optional[str] = None

    def execute(self, chain: Chain) -> Dict[str, Any]:
        from src.flowgame.web.search import search_web

        real_keyword = resolve_named_field(chain, self, "keyword", self.keyword)
        if not (real_keyword or "").strip():
            real_keyword = resolve_named_field(chain, self, "text", None)
        real_limit = 10
        limit_str = resolve_named_field(chain, self, "limit", self.limit)
        if limit_str:
            try:
                real_limit = int(float(str(limit_str)))
            except (TypeError, ValueError):
                pass
        payload = search_web(str(real_keyword or ""), self.engines, real_limit)
        documents = payload.get("documents") or []
        errors = payload.get("errors") or []
        result: Dict[str, Any] = {
            "documents": documents,
            "errorMessage": "; ".join(str(e) for e in errors) if errors else "",
        }
        if documents:
            first = documents[0]
            if isinstance(first, dict):
                for key in ("title", "content", "url"):
                    if first.get(key) is not None:
                        result[key] = first[key]
        elif not result["errorMessage"]:
            result["errorMessage"] = "未检索到结果"
        return result


class FetchUrlNode(BaseNode):
    """抓取 URL 并抽取正文（自定义节点 fetchUrlNode）。

    入参 urls（数组 / 单字符串 / documents）；兼容旧参数 url / link。
    优先 Jina Reader，失败再 requests+strip。输出 documents + 首条便捷字段。
    """

    def __init__(self) -> None:
        super().__init__()
        self.max_chars: Optional[str] = None

    def execute(self, chain: Chain) -> Dict[str, Any]:
        from src.flowgame.web.fetch import DEFAULT_MAX_CHARS, fetch_url_documents

        raw_urls = _resolve_node_param(chain, self, "urls")
        if raw_urls is None:
            raw_urls = _resolve_node_param(chain, self, "url")
        if raw_urls is None:
            raw_urls = _resolve_node_param(chain, self, "link")
        if raw_urls is None:
            # 兼容直接引用 documents
            raw_urls = _resolve_node_param(chain, self, "documents")

        hint_title = _resolve_node_param(chain, self, "title")
        hint_titles: List[Optional[str]] = []
        if isinstance(raw_urls, (list, tuple)):
            for item in raw_urls:
                if isinstance(item, dict) and item.get("title"):
                    hint_titles.append(str(item.get("title")))
                else:
                    hint_titles.append(None)
        elif hint_title:
            hint_titles = [str(hint_title)]

        max_chars = DEFAULT_MAX_CHARS
        if self.max_chars:
            try:
                max_chars = int(float(str(self.max_chars)))
            except (TypeError, ValueError):
                pass
        return fetch_url_documents(
            raw_urls,
            max_chars=max_chars,
            hint_titles=hint_titles or None,
        )


class ImageGenNode(BaseNode):
    """图像生成：OpenAI SDK 或 DashScope 原生（自定义节点 imageGenNode）。"""

    def __init__(self) -> None:
        super().__init__()
        self.provider: str = "openai"
        self.base_url: Optional[str] = None
        self.api_key: Optional[str] = None
        self.model: str = "doubao-seedream-5-0-260128"
        self.size: str = "2K"
        self.prompt_template: Optional[str] = "{{prompt}}"
        self.response_format: str = "url"
        self.extra_body_json: Optional[str] = None
        self.request_timeout_ms: int = 120000

    def execute(self, chain: Chain) -> Dict[str, Any]:
        params = chain.get_parameter_values(self)
        prompt_value = resolve_named_field(chain, self, "prompt", None)
        if prompt_value is not None:
            params["prompt"] = prompt_value

        template = (self.prompt_template or "{{prompt}}").strip() or "{{prompt}}"
        prompt = format_template(template, params).strip()
        if not prompt:
            return self._failure("生图提示词 prompt 为空")

        api_key = (self.api_key or "").strip()
        if not api_key:
            return self._failure("API Key 未配置")

        base_url = (self.base_url or "").strip().rstrip("/")
        if not base_url:
            return self._failure("Base URL 未配置")

        model = (self.model or "").strip()
        if not model:
            return self._failure("模型 model 未配置")

        size = (self.size or "").strip() or None
        extra_body = _parse_optional_json_object(self.extra_body_json)
        timeout_sec = max(5.0, self.request_timeout_ms / 1000.0)
        provider = (self.provider or "openai").strip().lower()
        image_urls = self._collect_image_urls(chain, params)

        try:
            if provider in ("dashscope", "qwen", "bailian"):
                return self._execute_dashscope(
                    chain,
                    prompt=prompt,
                    api_key=api_key,
                    base_url=base_url,
                    model=model,
                    size=size,
                    extra_body=extra_body,
                    timeout_sec=timeout_sec,
                    image_urls=image_urls,
                )
            if image_urls:
                return self._failure(
                    "图生图/编辑仅支持 DashScope 协议；请将「接口协议」改为 DashScope 原生"
                )
            return self._execute_openai(
                chain,
                prompt=prompt,
                api_key=api_key,
                base_url=base_url,
                model=model,
                size=size,
                extra_body=extra_body,
                timeout_sec=timeout_sec,
            )
        except Exception as exc:  # noqa: BLE001
            message = str(exc) or "图像生成失败"
            chain.stop_error(f"图像生成失败: {message}")
            return self._failure(message)

    def _collect_image_urls(self, chain: Chain, params: Dict[str, Any]) -> List[str]:
        """
        收集参考图（最多 3 张）。

        imageUrl 兼容：
        - 单张：字符串 URL / data:image/...;base64,...
        - 多张：list / JSON 数组字符串；也可配合 imageUrl2 / imageUrl3 / images
        """
        urls: List[str] = []

        def _blank(raw: Any) -> bool:
            if raw is None:
                return True
            if isinstance(raw, (list, tuple, dict)):
                return len(raw) == 0
            return not str(raw).strip()

        def _push(raw: Any) -> None:
            if raw is None:
                return
            if isinstance(raw, (list, tuple)):
                for item in raw:
                    _push(item)
                return
            text = str(raw).strip()
            if not text:
                return
            if text.startswith("["):
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, list):
                        for item in parsed:
                            _push(item)
                        return
                except json.JSONDecodeError:
                    pass
            if "," in text and not text.startswith("data:"):
                parts = [p.strip() for p in text.split(",") if p.strip()]
                if len(parts) > 1 and all(
                    p.startswith("http") or p.startswith("oss://") or p.startswith("data:")
                    for p in parts
                ):
                    for p in parts:
                        _push(p)
                    return
            if text not in urls:
                urls.append(text)

        for name in ("imageUrl", "imageUrl2", "imageUrl3", "images"):
            # 优先 params：保留 list，避免 resolve_named_field 把数组 str() 成不可解析文本
            value = params.get(name) if name in params else None
            if _blank(value):
                value = self._resolve_image_field_raw(chain, name)
            _push(value)

        return urls[:3]

    def _resolve_image_field_raw(self, chain: Chain, name: str) -> Any:
        """读取 imageUrl 等参数的原始值（list / str），不做 str() 强制转换。"""
        for parameter in self.parameters or []:
            if parameter.name != name:
                continue
            ref_type = parameter.ref_type or RefType.REF
            if ref_type == RefType.FIXED:
                return parameter.value
            if ref_type == RefType.REF:
                ref = parameter.ref or ""
                value = chain.get(ref) if ref else None
                if value is None and ref and "." in ref:
                    value = chain.memory.get(ref.split(".")[-1])
                if value is None and parameter.default_value is not None:
                    return parameter.default_value
                return value
            if ref_type == RefType.INPUT:
                return parameter.ref
        return None

    def _execute_openai(
        self,
        chain: Chain,
        *,
        prompt: str,
        api_key: str,
        base_url: str,
        model: str,
        size: Optional[str],
        extra_body: Dict[str, Any],
        timeout_sec: float,
    ) -> Dict[str, Any]:
        from openai import OpenAI

        response_format = (self.response_format or "url").strip().lower() or "url"
        if response_format not in ("url", "b64_json"):
            response_format = "url"
        body = dict(extra_body)
        body.pop("response_format", None)

        client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout_sec)
        kwargs: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "response_format": response_format,
        }
        if size:
            kwargs["size"] = size
        if body:
            kwargs["extra_body"] = body

        response = client.images.generate(**kwargs)
        raw = self._response_to_dict(response)
        urls: List[str] = []
        b64_first = ""
        for item in getattr(response, "data", None) or []:
            url = getattr(item, "url", None)
            if url:
                urls.append(str(url))
            b64 = getattr(item, "b64_json", None)
            if b64 and not b64_first:
                b64_first = str(b64)

        if not urls and not b64_first:
            return self._failure("未返回图片结果", raw)

        return {
            "success": True,
            "url": urls[0] if urls else "",
            "urls": urls,
            "b64Json": b64_first,
            "rawResponse": raw,
            "errorMessage": "",
        }

    def _execute_dashscope(
        self,
        chain: Chain,
        *,
        prompt: str,
        api_key: str,
        base_url: str,
        model: str,
        size: Optional[str],
        extra_body: Dict[str, Any],
        timeout_sec: float,
        image_urls: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        百炼原生 multimodal-generation：
        - 无参考图：文生图
        - 有 1-3 张 image：图生图/指令编辑（content: image* + text）
        文档：https://help.aliyun.com/zh/model-studio/qwen-image-edit-api
        """
        endpoint = self._dashscope_generation_url(base_url)
        parameters = dict(extra_body)
        if size and "size" not in parameters:
            parameters["size"] = size
        # DashScope 常用宽*高；兼容误填 2K
        if str(parameters.get("size") or "").upper() in ("1K", "2K", "4K"):
            parameters["size"] = {
                "1K": "1024*1024",
                "2K": "2048*2048",
                "4K": "2048*2048",
            }.get(str(parameters["size"]).upper(), "2048*2048")

        content: List[Dict[str, str]] = []
        for img in (image_urls or [])[:3]:
            content.append({"image": img})
        content.append({"text": prompt})

        payload: Dict[str, Any] = {
            "model": model,
            "input": {
                "messages": [
                    {"role": "user", "content": content},
                ]
            },
        }
        if parameters:
            payload["parameters"] = parameters

        response = requests.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=timeout_sec,
        )
        try:
            raw = response.json()
        except ValueError:
            raw = {"_text": response.text}

        if response.status_code >= 400:
            message = _format_api_error_message(response.status_code, raw, endpoint)
            chain.stop_error(message)
            return self._failure(message, raw if isinstance(raw, dict) else {})

        # DashScope 错误码也可能在 200 里
        if isinstance(raw, dict) and raw.get("code") and str(raw.get("code")) not in ("", "Success"):
            message = str(raw.get("message") or raw.get("code") or "DashScope 生图失败")
            chain.stop_error(message)
            return self._failure(message, raw)

        urls = self._extract_dashscope_image_urls(raw if isinstance(raw, dict) else {})
        if not urls:
            return self._failure("未返回图片 URL", raw if isinstance(raw, dict) else {})

        return {
            "success": True,
            "url": urls[0],
            "urls": urls,
            "b64Json": "",
            "rawResponse": raw if isinstance(raw, dict) else {},
            "errorMessage": "",
        }

    @staticmethod
    def _dashscope_generation_url(base_url: str) -> str:
        text = (base_url or "").strip().rstrip("/")
        lower = text.lower()
        if "multimodal-generation" in lower:
            return text
        # 允许填完整 generation 路径或仅 api/v1 根
        if lower.endswith("/api/v1"):
            return f"{text}/services/aigc/multimodal-generation/generation"
        if "/api/v1/" in lower:
            return f"{text.rstrip('/')}/services/aigc/multimodal-generation/generation"
        return f"{text}/api/v1/services/aigc/multimodal-generation/generation"

    @staticmethod
    def _extract_dashscope_image_urls(raw: Dict[str, Any]) -> List[str]:
        urls: List[str] = []
        output = raw.get("output") if isinstance(raw.get("output"), dict) else {}
        choices = output.get("choices") if isinstance(output, dict) else None
        if not isinstance(choices, list):
            return urls
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for item in content:
                if isinstance(item, dict) and item.get("image"):
                    urls.append(str(item["image"]))
        return urls

    def _failure(self, message: str, raw: Any = None) -> Dict[str, Any]:
        return {
            "success": False,
            "url": "",
            "urls": [],
            "b64Json": "",
            "rawResponse": raw if isinstance(raw, dict) else {},
            "errorMessage": message,
        }

    @staticmethod
    def _response_to_dict(response: Any) -> Dict[str, Any]:
        model_dump = getattr(response, "model_dump", None)
        if callable(model_dump):
            try:
                dumped = model_dump()
                return dumped if isinstance(dumped, dict) else {"value": dumped}
            except Exception:  # noqa: BLE001
                pass
        to_dict = getattr(response, "to_dict", None)
        if callable(to_dict):
            try:
                dumped = to_dict()
                return dumped if isinstance(dumped, dict) else {"value": dumped}
            except Exception:  # noqa: BLE001
                pass
        return {"repr": repr(response)}


def _apply_output_default(value: Any, default_value: Optional[str]) -> Any:
    if default_value is None:
        return value
    if value is None:
        return default_value
    if isinstance(value, str) and not value.strip():
        return default_value
    return value


def _unwrap_output_value(value: Any, data_type: DataType | None) -> Any:
    """documents.content 等路径可能解析为单元素列表，对外输出时取首条。"""
    if isinstance(value, list):
        if len(value) == 1:
            return value[0]
        if len(value) == 0 and data_type == DataType.STRING:
            return ""
    return value


def resolve_output_by_defs(
    chain: Chain,
    output_defs: List[Parameter],
    method_key: Optional[str] = None,
    *,
    from_request: bool = False,
) -> Dict[str, Any]:
    output: Dict[str, Any] = {}
    for output_def in output_defs:
        name = (output_def.name or "").strip()
        if not name and not output_def.children:
            continue
        if from_request:
            raw = _resolve_start_api_output_value(chain, output_def, method_key)
        else:
            raw = _resolve_chain_output_value(chain, output_def)
        if name:
            output[name] = _unwrap_output_value(raw, output_def.data_type)
    return output


def _normalize_code_result(result: Any, output_defs: List[Parameter]) -> Dict[str, Any]:
    if isinstance(result, dict):
        names = [(d.name or "").strip() for d in (output_defs or []) if (d.name or "").strip()]
        if names and not any(k in names for k in result.keys()):
            if len(names) == 1:
                return {names[0]: result}
        return result
    if output_defs:
        return {output_defs[0].name or "output": result}
    return {"output": result}


def _fill_loop_result(
    result: Dict[str, Any], output_defs: List[Parameter], execute_result: Dict[str, Any]
) -> None:
    for output_def in output_defs:
        if output_def.ref_type == RefType.REF:
            ref_key = output_def.ref or ""
            value = execute_result.get(ref_key)
            if ref_key:
                dot = ref_key.find(".")
                if dot >= 0:
                    value = execute_result.get(ref_key) or execute_result.get(ref_key[dot + 1 :])
            name = output_def.name or ""
            bucket = result.setdefault(name, [])
            if isinstance(bucket, list):
                bucket.append(value)
