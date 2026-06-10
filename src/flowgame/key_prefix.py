"""Redis / Qdrant 命名空间前缀（环境变量 + 请求头可选，用于多项目隔离共享实例）。"""
from __future__ import annotations

import os
from contextvars import ContextVar
from functools import lru_cache
from typing import Optional

DEFAULT_REDIS_KEY_PREFIX = "flow_game:"
DEFAULT_QDRANT_KB_PREFIX = "flowgame_"

_REQUEST_REDIS_KEY_PREFIX: ContextVar[Optional[str]] = ContextVar(
    "flowgame_request_redis_key_prefix", default=None
)
_REQUEST_QDRANT_KB_PREFIX: ContextVar[Optional[str]] = ContextVar(
    "flowgame_request_qdrant_kb_prefix", default=None
)


def normalize_redis_key_prefix(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return DEFAULT_REDIS_KEY_PREFIX
    return value if value.endswith(":") else f"{value}:"


def normalize_qdrant_kb_prefix(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return DEFAULT_QDRANT_KB_PREFIX
    return value if value.endswith("_") else f"{value}_"


@lru_cache(maxsize=1)
def _env_redis_key_prefix() -> str:
    return normalize_redis_key_prefix(os.getenv("FLOWGAME_REDIS_KEY_PREFIX", ""))


@lru_cache(maxsize=1)
def _env_qdrant_kb_prefix() -> str:
    return normalize_qdrant_kb_prefix(os.getenv("FLOWGAME_QDRANT_KB_PREFIX", ""))


def bind_request_key_prefixes(
    redis_key_prefix: Optional[str] = None,
    qdrant_kb_prefix: Optional[str] = None,
) -> None:
    if redis_key_prefix is not None and str(redis_key_prefix).strip():
        _REQUEST_REDIS_KEY_PREFIX.set(normalize_redis_key_prefix(str(redis_key_prefix)))
    if qdrant_kb_prefix is not None and str(qdrant_kb_prefix).strip():
        _REQUEST_QDRANT_KB_PREFIX.set(normalize_qdrant_kb_prefix(str(qdrant_kb_prefix)))


def clear_request_key_prefixes() -> None:
    _REQUEST_REDIS_KEY_PREFIX.set(None)
    _REQUEST_QDRANT_KB_PREFIX.set(None)


def get_redis_key_prefix() -> str:
    override = _REQUEST_REDIS_KEY_PREFIX.get()
    if override:
        return override
    return _env_redis_key_prefix()


def get_qdrant_kb_prefix() -> str:
    override = _REQUEST_QDRANT_KB_PREFIX.get()
    if override:
        return override
    return _env_qdrant_kb_prefix()


def get_flow_list_redis_prefix() -> str:
    return f"{get_redis_key_prefix()}flow_list:"


def get_flow_context_redis_prefix() -> str:
    return f"{get_redis_key_prefix()}flow_context:"


def get_kb_docs_redis_prefix() -> str:
    return f"{get_redis_key_prefix()}kb:docs:"


def get_kb_doc_points_redis_prefix() -> str:
    return f"{get_redis_key_prefix()}kb:doc_points:"


def clear_key_prefix_cache() -> None:
    _env_redis_key_prefix.cache_clear()
    _env_qdrant_kb_prefix.cache_clear()
