"""知识库文档索引（Redis，键前缀与 FLOWGAME_REDIS_KEY_PREFIX 一致）。"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.flowgame.key_prefix import get_kb_doc_points_redis_prefix, get_kb_docs_redis_prefix

logger = logging.getLogger(__name__)


def build_kb_docs_key(collection_name: str) -> str:
    return f"{get_kb_docs_redis_prefix()}{collection_name.strip()}"


def build_kb_doc_points_key(collection_name: str, doc_id: str) -> str:
    return f"{get_kb_doc_points_redis_prefix()}{collection_name.strip()}:{doc_id.strip()}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_docs_list(raw: Any) -> List[Dict[str, Any]]:
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [item for item in parsed if isinstance(item, dict)]
        except json.JSONDecodeError:
            pass
    return []


def _get_redis():
    from src.flowgame.redis.client import redis_client

    if not redis_client.ping():
        raise RuntimeError("Redis 不可用，无法维护文档索引")
    return redis_client


def list_documents(collection_name: str) -> List[Dict[str, Any]]:
    client = _get_redis()
    key = build_kb_docs_key(collection_name)
    raw = client.get_json(key, default=[])
    docs = _load_docs_list(raw)
    return sorted(docs, key=lambda item: str(item.get("createdAt") or ""), reverse=True)


def get_document(collection_name: str, doc_id: str) -> Optional[Dict[str, Any]]:
    for item in list_documents(collection_name):
        if str(item.get("docId") or "") == doc_id:
            return item
    return None


def register_document(
    collection_name: str,
    *,
    doc_id: str,
    file_name: str,
    chunk_count: int,
    mime_type: str,
    point_ids: List[str],
) -> Dict[str, Any]:
    client = _get_redis()
    docs_key = build_kb_docs_key(collection_name)
    points_key = build_kb_doc_points_key(collection_name, doc_id)

    entry = {
        "docId": doc_id,
        "fileName": file_name,
        "chunkCount": chunk_count,
        "mimeType": mime_type,
        "createdAt": _now_iso(),
    }

    docs = list_documents(collection_name)
    docs = [d for d in docs if str(d.get("docId") or "") != doc_id]
    docs.insert(0, entry)
    client.set_json(docs_key, docs)
    client.set_json(points_key, point_ids)
    return entry


def get_document_point_ids(collection_name: str, doc_id: str) -> List[str]:
    client = _get_redis()
    key = build_kb_doc_points_key(collection_name, doc_id)
    raw = client.get_json(key, default=[])
    if isinstance(raw, list):
        return [str(item) for item in raw if item is not None]
    return []


def remove_document(collection_name: str, doc_id: str) -> bool:
    client = _get_redis()
    docs_key = build_kb_docs_key(collection_name)
    points_key = build_kb_doc_points_key(collection_name, doc_id)

    docs = list_documents(collection_name)
    next_docs = [d for d in docs if str(d.get("docId") or "") != doc_id]
    client.set_json(docs_key, next_docs)
    client.delete(points_key)
    return len(next_docs) < len(docs)
