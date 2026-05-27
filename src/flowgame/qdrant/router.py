"""FlowGame Qdrant REST API。"""
from __future__ import annotations

from typing import Optional, Union

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from src.flowgame.qdrant import service
from src.flowgame.qdrant.embedding import (
    EmbeddingNotConfiguredError,
    get_default_vector_size,
    get_embedding_mode,
    is_embedding_enabled,
)
from src.flowgame.qdrant.embedding_config import resolve_local_model_path
from src.flowgame.qdrant.schemas import (
    ApiResponse,
    CollectionCreateBody,
    PointBatchDeleteBody,
    PointSearchBody,
    PointWriteBody,
    QaBatchUploadBody,
    QaPointWriteBody,
)

qdrant_router = APIRouter()


def _ok(msg: str, data: Optional[dict] = None) -> ApiResponse:
    return ApiResponse(code=200, msg=msg, data=data)


def _handle(exc: Exception) -> HTTPException:
    if isinstance(exc, service.QdrantServiceError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, EmbeddingNotConfiguredError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, RuntimeError):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


@qdrant_router.get("/embedding/status", response_model=ApiResponse, summary="Embedding 配置状态")
async def api_embedding_status():
    try:
        return _ok(
            "查询成功",
            {
                "enabled": is_embedding_enabled(),
                "mode": get_embedding_mode(),
                "localModelPath": resolve_local_model_path(),
                "defaultVectorSize": get_default_vector_size(),
            },
        )
    except Exception as exc:
        raise _handle(exc) from exc


@qdrant_router.get("/collections", response_model=ApiResponse, summary="列出所有集合")
async def api_list_collections():
    try:
        return _ok("查询成功", service.list_collections())
    except Exception as exc:
        raise _handle(exc) from exc


@qdrant_router.get("/collections/detail", response_model=ApiResponse, summary="查询集合详情")
async def api_get_collection(
    collectionName: str = Query(..., description="集合名称"),
):
    try:
        return _ok("查询成功", service.get_collection(collectionName))
    except Exception as exc:
        raise _handle(exc) from exc


@qdrant_router.post("/collections", response_model=ApiResponse, summary="创建集合")
async def api_create_collection(body: CollectionCreateBody):
    try:
        return _ok("创建成功", service.create_collection(body))
    except Exception as exc:
        raise _handle(exc) from exc


@qdrant_router.post("/collections/kb-pair", response_model=ApiResponse, summary="创建知识库（自动创建 base_qa + base_doc）")
async def api_create_kb_pair(body: CollectionCreateBody):
    try:
        return _ok("创建成功", service.create_kb_pair(body))
    except Exception as exc:
        raise _handle(exc) from exc


@qdrant_router.get("/collections/kb-bases", response_model=ApiResponse, summary="列出知识库（仅 flowgame_ 前缀，聚合 _qa / _doc）")
async def api_list_kb_bases():
    try:
        return _ok("查询成功", service.list_kb_bases())
    except Exception as exc:
        raise _handle(exc) from exc


@qdrant_router.get("/collections/flowgame-kb", response_model=ApiResponse, summary="列出 flowgame_ 前缀的 Q&A/文档 Collection")
async def api_list_flowgame_kb_collections():
    try:
        return _ok("查询成功", service.list_flowgame_kb_collections())
    except Exception as exc:
        raise _handle(exc) from exc


@qdrant_router.delete("/collections/kb-pair", response_model=ApiResponse, summary="删除知识库（含 _qa、_doc 及文档索引）")
async def api_delete_kb_pair(
    baseName: str = Query(..., description="知识库 base 名称（不含 _qa/_doc 后缀）"),
):
    try:
        return _ok("删除成功", service.delete_kb_pair(baseName))
    except Exception as exc:
        raise _handle(exc) from exc


@qdrant_router.delete("/collections", response_model=ApiResponse, summary="删除集合")
async def api_delete_collection(
    collectionName: str = Query(..., description="集合名称"),
):
    try:
        return _ok("删除成功", service.delete_collection(collectionName))
    except Exception as exc:
        raise _handle(exc) from exc


@qdrant_router.get("/points", response_model=ApiResponse, summary="查询单个向量点")
async def api_get_point(
    collectionName: str = Query(..., description="集合名称"),
    pointId: str = Query(..., description="点 ID"),
):
    try:
        pid: Union[str, int] = int(pointId) if pointId.isdigit() else pointId
        return _ok("查询成功", service.get_point(collectionName, pid))
    except Exception as exc:
        raise _handle(exc) from exc


@qdrant_router.get("/points/scroll", response_model=ApiResponse, summary="分页遍历向量点")
async def api_scroll_points(
    collectionName: str = Query(..., description="集合名称"),
    limit: int = Query(20, ge=1, le=200),
    offset: Optional[str] = Query(None, description="上一页返回的 nextOffset"),
    withVector: bool = Query(False, description="是否返回向量"),
):
    try:
        parsed_offset: Optional[Union[str, int]] = offset
        if offset is not None and offset.isdigit():
            parsed_offset = int(offset)
        return _ok(
            "查询成功",
            service.scroll_points(collectionName, limit=limit, offset=parsed_offset, with_vector=withVector),
        )
    except Exception as exc:
        raise _handle(exc) from exc


@qdrant_router.post("/points", response_model=ApiResponse, summary="新增/写入向量点")
async def api_create_point(body: PointWriteBody):
    """写入向量点（upsert，同 pointId 会覆盖）。"""
    try:
        return _ok("写入成功", service.upsert_point(body))
    except Exception as exc:
        raise _handle(exc) from exc


@qdrant_router.put("/points", response_model=ApiResponse, summary="更新向量点")
async def api_update_point(body: PointWriteBody):
    try:
        return _ok("更新成功", service.upsert_point(body))
    except Exception as exc:
        raise _handle(exc) from exc


@qdrant_router.delete("/points", response_model=ApiResponse, summary="批量删除向量点")
async def api_delete_points(body: PointBatchDeleteBody):
    try:
        return _ok("删除成功", service.delete_points(body))
    except Exception as exc:
        raise _handle(exc) from exc


@qdrant_router.delete("/points/single", response_model=ApiResponse, summary="删除单个向量点")
async def api_delete_point(
    collectionName: str = Query(..., description="集合名称"),
    pointId: str = Query(..., description="点 ID"),
):
    try:
        pid: Union[str, int] = int(pointId) if pointId.isdigit() else pointId
        body = PointBatchDeleteBody(collectionName=collectionName, pointIds=[pid])
        return _ok("删除成功", service.delete_points(body))
    except Exception as exc:
        raise _handle(exc) from exc


@qdrant_router.post("/search", response_model=ApiResponse, summary="向量相似度检索")
async def api_search(body: PointSearchBody):
    try:
        return _ok("检索成功", service.search_points(body))
    except Exception as exc:
        raise _handle(exc) from exc


@qdrant_router.post("/points/upload-qa", response_model=ApiResponse, summary="批量上传 Q&A 文本")
async def api_upload_qa_text(body: QaBatchUploadBody):
    try:
        return _ok("导入成功", service.upload_qa_batch(body))
    except Exception as exc:
        raise _handle(exc) from exc


@qdrant_router.post("/points/upload-document", response_model=ApiResponse, summary="上传 PDF/DOCX 文档并分块入库")
async def api_upload_document(
    collectionName: str = Form(..., description="集合名称"),
    file: UploadFile = File(..., description=".pdf 或 .docx"),
):
    try:
        raw = await file.read()
        filename = file.filename or "document"
        data = service.upload_document_file(collectionName, filename, raw)
        chunks = data.get("importedChunks", 0)
        return _ok(f"成功导入 {chunks} 个文本块", data)
    except Exception as exc:
        raise _handle(exc) from exc


@qdrant_router.get("/documents", response_model=ApiResponse, summary="列出 Collection 下的文档索引")
async def api_list_documents(
    collectionName: str = Query(..., description="集合名称"),
):
    try:
        return _ok("查询成功", service.list_kb_documents(collectionName))
    except Exception as exc:
        raise _handle(exc) from exc


@qdrant_router.delete("/documents", response_model=ApiResponse, summary="按 docId 删除整份文档及其向量点")
async def api_delete_document(
    collectionName: str = Query(..., description="集合名称"),
    docId: str = Query(..., description="文档 ID"),
):
    try:
        return _ok("删除成功", service.delete_kb_document(collectionName, docId))
    except Exception as exc:
        raise _handle(exc) from exc


@qdrant_router.post("/points/upload-qa-file", response_model=ApiResponse, summary="上传 Q&A 格式 txt 文件")
async def api_upload_qa_file(
    collectionName: str = Form(..., description="集合名称"),
    file: UploadFile = File(..., description=".txt 文件，Q:/A: 格式"),
):
    try:
        raw = await file.read()
        text = raw.decode("utf-8-sig", errors="replace")
        body = QaBatchUploadBody(collectionName=collectionName, text=text)
        data = service.upload_qa_batch(body)
        return _ok(f"成功导入 {data.get('imported', 0)} 条 Q&A", data)
    except Exception as exc:
        raise _handle(exc) from exc


@qdrant_router.post("/points/qa", response_model=ApiResponse, summary="新增单条 Q&A")
async def api_create_qa_point(body: QaPointWriteBody):
    try:
        return _ok("写入成功", service.upsert_qa_point(body))
    except Exception as exc:
        raise _handle(exc) from exc


@qdrant_router.put("/points/qa", response_model=ApiResponse, summary="更新单条 Q&A")
async def api_update_qa_point(body: QaPointWriteBody):
    try:
        if body.pointId is None:
            raise HTTPException(status_code=400, detail="更新时请提供 pointId")
        return _ok("更新成功", service.upsert_qa_point(body))
    except HTTPException:
        raise
    except Exception as exc:
        raise _handle(exc) from exc
