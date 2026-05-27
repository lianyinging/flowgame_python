"""FlowGame Qdrant 客户端（仅依赖 qdrant-client）。"""
from __future__ import annotations

import logging
from typing import Optional

from qdrant_client import QdrantClient

from src.flowgame.settings import get_flowgame_settings

logger = logging.getLogger(__name__)

_client: Optional[QdrantClient] = None


def get_qdrant_client() -> QdrantClient:
    global _client
    if _client is not None:
        return _client

    cfg = get_flowgame_settings()
    _client = QdrantClient(
        host=cfg.qdrant_host,
        port=cfg.qdrant_port,
        timeout=cfg.qdrant_timeout,
        prefer_grpc=False,
    )
    logger.info("FlowGame Qdrant 客户端已连接 %s:%s", cfg.qdrant_host, cfg.qdrant_port)
    return _client


def ensure_qdrant_available() -> QdrantClient:
    client = get_qdrant_client()
    try:
        client.get_collections()
    except Exception as exc:
        raise RuntimeError(f"Qdrant 不可用 ({get_flowgame_settings().qdrant_host}): {exc}") from exc
    return client
