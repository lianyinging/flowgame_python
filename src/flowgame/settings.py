"""
FlowGame 模块配置（独立部署：仅环境变量，不依赖 smartAi 主项目）。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional


@dataclass(frozen=True)
class FlowgameSettings:
    qdrant_host: str = "127.0.0.1"
    qdrant_port: int = 6333
    qdrant_timeout: int = 30
    embedding_api_url: str = ""
    embedding_api_timeout: int = 30
    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: Optional[str] = None
    redis_decode_responses: bool = True
    redis_socket_connect_timeout: int = 5
    redis_socket_timeout: int = 5
    redis_max_connections: int = 50
    mysql_host: str = ""
    mysql_port: int = 3306
    mysql_user: str = ""
    mysql_password: Optional[str] = None
    mysql_database: str = ""
    mysql_charset: str = "utf8mb4"


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    return int(raw)


@lru_cache(maxsize=1)
def get_flowgame_settings() -> FlowgameSettings:
    return FlowgameSettings(
        qdrant_host=os.getenv("QDRANT_HOST", "127.0.0.1").strip(),
        qdrant_port=_env_int("QDRANT_PORT", 6333),
        qdrant_timeout=_env_int("QDRANT_TIMEOUT", 30),
        embedding_api_url=os.getenv("EMBEDDING_API_URL", "").strip(),
        embedding_api_timeout=_env_int("EMBEDDING_API_TIMEOUT", 30),
        redis_host=os.getenv("REDIS_HOST", "127.0.0.1").strip(),
        redis_port=_env_int("REDIS_PORT", 6379),
        redis_db=_env_int("REDIS_DB", 0),
        redis_password=os.getenv("REDIS_PASSWORD") or None,
        redis_decode_responses=os.getenv("REDIS_DECODE_RESPONSES", "true").lower() == "true",
        redis_socket_connect_timeout=_env_int("REDIS_CONNECT_TIMEOUT", 5),
        redis_socket_timeout=_env_int("REDIS_SOCKET_TIMEOUT", 5),
        redis_max_connections=_env_int("REDIS_MAX_CONNECTIONS", 50),
        mysql_host=os.getenv("MYSQL_HOST", "").strip(),
        mysql_port=_env_int("MYSQL_PORT", 3306),
        mysql_user=os.getenv("MYSQL_USER", "").strip(),
        mysql_password=os.getenv("MYSQL_PASSWORD") or None,
        mysql_database=os.getenv("MYSQL_DATABASE", "").strip(),
        mysql_charset=os.getenv("MYSQL_CHARSET", "utf8mb4").strip() or "utf8mb4",
    )
