from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


class ApiResponse(BaseModel):
    code: int = 200
    msg: str = "success"
    data: Optional[Dict[str, Any]] = None


class RedisWriteBody(BaseModel):
    redisKey: str = Field(..., min_length=1, description="Redis 键名")
    value: Union[str, int, float, bool, dict, list, None] = Field(
        default=None, description="要写入的值，支持 JSON 对象/数组"
    )
    expire: Optional[int] = Field(default=None, ge=1, description="过期时间（秒）")
