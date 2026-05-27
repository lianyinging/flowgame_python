"""Qdrant API 请求/响应模型。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


class ApiResponse(BaseModel):
    code: int = 200
    msg: str = "success"
    data: Optional[Dict[str, Any]] = None


class CollectionCreateBody(BaseModel):
    collectionName: str = Field(..., min_length=1, description="集合名称")
    vectorSize: int = Field(default=512, ge=1, description="向量维度")
    distance: str = Field(default="Cosine", description="Cosine / Euclid / Dot")


class PointWriteBody(BaseModel):
    collectionName: str = Field(..., min_length=1)
    pointId: Optional[Union[str, int]] = Field(default=None, description="不传则自动生成 UUID")
    vector: Optional[List[float]] = Field(default=None, description="向量；与 text 二选一")
    text: Optional[str] = Field(default=None, description="文本；需配置 EMBEDDING_API_URL 自动向量化")
    payload: Optional[Dict[str, Any]] = Field(default=None, description="元数据")


class PointBatchDeleteBody(BaseModel):
    collectionName: str = Field(..., min_length=1)
    pointIds: List[Union[str, int]] = Field(..., min_length=1)


class PointSearchBody(BaseModel):
    collectionName: str = Field(..., min_length=1)
    vector: Optional[List[float]] = None
    text: Optional[str] = None
    limit: int = Field(default=10, ge=1, le=100)
    scoreThreshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    withPayload: bool = True
    withVector: bool = False


class QaBatchUploadBody(BaseModel):
    collectionName: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1, description="Q&A 格式文本内容")


class QaPointWriteBody(BaseModel):
    collectionName: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1)
    answer: str = Field(..., min_length=1)
    pointId: Optional[Union[str, int]] = None
