"""将前端 configureFlowGameClient 中的前缀通过请求头注入当前请求上下文。"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from src.flowgame.key_prefix import bind_request_key_prefixes, clear_request_key_prefixes

HEADER_REDIS_KEY_PREFIX = "x-flowgame-redis-key-prefix"
HEADER_QDRANT_KB_PREFIX = "x-flowgame-qdrant-kb-prefix"


class FlowgameKeyPrefixMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        bind_request_key_prefixes(
            redis_key_prefix=request.headers.get(HEADER_REDIS_KEY_PREFIX),
            qdrant_kb_prefix=request.headers.get(HEADER_QDRANT_KB_PREFIX),
        )
        try:
            return await call_next(request)
        finally:
            clear_request_key_prefixes()
