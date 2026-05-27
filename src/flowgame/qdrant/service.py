"""FlowGame Qdrant 增删改查服务。"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional, Union

from qdrant_client.http import models as qmodels

from src.flowgame.qdrant import embedding as embedding_module
from src.flowgame.qdrant.client import ensure_qdrant_available
from src.flowgame.qdrant.kb_collection import (
    FLOWGAME_KB_PREFIX,
    KbCollectionNameError,
    filter_flowgame_kb_collections,
    list_kb_bases_from_collections,
    resolve_doc_collection_name,
    resolve_kb_base_from_any,
    resolve_qa_collection_name,
    to_doc_collection_name,
    to_qa_collection_name,
)
from src.flowgame.qdrant.document_chunk import chunk_segments
from src.flowgame.qdrant.document_parser import DocumentParseError, extract_document_segments
from src.flowgame.qdrant.document_payload import build_document_embed_text, build_document_payload
from src.flowgame.qdrant import doc_registry
from src.flowgame.qdrant.qa_parser import build_qa_embed_text, build_qa_payload, parse_qa_pairs
from src.flowgame.qdrant.schemas import (
    CollectionCreateBody,
    PointBatchDeleteBody,
    PointSearchBody,
    PointWriteBody,
    QaBatchUploadBody,
    QaPointWriteBody,
)

logger = logging.getLogger(__name__)

_DISTANCE_MAP = {
    "cosine": qmodels.Distance.COSINE,
    "euclid": qmodels.Distance.EUCLID,
    "dot": qmodels.Distance.DOT,
}


class QdrantServiceError(Exception):
    pass


def _normalize_collection_name(name: str) -> str:
    value = (name or "").strip()
    if not value:
        raise QdrantServiceError("collectionName 不能为空")
    return value


def _resolve_vector(body: PointWriteBody) -> List[float]:
    if body.vector is not None:
        if not body.vector:
            raise QdrantServiceError("vector 不能为空数组")
        return [float(x) for x in body.vector]
    if body.text is not None and str(body.text).strip():
        return embedding_module.embed_text(str(body.text).strip())
    raise QdrantServiceError("请提供 vector 或 text（text 需配置 EMBEDDING_API_URL）")


def _resolve_search_vector(body: PointSearchBody) -> List[float]:
    if body.vector is not None:
        if not body.vector:
            raise QdrantServiceError("vector 不能为空数组")
        return [float(x) for x in body.vector]
    if body.text is not None and str(body.text).strip():
        return embedding_module.embed_text(str(body.text).strip())
    raise QdrantServiceError("请提供 vector 或 text（text 需配置 EMBEDDING_API_URL）")


def _point_id(point_id: Optional[Union[str, int]]) -> Union[str, int]:
    if point_id is None:
        return str(uuid.uuid4())
    return point_id


def _point_to_dict(point: Any, with_vector: bool = False) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "id": point.id,
        "payload": point.payload or {},
    }
    if with_vector and point.vector is not None:
        if isinstance(point.vector, dict):
            data["vector"] = point.vector
        else:
            data["vector"] = list(point.vector)
    return data


def _scored_point_to_dict(point: Any, with_vector: bool = False) -> Dict[str, Any]:
    item = _point_to_dict(point, with_vector=with_vector)
    item["score"] = point.score
    return item


def list_collections() -> Dict[str, Any]:
    client = ensure_qdrant_available()
    collections = client.get_collections().collections
    items: List[Dict[str, Any]] = []
    for col in collections:
        name = col.name
        entry: Dict[str, Any] = {"collectionName": name, "status": None}
        # get_collections 仅返回 CollectionDescription(name)；详情需 get_collection
        try:
            info = client.get_collection(name)
            entry["status"] = str(info.status) if info.status is not None else None
            entry["pointsCount"] = info.points_count
        except Exception as exc:
            logger.debug("get_collection failed for %s: %s", name, exc)
        items.append(entry)
    return {"collections": items, "total": len(items)}


def get_collection(collection_name: str) -> Dict[str, Any]:
    client = ensure_qdrant_available()
    name = _normalize_collection_name(collection_name)
    try:
        info = client.get_collection(name)
    except Exception as exc:
        raise QdrantServiceError(f"集合不存在或查询失败: {name}") from exc

    vectors = info.config.params.vectors
    vector_size = None
    distance = None
    if vectors is not None:
        if hasattr(vectors, "size"):
            vector_size = vectors.size
            distance = str(vectors.distance)
        elif isinstance(vectors, dict) and vectors:
            first = next(iter(vectors.values()))
            vector_size = getattr(first, "size", None)
            distance = str(getattr(first, "distance", ""))

    return {
        "collectionName": name,
        "pointsCount": info.points_count,
        "status": str(info.status) if info.status is not None else None,
        "vectorSize": vector_size,
        "distance": distance,
    }


def _kb_name_error(exc: KbCollectionNameError) -> QdrantServiceError:
    return QdrantServiceError(str(exc))


def create_kb_pair(body: CollectionCreateBody) -> Dict[str, Any]:
    try:
        base = resolve_kb_base_from_any(body.collectionName)
    except KbCollectionNameError as exc:
        raise _kb_name_error(exc) from exc

    qa_name = to_qa_collection_name(base)
    doc_name = to_doc_collection_name(base)
    qa_body = CollectionCreateBody(
        collectionName=qa_name,
        vectorSize=body.vectorSize,
        distance=body.distance,
    )
    doc_body = CollectionCreateBody(
        collectionName=doc_name,
        vectorSize=body.vectorSize,
        distance=body.distance,
    )

    client = ensure_qdrant_available()
    existing = {c.name for c in client.get_collections().collections}
    created: List[str] = []
    if qa_name not in existing:
        create_collection(qa_body)
        created.append(qa_name)
    if doc_name not in existing:
        create_collection(doc_body)
        created.append(doc_name)
    if not created and qa_name in existing and doc_name in existing:
        raise QdrantServiceError(f"知识库已存在: {base}")

    return {
        "baseName": base,
        "qaCollection": qa_name,
        "docCollection": doc_name,
        "created": created,
    }


def delete_kb_pair(base_name: str) -> Dict[str, Any]:
    try:
        base = resolve_kb_base_from_any(base_name)
    except KbCollectionNameError as exc:
        raise _kb_name_error(exc) from exc

    qa_name = to_qa_collection_name(base)
    doc_name = to_doc_collection_name(base)
    deleted: List[str] = []
    client = ensure_qdrant_available()
    existing = {c.name for c in client.get_collections().collections}
    if qa_name in existing:
        delete_collection(qa_name)
        deleted.append(qa_name)
    if doc_name in existing:
        delete_collection(doc_name)
        deleted.append(doc_name)

    try:
        from src.flowgame.redis.client import redis_client

        if redis_client.ping():
            redis_client.delete(
                doc_registry.build_kb_docs_key(base),
            )
    except Exception as exc:
        logger.debug("清理文档 Redis 索引失败: %s", exc)

    return {"baseName": base, "deletedCollections": deleted}


def list_kb_bases() -> Dict[str, Any]:
    raw = list_collections()
    all_items = raw.get("collections") or []
    flowgame_items = filter_flowgame_kb_collections(all_items)
    bases = list_kb_bases_from_collections(all_items)
    return {
        "bases": bases,
        "total": len(bases),
        "prefix": FLOWGAME_KB_PREFIX,
        "flowgameCollectionCount": len(flowgame_items),
    }


def list_flowgame_kb_collections() -> Dict[str, Any]:
    """列出所有 flowgame_ 前缀的 Q&A/文档物理 Collection。"""
    raw = list_collections()
    items = filter_flowgame_kb_collections(raw.get("collections") or [])
    return {"collections": items, "total": len(items), "prefix": FLOWGAME_KB_PREFIX}


def create_collection(body: CollectionCreateBody) -> Dict[str, Any]:
    client = ensure_qdrant_available()
    name = _normalize_collection_name(body.collectionName)
    distance_key = (body.distance or "Cosine").strip().lower()
    distance = _DISTANCE_MAP.get(distance_key)
    if distance is None:
        raise QdrantServiceError("distance 仅支持 Cosine / Euclid / Dot")

    collections = {c.name for c in client.get_collections().collections}
    if name in collections:
        raise QdrantServiceError(f"集合已存在: {name}")

    client.create_collection(
        collection_name=name,
        vectors_config=qmodels.VectorParams(size=body.vectorSize, distance=distance),
    )
    return get_collection(name)


def delete_collection(collection_name: str) -> Dict[str, Any]:
    client = ensure_qdrant_available()
    name = _normalize_collection_name(collection_name)
    client.delete_collection(name)
    return {"collectionName": name, "deleted": True}


def get_point(collection_name: str, point_id: Union[str, int]) -> Dict[str, Any]:
    client = ensure_qdrant_available()
    name = _normalize_collection_name(collection_name)
    records = client.retrieve(
        collection_name=name,
        ids=[point_id],
        with_payload=True,
        with_vectors=True,
    )
    if not records:
        raise QdrantServiceError(f"点不存在: {point_id}")
    return _point_to_dict(records[0], with_vector=True)


def upsert_point(body: PointWriteBody) -> Dict[str, Any]:
    client = ensure_qdrant_available()
    name = _normalize_collection_name(body.collectionName)
    pid = _point_id(body.pointId)
    vector = _resolve_vector(body)

    point = qmodels.PointStruct(id=pid, vector=vector, payload=body.payload or {})
    client.upsert(collection_name=name, points=[point], wait=True)
    return get_point(name, pid)


def delete_points(body: PointBatchDeleteBody) -> Dict[str, Any]:
    client = ensure_qdrant_available()
    name = _normalize_collection_name(body.collectionName)
    selector = qmodels.PointIdsList(points=list(body.pointIds))
    result = client.delete(collection_name=name, points_selector=selector, wait=True)
    status = getattr(result, "status", None)
    return {
        "collectionName": name,
        "pointIds": body.pointIds,
        "deleted": True,
        "status": str(status) if status is not None else None,
    }


def scroll_points(
    collection_name: str,
    limit: int = 20,
    offset: Optional[Union[str, int]] = None,
    with_vector: bool = False,
) -> Dict[str, Any]:
    client = ensure_qdrant_available()
    try:
        name = resolve_qa_collection_name(collection_name)
    except KbCollectionNameError as exc:
        raise QdrantServiceError(str(exc)) from exc
    _normalize_collection_name(name)
    records, next_offset = client.scroll(
        collection_name=name,
        limit=limit,
        offset=offset,
        with_payload=True,
        with_vectors=with_vector,
    )
    points = [_point_to_dict(p, with_vector=with_vector) for p in records]
    return {
        "collectionName": name,
        "points": points,
        "nextOffset": next_offset,
        "count": len(points),
    }


def upload_qa_batch(body: QaBatchUploadBody) -> Dict[str, Any]:
    client = ensure_qdrant_available()
    try:
        name = resolve_qa_collection_name(body.collectionName)
    except KbCollectionNameError as exc:
        raise _kb_name_error(exc) from exc
    _normalize_collection_name(name)
    pairs = parse_qa_pairs(body.text)
    if not pairs:
        raise QdrantServiceError("未解析到有效的 Q&A 条目，请使用 Q: / A: 格式")

    texts = [build_qa_embed_text(q, a) for q, a in pairs]
    vectors = embedding_module.embed_texts(texts)
    points = [
        qmodels.PointStruct(
            id=str(uuid.uuid4()),
            vector=vectors[index],
            payload=build_qa_payload(question, answer),
        )
        for index, (question, answer) in enumerate(pairs)
    ]
    client.upsert(collection_name=name, points=points, wait=True)
    try:
        base = resolve_kb_base_from_any(body.collectionName)
    except KbCollectionNameError:
        base = name
    return {
        "collectionName": name,
        "baseName": base,
        "qaCollection": name,
        "imported": len(points),
        "total": len(points),
    }


def upsert_qa_point(body: QaPointWriteBody) -> Dict[str, Any]:
    question = (body.question or "").strip()
    answer = (body.answer or "").strip()
    if not question or not answer:
        raise QdrantServiceError("question 与 answer 均不能为空")
    try:
        qa_name = resolve_qa_collection_name(body.collectionName)
    except KbCollectionNameError as exc:
        raise _kb_name_error(exc) from exc
    write_body = PointWriteBody(
        collectionName=qa_name,
        pointId=body.pointId,
        text=build_qa_embed_text(question, answer),
        payload=build_qa_payload(question, answer),
    )
    return upsert_point(write_body)


_EMBED_BATCH_SIZE = 32


def upload_document_file(
    collection_name: str,
    filename: str,
    content: bytes,
) -> Dict[str, Any]:
    client = ensure_qdrant_available()
    try:
        base = resolve_kb_base_from_any(collection_name)
        name = resolve_doc_collection_name(collection_name)
    except KbCollectionNameError as exc:
        raise _kb_name_error(exc) from exc
    _normalize_collection_name(name)

    try:
        segments = extract_document_segments(filename, content)
    except DocumentParseError as exc:
        raise QdrantServiceError(str(exc)) from exc

    chunked = chunk_segments(segments)
    if not chunked:
        raise QdrantServiceError("分块后无有效文本")

    doc_id = str(uuid.uuid4())
    file_name = (filename or "document").strip() or "document"
    ext = file_name.lower()[file_name.rfind(".") :] if "." in file_name else ""
    mime_type = "application/pdf" if ext == ".pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    texts = [
        build_document_embed_text(text, file_name=file_name) for text, _page in chunked
    ]
    all_vectors: List[List[float]] = []
    for start in range(0, len(texts), _EMBED_BATCH_SIZE):
        batch = texts[start : start + _EMBED_BATCH_SIZE]
        all_vectors.extend(embedding_module.embed_texts(batch))

    point_ids: List[str] = []
    points = []
    for index, ((chunk_text, page), vector) in enumerate(zip(chunked, all_vectors)):
        pid = str(uuid.uuid4())
        point_ids.append(pid)
        points.append(
            qmodels.PointStruct(
                id=pid,
                vector=vector,
                payload=build_document_payload(
                    chunk_text=chunk_text,
                    doc_id=doc_id,
                    file_name=file_name,
                    chunk_index=index,
                    mime_type=mime_type,
                    page=page,
                ),
            )
        )

    client.upsert(collection_name=name, points=points, wait=True)
    entry = doc_registry.register_document(
        base,
        doc_id=doc_id,
        file_name=file_name,
        chunk_count=len(points),
        mime_type=mime_type,
        point_ids=point_ids,
    )
    return {
        "collectionName": name,
        "baseName": base,
        "docCollection": name,
        "docId": doc_id,
        "fileName": file_name,
        "importedChunks": len(points),
        "document": entry,
    }


def list_kb_documents(collection_name: str) -> Dict[str, Any]:
    try:
        base = resolve_kb_base_from_any(collection_name)
    except KbCollectionNameError as exc:
        raise _kb_name_error(exc) from exc
    try:
        documents = doc_registry.list_documents(base)
    except RuntimeError as exc:
        raise QdrantServiceError(str(exc)) from exc
    return {
        "baseName": base,
        "docCollection": resolve_doc_collection_name(base),
        "documents": documents,
        "total": len(documents),
    }


def delete_kb_document(collection_name: str, doc_id: str) -> Dict[str, Any]:
    client = ensure_qdrant_available()
    try:
        base = resolve_kb_base_from_any(collection_name)
        name = resolve_doc_collection_name(collection_name)
    except KbCollectionNameError as exc:
        raise _kb_name_error(exc) from exc
    normalized_doc_id = (doc_id or "").strip()
    if not normalized_doc_id:
        raise QdrantServiceError("docId 不能为空")

    point_ids = doc_registry.get_document_point_ids(base, normalized_doc_id)
    if not point_ids:
        existed = doc_registry.remove_document(base, normalized_doc_id)
        if not existed:
            raise QdrantServiceError(f"文档不存在: {normalized_doc_id}")
        return {
            "baseName": base,
            "docCollection": name,
            "docId": normalized_doc_id,
            "deletedPoints": 0,
            "deleted": True,
        }

    delete_points(PointBatchDeleteBody(collectionName=name, pointIds=point_ids))
    doc_registry.remove_document(base, normalized_doc_id)
    return {
        "baseName": base,
        "docCollection": name,
        "docId": normalized_doc_id,
        "deletedPoints": len(point_ids),
        "deleted": True,
    }


def search_points(body: PointSearchBody) -> Dict[str, Any]:
    client = ensure_qdrant_available()
    name = _normalize_collection_name(body.collectionName)
    query_vector = _resolve_search_vector(body)

    try:
        results = client.search(
            collection_name=name,
            query_vector=query_vector,
            limit=body.limit,
            score_threshold=body.scoreThreshold,
            with_payload=body.withPayload,
            with_vectors=body.withVector,
        )
    except AttributeError:
        query_result = client.query_points(
            collection_name=name,
            query=query_vector,
            limit=body.limit,
            score_threshold=body.scoreThreshold,
            with_payload=body.withPayload,
            with_vectors=body.withVector,
        )
        results = query_result.points

    hits = [_scored_point_to_dict(item, with_vector=body.withVector) for item in results]
    return {
        "collectionName": name,
        "hits": hits,
        "total": len(hits),
    }
