"""FlowGame Redis 客户端（仅依赖 redis 包与 flowgame.settings）。"""
from __future__ import annotations

import json
import logging
from typing import Any, List, Optional

from src.flowgame.settings import get_flowgame_settings

logger = logging.getLogger(__name__)

try:
    import redis
    from redis.connection import ConnectionPool

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    redis = None  # type: ignore
    ConnectionPool = None  # type: ignore


class FlowgameRedisClient:
    _instance: Optional["FlowgameRedisClient"] = None

    def __new__(cls) -> "FlowgameRedisClient":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self._client = None
        self._pool = None
        self._connected = False

    def _connect(self) -> None:
        if not REDIS_AVAILABLE:
            self._connected = False
            return
        if self._client is not None:
            return

        cfg = get_flowgame_settings()
        try:
            if not (cfg.redis_host or "").strip():
                from src.config.config import init_redis_settings_from_nacos

                init_redis_settings_from_nacos()
                from src.flowgame.settings import clear_flowgame_settings_cache

                clear_flowgame_settings_cache()
                cfg = get_flowgame_settings()
        except Exception:
            pass

        pool_kwargs = {
            "host": cfg.redis_host,
            "port": cfg.redis_port,
            "db": cfg.redis_db,
            "password": cfg.redis_password,
            "decode_responses": cfg.redis_decode_responses,
            "socket_connect_timeout": cfg.redis_socket_connect_timeout,
            "socket_timeout": cfg.redis_socket_timeout,
            "max_connections": cfg.redis_max_connections,
            "retry_on_timeout": True,
        }
        self._pool = ConnectionPool(**pool_kwargs)
        self._client = redis.Redis(connection_pool=self._pool)
        self._client.ping()
        self._connected = True
        logger.info("FlowGame Redis 已连接 %s:%s", cfg.redis_host, cfg.redis_port)

    def _ensure_connected(self) -> bool:
        if not self._connected or self._client is None:
            self._connect()
        return self._connected

    def ping(self) -> bool:
        if not self._ensure_connected():
            return False
        try:
            return bool(self._client.ping())
        except Exception as exc:
            logger.error("Redis ping 失败: %s", exc)
            self._connected = False
            return False

    def get(self, key: str, default: Any = None) -> Any:
        if not self._ensure_connected():
            return default
        try:
            value = self._client.get(key)
            return default if value is None else value
        except Exception as exc:
            logger.error("Redis get 失败 [%s]: %s", key, exc)
            return default

    def set(
        self,
        key: str,
        value: Any,
        ex: Optional[int] = None,
        nx: bool = False,
        xx: bool = False,
    ) -> bool:
        if not self._ensure_connected():
            return False
        try:
            kwargs: dict = {}
            if ex is not None:
                kwargs["ex"] = ex
            if nx:
                kwargs["nx"] = True
            if xx:
                kwargs["xx"] = True
            return bool(self._client.set(key, value, **kwargs))
        except Exception as exc:
            logger.error("Redis set 失败 [%s]: %s", key, exc)
            return False

    def delete(self, *keys: str) -> int:
        if not self._ensure_connected():
            return 0
        try:
            return int(self._client.delete(*keys))
        except Exception as exc:
            logger.error("Redis delete 失败: %s", exc)
            return 0

    def exists(self, *keys: str) -> int:
        if not self._ensure_connected():
            return 0
        try:
            return int(self._client.exists(*keys))
        except Exception as exc:
            logger.error("Redis exists 失败: %s", exc)
            return 0

    def expire(self, key: str, seconds: int) -> bool:
        if not self._ensure_connected():
            return False
        try:
            return bool(self._client.expire(key, seconds))
        except Exception as exc:
            logger.error("Redis expire 失败 [%s]: %s", key, exc)
            return False

    def ttl(self, key: str) -> int:
        if not self._ensure_connected():
            return -2
        try:
            return int(self._client.ttl(key))
        except Exception as exc:
            logger.error("Redis ttl 失败 [%s]: %s", key, exc)
            return -2

    def type(self, key: str) -> Optional[str]:
        if not self._ensure_connected():
            return None
        try:
            return self._client.type(key)
        except Exception as exc:
            logger.error("Redis type 失败 [%s]: %s", key, exc)
            return None

    def rpush(self, key: str, value: str) -> int:
        if not self._ensure_connected():
            return 0
        try:
            return int(self._client.rpush(key, value))
        except Exception as exc:
            logger.error("Redis rpush 失败 [%s]: %s", key, exc)
            return 0

    def lpush(self, key: str, value: str) -> int:
        if not self._ensure_connected():
            return 0
        try:
            return int(self._client.lpush(key, value))
        except Exception as exc:
            logger.error("Redis lpush 失败 [%s]: %s", key, exc)
            return 0

    def brpop(self, key: str, timeout: int = 1) -> Optional[Any]:
        """阻塞从列表右侧弹出；超时返回 None。"""
        if not self._ensure_connected():
            return None
        try:
            item = self._client.brpop(key, timeout=max(1, int(timeout)))
            return item
        except Exception as exc:
            logger.error("Redis brpop 失败 [%s]: %s", key, exc)
            return None

    def blpop(self, key: str, timeout: int = 1) -> Optional[Any]:
        """阻塞从列表左侧弹出；超时返回 None。"""
        if not self._ensure_connected():
            return None
        try:
            item = self._client.blpop(key, timeout=max(1, int(timeout)))
            return item
        except Exception as exc:
            logger.error("Redis blpop 失败 [%s]: %s", key, exc)
            return None

    def llen(self, key: str) -> int:
        if not self._ensure_connected():
            return 0
        try:
            return int(self._client.llen(key))
        except Exception as exc:
            logger.error("Redis llen 失败 [%s]: %s", key, exc)
            return 0

    def ltrim(self, key: str, start: int, end: int) -> bool:
        if not self._ensure_connected():
            return False
        try:
            return bool(self._client.ltrim(key, start, end))
        except Exception as exc:
            logger.error("Redis ltrim 失败 [%s]: %s", key, exc)
            return False

    def lrange(self, key: str, start: int = 0, end: int = -1) -> List[Any]:
        if not self._ensure_connected():
            return []
        try:
            return list(self._client.lrange(key, start, end))
        except Exception as exc:
            logger.error("Redis lrange 失败 [%s]: %s", key, exc)
            return []

    def hgetall(self, key: str) -> dict:
        if not self._ensure_connected():
            return {}
        try:
            return dict(self._client.hgetall(key))
        except Exception as exc:
            logger.error("Redis hgetall 失败 [%s]: %s", key, exc)
            return {}

    def get_json(self, key: str, default: Any = None) -> Any:
        if not self._ensure_connected():
            return default
        try:
            key_type = self.type(key)
            if key_type == "none":
                return default
            if key_type == "list":
                items = self.lrange(key, 0, -1)
                result = []
                for item in items:
                    try:
                        result.append(json.loads(item) if isinstance(item, str) else item)
                    except json.JSONDecodeError:
                        result.append(item)
                return result
            if key_type == "string":
                value = self.get(key)
                if value is None:
                    return default
                if isinstance(value, (dict, list)):
                    return value
                if isinstance(value, str):
                    return json.loads(value)
                return value
            if key_type == "hash":
                return self.hgetall(key)
            return default
        except Exception as exc:
            logger.error("Redis get_json 失败 [%s]: %s", key, exc)
            return default

    def set_json(
        self,
        key: str,
        value: Any,
        ex: Optional[int] = None,
        nx: bool = False,
        xx: bool = False,
    ) -> bool:
        try:
            payload = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            return self.set(key, payload, ex=ex, nx=nx, xx=xx)
        except Exception as exc:
            logger.error("Redis set_json 失败 [%s]: %s", key, exc)
            return False


redis_client = FlowgameRedisClient()
