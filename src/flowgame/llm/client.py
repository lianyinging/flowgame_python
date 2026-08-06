"""统一大模型调用入口（OpenAI 兼容 Chat Completions）。

业务侧（模型调用节点、Team、机器人路由等）应走本模块，避免各处直接拼 HTTP/SDK。
本期不引入 LiteLLM，行为与原先直接调 DeepSeek/OpenAI 兼容接口一致。
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

import requests

logger = logging.getLogger("flowgame.llm")

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


def default_api_key() -> str:
    return os.getenv("DEEPSEEK_API_KEY", "").strip()


def default_base_url() -> str:
    return (
        os.getenv("DEEPSEEK_BASE_URL", "").strip()
        or DEFAULT_BASE_URL
    )


def default_model() -> str:
    return (
        os.getenv("DEEPSEEK_MODEL", "").strip()
        or DEFAULT_MODEL
    )


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


def extract_chat_content(payload: Any) -> str:
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

    primary = candidates[0]
    if primary.lstrip().startswith("{") and primary.rstrip().endswith("}"):
        return primary

    for text in candidates:
        extracted = _extract_trailing_json_object(text)
        if extracted:
            return extracted
    return primary


def _extract_trailing_json_object(text: str) -> str:
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


def format_api_error_message(status_code: int, payload: Any, request_url: str = "") -> str:
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


@dataclass
class LlmChatResult:
    """统一聊天结果。"""

    content: str = ""
    raw: Any = None
    error: str = ""
    ok: bool = True
    status_code: int = 200
    request_url: str = ""

    def to_legacy_dict(self) -> Dict[str, Any]:
        """兼容 DeepSeekLlmClient.chat 旧返回：成功 {content} / 失败 {error}。"""
        if self.ok:
            return {"content": self.content}
        return {"error": self.error or "LLM 调用失败"}


@dataclass
class LlmClient:
    """项目内大模型统一入口（Chat Completions）。"""

    api_key: str = ""
    base_url: str = ""
    model: str = ""
    provider: str = ""
    timeout_sec: float = 60.0
    auth_type: str = "bearer"
    auth_header_name: str = "Authorization"
    extra_headers: Dict[str, str] = field(default_factory=dict)

    def resolved_api_key(self) -> str:
        return (self.api_key or "").strip() or default_api_key()

    def resolved_base_url(self) -> str:
        from src.flowgame.llm.providers import resolve_provider_base_url

        if (self.provider or "").strip():
            return resolve_provider_base_url(self.provider)
        return (self.base_url or "").strip() or default_base_url()

    def resolved_model(self) -> str:
        from src.flowgame.llm.providers import resolve_provider_default_model

        if (self.model or "").strip():
            return self.model.strip()
        if (self.provider or "").strip():
            return resolve_provider_default_model(self.provider)
        return default_model()

    def chat(
        self,
        messages: List[Dict[str, Any]],
        *,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        provider: Optional[str] = None,
        temperature: float = 0.7,
        top_p: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_format: Optional[Union[str, Dict[str, Any]]] = None,
        timeout_sec: Optional[float] = None,
        auth_type: Optional[str] = None,
        auth_header_name: Optional[str] = None,
        extra_headers: Optional[Dict[str, Any]] = None,
        extra_body: Optional[Dict[str, Any]] = None,
    ) -> LlmChatResult:
        """发起一次 Chat Completions。失败时 ok=False，不抛异常（节点可自行 stop_error）。"""
        from src.flowgame.llm.providers import (
            normalize_provider_id,
            resolve_provider_base_url,
            resolve_provider_default_model,
        )

        key = (api_key if api_key is not None else self.api_key) or ""
        key = key.strip() or default_api_key()

        use_provider = provider if provider is not None else self.provider
        use_provider = (use_provider or "").strip()

        raw_base = (base_url if base_url is not None else self.base_url) or ""
        raw_base = raw_base.strip()
        # 有厂家时强制用厂家地址，忽略外部传入的自定义 URL
        if use_provider:
            use_provider = normalize_provider_id(use_provider)
            raw_base = resolve_provider_base_url(use_provider)
        elif not raw_base:
            raw_base = default_base_url()

        use_model = (model if model is not None else self.model) or ""
        use_model = use_model.strip()
        if not use_model:
            use_model = (
                resolve_provider_default_model(use_provider)
                if use_provider
                else default_model()
            )

        timeout = float(timeout_sec if timeout_sec is not None else self.timeout_sec)
        timeout = max(1.0, timeout)
        use_auth = (auth_type if auth_type is not None else self.auth_type) or "bearer"
        header_name = (
            auth_header_name
            if auth_header_name is not None
            else self.auth_header_name
        ) or "Authorization"

        url = normalize_chat_completions_url(raw_base)
        body: Dict[str, Any] = {
            "model": use_model,
            "messages": messages,
            "temperature": temperature,
        }
        if top_p is not None:
            body["top_p"] = top_p
        if max_tokens is not None and int(max_tokens) > 0:
            body["max_tokens"] = int(max_tokens)
        if response_format == "json_object":
            body["response_format"] = {"type": "json_object"}
        elif isinstance(response_format, dict):
            body["response_format"] = response_format
        if extra_body:
            body.update(extra_body)

        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if key:
            if str(use_auth).lower() == "header":
                headers[str(header_name).strip() or "Authorization"] = key
            else:
                headers["Authorization"] = f"Bearer {key}"
        for src in (self.extra_headers, extra_headers or {}):
            for k, v in (src or {}).items():
                if v is not None:
                    headers[str(k)] = str(v)

        try:
            response = requests.post(url, json=body, headers=headers, timeout=timeout)
        except requests.RequestException as exc:
            logger.error("LlmClient request failed: %s", exc)
            return LlmChatResult(
                ok=False,
                error=str(exc),
                raw={"_text": str(exc)},
                status_code=0,
                request_url=url,
            )

        try:
            raw: Any = response.json()
        except ValueError:
            raw = {"_text": response.text}

        if response.status_code >= 400:
            message = format_api_error_message(response.status_code, raw, url)
            return LlmChatResult(
                ok=False,
                error=message,
                raw=raw,
                status_code=response.status_code,
                request_url=url,
            )

        content = extract_chat_content(raw)
        return LlmChatResult(
            ok=True,
            content=content,
            raw=raw,
            status_code=response.status_code,
            request_url=url,
        )


def chat_completion(
    messages: List[Dict[str, Any]],
    **kwargs: Any,
) -> LlmChatResult:
    """模块级便捷方法：等价于默认 LlmClient().chat(...)。"""
    return LlmClient().chat(messages, **kwargs)
