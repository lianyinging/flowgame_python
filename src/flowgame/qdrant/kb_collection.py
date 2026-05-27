"""FlowGame 知识库 Collection 命名：仅 flowgame_ 前缀，_qa / _doc 区分类型。"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

FLOWGAME_KB_PREFIX = "flowgame_"
KB_QA_SUFFIX = "_qa"
KB_DOC_SUFFIX = "_doc"
KB_COLLECTION_TYPE_QA = "qa"
KB_COLLECTION_TYPE_DOC = "document"

# 知识库短名：支持中文、字母、数字、下划线、连字符（展示名，不含 flowgame_ / _qa / _doc）
_BASE_NAME_PATTERN = re.compile(r"^[\u4e00-\u9fffA-Za-z0-9][\u4e00-\u9fffA-Za-z0-9_-]*$")


class KbCollectionNameError(ValueError):
    pass


def strip_flowgame_prefix(name: str) -> str:
    value = (name or "").strip()
    if value.startswith(FLOWGAME_KB_PREFIX):
        return value[len(FLOWGAME_KB_PREFIX) :].strip()
    return value


def normalize_kb_base_name(name: str) -> str:
    """解析为知识库短名（不含 flowgame_ 前缀与 _qa/_doc 后缀）。"""
    value = (name or "").strip()
    if not value:
        raise KbCollectionNameError("知识库名称不能为空")

    if value.endswith(KB_QA_SUFFIX):
        value = value[: -len(KB_QA_SUFFIX)]
    elif value.endswith(KB_DOC_SUFFIX):
        value = value[: -len(KB_DOC_SUFFIX)]

    value = strip_flowgame_prefix(value).strip()
    if not value:
        raise KbCollectionNameError("知识库名称无效")
    if value.startswith(FLOWGAME_KB_PREFIX):
        raise KbCollectionNameError("请勿重复包含 flowgame_ 前缀")
    if not _BASE_NAME_PATTERN.match(value):
        raise KbCollectionNameError(
            "知识库名称须以中文、字母或数字开头，可含下划线、连字符"
        )
    return value


def display_kb_base_name(name: str) -> str:
    """任意物理名 / base 名 → 界面展示用短名（如 flowgame_日常问题_doc → 日常问题）。"""
    return normalize_kb_base_name(name)


def to_qa_collection_name(base_name: str) -> str:
    return f"{FLOWGAME_KB_PREFIX}{normalize_kb_base_name(base_name)}{KB_QA_SUFFIX}"


def to_doc_collection_name(base_name: str) -> str:
    return f"{FLOWGAME_KB_PREFIX}{normalize_kb_base_name(base_name)}{KB_DOC_SUFFIX}"


def is_flowgame_kb_collection(name: str) -> bool:
    n = (name or "").strip()
    if not n.startswith(FLOWGAME_KB_PREFIX):
        return False
    return n.endswith(KB_QA_SUFFIX) or n.endswith(KB_DOC_SUFFIX)


def is_qa_collection_name(name: str) -> bool:
    n = (name or "").strip()
    return n.startswith(FLOWGAME_KB_PREFIX) and n.endswith(KB_QA_SUFFIX)


def is_doc_collection_name(name: str) -> bool:
    n = (name or "").strip()
    return n.startswith(FLOWGAME_KB_PREFIX) and n.endswith(KB_DOC_SUFFIX)


def collection_type_of(name: str) -> Optional[str]:
    if is_qa_collection_name(name):
        return KB_COLLECTION_TYPE_QA
    if is_doc_collection_name(name):
        return KB_COLLECTION_TYPE_DOC
    return None


def parse_base_from_physical_collection(name: str) -> Optional[str]:
    if not is_flowgame_kb_collection(name):
        return None
    try:
        return normalize_kb_base_name(name)
    except KbCollectionNameError:
        return None


def resolve_kb_base_from_any(name: str) -> str:
    return normalize_kb_base_name(name)


def _existing_collection_names() -> Set[str]:
    from src.flowgame.qdrant.client import ensure_qdrant_available

    client = ensure_qdrant_available()
    return {c.name for c in client.get_collections().collections}


def filter_flowgame_kb_collections(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """仅保留 flowgame_ 前缀且带 _qa/_doc 后缀的 Collection。"""
    filtered: List[Dict[str, Any]] = []
    for item in items:
        name = str(item.get("collectionName") or "").strip()
        if not is_flowgame_kb_collection(name):
            continue
        row = dict(item)
        row["collectionType"] = collection_type_of(name)
        filtered.append(row)
    return filtered


def resolve_qa_collection_name(name: str) -> str:
    raw = (name or "").strip()
    if not raw:
        raise KbCollectionNameError("collectionName 不能为空")

    existing = _existing_collection_names()
    if is_qa_collection_name(raw):
        if raw in existing:
            return raw
        raise KbCollectionNameError(f"Q&A Collection 不存在: {raw}")

    base = normalize_kb_base_name(raw)
    qa = to_qa_collection_name(base)
    if qa in existing:
        return qa

    raise KbCollectionNameError(
        f"未找到 Q&A Collection: {qa}。请先在「知识库管理」创建知识库「{base}」。"
    )


def resolve_doc_collection_name(name: str) -> str:
    raw = (name or "").strip()
    if not raw:
        raise KbCollectionNameError("collectionName 不能为空")

    existing = _existing_collection_names()
    if is_doc_collection_name(raw):
        if raw in existing:
            return raw
        raise KbCollectionNameError(f"文档 Collection 不存在: {raw}")

    base = normalize_kb_base_name(raw)
    doc = to_doc_collection_name(base)
    if doc in existing:
        return doc

    raise KbCollectionNameError(
        f"未找到文档 Collection: {doc}。请先在「知识库管理」创建知识库「{base}」。"
    )


def collections_for_search(name: str) -> List[Tuple[str, str]]:
    """工作流检索：仅 flowgame_{base}_qa + flowgame_{base}_doc。"""
    raw = (name or "").strip()
    if not raw:
        return []

    existing = _existing_collection_names()
    if is_qa_collection_name(raw) and raw in existing:
        return [(raw, KB_COLLECTION_TYPE_QA)]
    if is_doc_collection_name(raw) and raw in existing:
        return [(raw, KB_COLLECTION_TYPE_DOC)]

    try:
        base = normalize_kb_base_name(raw)
    except KbCollectionNameError:
        return []

    qa = to_qa_collection_name(base)
    doc = to_doc_collection_name(base)
    targets: List[Tuple[str, str]] = []
    if qa in existing:
        targets.append((qa, KB_COLLECTION_TYPE_QA))
    if doc in existing:
        targets.append((doc, KB_COLLECTION_TYPE_DOC))
    return targets


def list_kb_bases_from_collections(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """仅聚合 flowgame_*_qa / flowgame_*_doc。"""
    by_base: Dict[str, Dict[str, Any]] = {}

    for item in filter_flowgame_kb_collections(items):
        name = str(item.get("collectionName") or "").strip()
        base = parse_base_from_physical_collection(name)
        if not base:
            continue

        entry = by_base.setdefault(
            base,
            {
                "baseName": base,
                "qaCollection": to_qa_collection_name(base),
                "docCollection": to_doc_collection_name(base),
                "qaPointsCount": 0,
                "docPointsCount": 0,
                "status": item.get("status"),
            },
        )
        if is_qa_collection_name(name):
            entry["qaCollection"] = name
            entry["qaPointsCount"] = item.get("pointsCount") or 0
        elif is_doc_collection_name(name):
            entry["docCollection"] = name
            entry["docPointsCount"] = item.get("pointsCount") or 0

    bases = list(by_base.values())
    bases.sort(key=lambda x: str(x.get("baseName") or ""))
    return bases
