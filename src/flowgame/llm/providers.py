"""预置模型厂家（不允许自定义 URL）。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class LlmProviderDef:
    id: str
    label: str
    base_url: str
    default_model: str
    models: tuple[str, ...] = ()


# base_url 为 OpenAI 兼容根地址（可无 /chat/completions）；由 LlmClient 补全
LLM_PROVIDERS: Dict[str, LlmProviderDef] = {
    "deepseek": LlmProviderDef(
        id="deepseek",
        label="DeepSeek",
        base_url="https://api.deepseek.com",
        default_model="deepseek-v4-flash",
        models=(
            "deepseek-v4-flash",
            "deepseek-chat",
            "deepseek-reasoner",
        ),
    ),
    "openai": LlmProviderDef(
        id="openai",
        label="OpenAI",
        base_url="https://api.openai.com",
        default_model="gpt-4o-mini",
        models=("gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "o4-mini"),
    ),
    "qwen": LlmProviderDef(
        id="qwen",
        label="通义千问",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        default_model="qwen-plus",
        models=("qwen-plus", "qwen-turbo", "qwen-max", "qwen-long"),
    ),
    "moonshot": LlmProviderDef(
        id="moonshot",
        label="月之暗面 Kimi",
        base_url="https://api.moonshot.cn",
        default_model="moonshot-v1-8k",
        models=("moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"),
    ),
    "zhipu": LlmProviderDef(
        id="zhipu",
        label="智谱 GLM",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        default_model="glm-4-flash",
        models=("glm-4-flash", "glm-4-air", "glm-4-plus"),
    ),
}

DEFAULT_PROVIDER_ID = "deepseek"


def list_providers() -> List[Dict[str, Any]]:
    return [
        {
            "value": p.id,
            "label": p.label,
            "defaultModel": p.default_model,
            "models": list(p.models),
            "baseUrl": p.base_url,
        }
        for p in LLM_PROVIDERS.values()
    ]


def get_provider(provider_id: str) -> Optional[LlmProviderDef]:
    key = (provider_id or "").strip().lower()
    return LLM_PROVIDERS.get(key)


def resolve_provider_base_url(provider_id: str) -> str:
    p = get_provider(provider_id) or LLM_PROVIDERS[DEFAULT_PROVIDER_ID]
    return p.base_url


def resolve_provider_default_model(provider_id: str) -> str:
    p = get_provider(provider_id) or LLM_PROVIDERS[DEFAULT_PROVIDER_ID]
    return p.default_model


def infer_provider_from_url(url: str) -> str:
    """旧节点 modelApiUrl → 厂家（无法识别时默认 DeepSeek）。"""
    text = (url or "").strip().lower()
    if not text:
        return DEFAULT_PROVIDER_ID
    if "deepseek" in text:
        return "deepseek"
    if "openai.com" in text:
        return "openai"
    if "dashscope" in text or "aliyuncs.com" in text:
        return "qwen"
    if "moonshot" in text:
        return "moonshot"
    if "bigmodel" in text or "zhipu" in text:
        return "zhipu"
    return DEFAULT_PROVIDER_ID


def normalize_provider_id(raw: Any, *, legacy_url: str = "") -> str:
    text = str(raw or "").strip().lower()
    if text in LLM_PROVIDERS:
        return text
    # 别名
    aliases = {
        "通义": "qwen",
        "tongyi": "qwen",
        "dashscope": "qwen",
        "kimi": "moonshot",
        "glm": "zhipu",
        "智谱": "zhipu",
    }
    if text in aliases:
        return aliases[text]
    if legacy_url:
        return infer_provider_from_url(legacy_url)
    return DEFAULT_PROVIDER_ID
