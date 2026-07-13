"""HACR（混合自适应分块）配置，仅 Markdown 上传可选启用。"""
from __future__ import annotations

import os

CHUNKING_VERSION_LLM_HACR = "v2_llm_hacr"
CHUNKING_VERSION_LEGACY = "v1"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = int(str(raw).strip())
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(str(raw).strip())
    except ValueError:
        return default


def is_hacr_server_allowed() -> bool:
    """服务端总开关：false 时即使前端请求 HACR 也拒绝。"""
    return _env_bool("FLOWGAME_HACR_ENABLED", True)


def is_hacr_enabled() -> bool:
    """兼容旧名，同 is_hacr_server_allowed。"""
    return is_hacr_server_allowed()


def is_markdown_filename(filename: str) -> bool:
    ext = (filename or "").lower().strip()
    dot = ext.rfind(".")
    suffix = ext[dot:] if dot >= 0 else ""
    return suffix in (".md", ".markdown")


def is_llm_fallback_enabled() -> bool:
    return _env_bool("FLOWGAME_HACR_LLM_FALLBACK", True)


def llm_temperature() -> float:
    return _env_float("FLOWGAME_HACR_LLM_TEMPERATURE", 0.2)


def children_min() -> int:
    return _env_int("FLOWGAME_HACR_CHILDREN_MIN", 3, minimum=1, maximum=10)


def children_max() -> int:
    return _env_int("FLOWGAME_HACR_CHILDREN_MAX", 6, minimum=1, maximum=12)


def max_document_chars() -> int:
    """单次送入 LLM 的文档最大字符数。"""
    return _env_int("FLOWGAME_HACR_MAX_DOCUMENT_CHARS", 12000, minimum=2000, maximum=60000)


def max_themes() -> int:
    return _env_int("FLOWGAME_HACR_MAX_THEMES", 30, minimum=3, maximum=100)


def max_section_chars() -> int:
    return _env_int("FLOWGAME_HACR_MAX_SECTION_CHARS", 4000, minimum=500, maximum=12000)


def max_parent_text_chars() -> int:
    return _env_int("FLOWGAME_HACR_MAX_PARENT_TEXT_CHARS", 3000, minimum=500, maximum=8000)


def llm_model_override() -> str:
    return os.getenv("FLOWGAME_HACR_LLM_MODEL", "").strip()


def is_llm_configured() -> bool:
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    return bool(key) and key != "not-configured"
