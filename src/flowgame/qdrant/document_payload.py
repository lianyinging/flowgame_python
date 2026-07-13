"""文档 chunk 的 Qdrant payload 与向量化文本。"""
from __future__ import annotations

from typing import Any, Dict, Optional

from src.flowgame.qdrant.hacr_config import CHUNKING_VERSION_LLM_HACR


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


def build_hacr_embed_text(
    child_snippet: str,
    *,
    file_name: str = "",
    section_title: str = "",
) -> str:
    body = (child_snippet or "").strip()
    name = (file_name or "").strip()
    section = (section_title or "").strip()
    parts: list[str] = []
    if name:
        parts.append(f"文档：{name}")
    if section:
        parts.append(f"章节：{section}")
    if body:
        parts.append(body)
    return "\n".join(parts) if parts else body


def build_hacr_document_payload(
    *,
    child_snippet: str,
    parent_text: str,
    section_title: str,
    parent_index: int,
    child_index: int,
    chunk_index: int,
    doc_id: str,
    file_name: str,
    mime_type: str,
    snippet_type: str = "keyword",
    page: Optional[int] = None,
) -> Dict[str, Any]:
    meta: Dict[str, Any] = {
        "source_type": "document",
        "chunking_version": CHUNKING_VERSION_LLM_HACR,
        "granularity": "child",
        "doc_id": doc_id,
        "file_name": file_name,
        "chunk_index": chunk_index,
        "parent_index": parent_index,
        "child_index": child_index,
        "section_title": section_title,
        "child_snippet": child_snippet,
        "parent_text": parent_text,
        "snippet_type": snippet_type,
        "mime_type": mime_type,
    }
    if page is not None:
        meta["page"] = page
    page_label = f"（第 {page} 页）" if page is not None else ""
    section_label = f" / {section_title}" if section_title else ""
    return {
        "page_content": f"【{file_name}】{page_label}{section_label}\n{child_snippet}",
        "metadata": meta,
    }
