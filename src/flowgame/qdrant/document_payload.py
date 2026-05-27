"""文档 chunk 的 Qdrant payload 与向量化文本。"""
from __future__ import annotations

from typing import Any, Dict, Optional


def build_document_payload(
    *,
    chunk_text: str,
    doc_id: str,
    file_name: str,
    chunk_index: int,
    mime_type: str,
    page: Optional[int] = None,
) -> Dict[str, Any]:
    meta: Dict[str, Any] = {
        "source_type": "document",
        "doc_id": doc_id,
        "file_name": file_name,
        "chunk_index": chunk_index,
        "mime_type": mime_type,
    }
    if page is not None:
        meta["page"] = page
    page_label = f"（第 {page} 页）" if page is not None else ""
    return {
        "page_content": f"【{file_name}】{page_label}\n{chunk_text}",
        "metadata": meta,
    }


def build_document_embed_text(chunk_text: str, *, file_name: str = "") -> str:
    """向量化时带上文件名，便于与用户短问句对齐。"""
    body = (chunk_text or "").strip()
    name = (file_name or "").strip()
    if name:
        return f"文档：{name}\n{body}"
    return body
