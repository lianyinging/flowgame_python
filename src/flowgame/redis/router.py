"""FlowGame Redis REST API（前端传 redisKey）。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from src.flowgame.redis import service
from src.flowgame.redis.schemas import ApiResponse, RedisWriteBody

redis_router = APIRouter()


def _ok(msg: str, data: Optional[dict] = None) -> ApiResponse:
    return ApiResponse(code=200, msg=msg, data=data)


@redis_router.get("", response_model=ApiResponse, summary="查询 Redis 键")
async def get_redis(redisKey: str = Query(..., description="Redis 键名")):
    service.ensure_redis()
    data = service.read_entry(redisKey)
    if not data["exists"]:
        return _ok("键不存在", data)
    return _ok("查询成功", data)


@redis_router.post("", response_model=ApiResponse, summary="新增 Redis 键")
async def create_redis(body: RedisWriteBody):
    service.ensure_redis()
    return _ok("新增成功", service.create_entry(body))


@redis_router.put("", response_model=ApiResponse, summary="更新 Redis 键")
async def update_redis(body: RedisWriteBody):
    service.ensure_redis()
    return _ok("更新成功", service.update_entry(body))


@redis_router.delete("", response_model=ApiResponse, summary="删除 Redis 键")
async def delete_redis(redisKey: str = Query(..., description="Redis 键名")):
    service.ensure_redis()
    data = service.delete_entry(redisKey)
    msg = "删除成功" if data.get("deleted") else "键不存在或已删除"
    return _ok(msg, data)
