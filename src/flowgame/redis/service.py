"""FlowGame Redis 增删改查。"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import HTTPException

from src.flowgame.redis.client import redis_client
from src.flowgame.redis.schemas import RedisWriteBody


def ensure_redis() -> None:
    if not redis_client.ping():
        raise HTTPException(status_code=503, detail="Redis 不可用，请检查连接与配置")


def normalize_key(redis_key: str) -> str:
    key = (redis_key or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="redisKey 不能为空")
    return key


def read_entry(redis_key: str) -> Dict[str, Any]:
    key = normalize_key(redis_key)
    if redis_client.exists(key) <= 0:
        return {
            "redisKey": key,
            "exists": False,
            "value": None,
            "type": "none",
            "ttl": -2,
        }
    return {
        "redisKey": key,
        "exists": True,
        "value": redis_client.get_json(key),
        "type": redis_client.type(key) or "none",
        "ttl": redis_client.ttl(key),
    }


def create_entry(body: RedisWriteBody) -> Dict[str, Any]:
    key = normalize_key(body.redisKey)
    if redis_client.exists(key):
        raise HTTPException(status_code=409, detail=f"键已存在: {key}")
    if not redis_client.set_json(key, body.value, ex=body.expire, nx=True):
        raise HTTPException(status_code=500, detail="写入 Redis 失败")
    return read_entry(key)


def update_entry(body: RedisWriteBody) -> Dict[str, Any]:
    key = normalize_key(body.redisKey)
    if not redis_client.exists(key):
        raise HTTPException(status_code=404, detail=f"键不存在: {key}")
    stored = redis_client.set_json(key, body.value, ex=body.expire, xx=True)
    if not stored:
        stored = redis_client.set_json(key, body.value, ex=body.expire)
    if not stored:
        raise HTTPException(status_code=500, detail="更新 Redis 失败")
    if body.expire is not None:
        redis_client.expire(key, body.expire)
    return read_entry(key)


def delete_entry(redis_key: str) -> Dict[str, Any]:
    key = normalize_key(redis_key)
    deleted = redis_client.delete(key)
    if deleted <= 0:
        return {"redisKey": key, "deleted": 0}
    return {"redisKey": key, "deleted": deleted}
