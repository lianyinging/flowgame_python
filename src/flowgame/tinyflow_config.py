"""Tinyflow runtime configuration and providers."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol

from openai import OpenAI

import logging

logger = logging.getLogger(__name__)

# 向量检索最低相似度（过滤弱相关文档块；可按业务在环境变量中覆盖）
DEFAULT_KB_SCORE_THRESHOLD = 0.38


class LlmProvider(Protocol):
    def get_llm(self, llm_id: Any) -> Any: ...


class KnowledgeProvider(Protocol):
    def get_knowledge(self, knowledge_id: Any) -> Any: ...


class SearchEngineProvider(Protocol):
    def get_search_engine(self, engine: Any) -> Any: ...


class DeepSeekLlmClient:
    """OpenAI-compatible LLM client for LlmNode."""

    def __init__(self) -> None:
        api_key = os.getenv("DEEPSEEK_API_KEY", "").strip() or "not-configured"
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
        self._model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip()
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.8,
        top_p: float = 0.8,
    ) -> Dict[str, Any]:
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=temperature,
                top_p=top_p,
            )
            content = response.choices[0].message.content or ""
            return {"content": content}
        except Exception as exc:
            logger.error("LlmNode chat failed: %s", exc)
            return {"error": str(exc)}


class DefaultLlmProvider:
    def __init__(self) -> None:
        self._default = DeepSeekLlmClient()
        self._cache: Dict[str, DeepSeekLlmClient] = {}

    def get_llm(self, llm_id: Any) -> DeepSeekLlmClient:
        if llm_id is None:
            return self._default
        key = str(llm_id)
        return self._cache.setdefault(key, DeepSeekLlmClient())


class VectorKnowledge:
    """未指定 Collection 时回退到项目全局向量库（如 faq_collection）。"""

    def __init__(self, collection_name: Optional[str] = None) -> None:
        self.collection_name = (collection_name or "").strip() or None

    def search(self, keyword: str, limit: int) -> List[Dict[str, Any]]:
        # 已选择 Collection 时必须走 Qdrant 指定集合，避免查到其他库
        if self.collection_name:
            return QdrantCollectionKnowledge(self.collection_name).search(keyword, limit)

        logger.warning(
            "未指定知识库 Collection，且独立部署未接入全局向量库，返回空结果。"
        )
        return []


def _qdrant_hit_to_document(
    hit: Dict[str, Any],
    *,
    knowledge_id: str,
    default_source_type: str = "qa",
) -> Dict[str, Any]:
    payload = hit.get("payload") or {}
    meta = payload.get("metadata") or {}
    if not isinstance(meta, dict):
        meta = {}
    source_type = str(meta.get("source_type") or default_source_type)
    question = str(meta.get("question") or "")
    answer = str(meta.get("answer") or "")
    page_content = str(payload.get("page_content") or "")
    if source_type == "document":
        file_name = str(meta.get("file_name") or "")
        chunk_index = meta.get("chunk_index")
        title = file_name or "文档片段"
        if chunk_index is not None:
            title = f"{title} #{int(chunk_index) + 1}"
        content = page_content
    else:
        title = question
        content = page_content or answer
    return {
        "title": title,
        "content": content,
        "documentId": hit.get("id"),
        "knowledgeId": knowledge_id,
        "score": hit.get("score"),
        "question": question,
        "answer": answer,
        "sourceType": source_type,
    }


class QdrantCollectionKnowledge:
    """按知识库 base 名检索：合并 {base}_qa 与 {base}_doc，带相似度阈值。"""

    def __init__(self, collection_name: str) -> None:
        self.collection_name = (collection_name or "").strip()

    def search(self, keyword: str, limit: int) -> List[Dict[str, Any]]:
        if not self.collection_name or not (keyword or "").strip():
            return []
        try:
            from src.flowgame.qdrant.kb_collection import collections_for_search
            from src.flowgame.qdrant.schemas import PointSearchBody
            from src.flowgame.qdrant import service as qdrant_service

            targets = collections_for_search(self.collection_name)
            if not targets:
                logger.warning("知识库不存在或未创建: %s", self.collection_name)
                return []

            cap = max(1, min(limit, 100))
            per_limit = max(1, (cap + len(targets) - 1) // len(targets))
            query_text = str(keyword).strip()

            logger.info(
                "知识库检索 base=%s targets=%s keyword=%s limit=%s",
                self.collection_name,
                targets,
                query_text[:80],
                cap,
            )

            merged: List[Dict[str, Any]] = []
            for physical_name, kind in targets:
                result = qdrant_service.search_points(
                    PointSearchBody(
                        collectionName=physical_name,
                        text=query_text,
                        limit=per_limit,
                        scoreThreshold=DEFAULT_KB_SCORE_THRESHOLD,
                    )
                )
                for hit in result.get("hits") or []:
                    doc = _qdrant_hit_to_document(
                        hit,
                        knowledge_id=self.collection_name,
                        default_source_type="qa" if kind == "qa" else "document",
                    )
                    doc["collection"] = physical_name
                    merged.append(doc)

            merged.sort(key=lambda item: float(item.get("score") or 0), reverse=True)
            return merged[:cap]
        except Exception as exc:
            logger.warning("Qdrant collection search failed [%s]: %s", self.collection_name, exc)
            return []


class DefaultKnowledgeProvider:
    """knowledgeId / Collection 名称 → 仅检索对应 Qdrant Collection。"""

    def get_knowledge(self, knowledge_id: Any) -> VectorKnowledge | QdrantCollectionKnowledge:
        name = str(knowledge_id).strip() if knowledge_id is not None else ""
        if name:
            return QdrantCollectionKnowledge(name)
        return VectorKnowledge(None)


@dataclass
class TinyflowRuntime:
    data: str
    llm_provider: Optional[LlmProvider] = None
    knowledge_provider: Optional[KnowledgeProvider] = None
    search_engine_provider: Optional[SearchEngineProvider] = None

    def get_llm_provider(self) -> LlmProvider:
        if self.llm_provider is None:
            self.llm_provider = DefaultLlmProvider()
        return self.llm_provider

    def get_knowledge_provider(self) -> KnowledgeProvider:
        if self.knowledge_provider is None:
            self.knowledge_provider = DefaultKnowledgeProvider()
        return self.knowledge_provider
