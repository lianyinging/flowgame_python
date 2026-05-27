"""
FlowGame Embedding：优先 HTTP API（EMBEDDING_API_URL），否则回退本地 BGE 模型。
"""
from __future__ import annotations

import logging
from typing import List, Optional, Sequence

import requests

from src.flowgame.qdrant.embedding_config import get_embedding_model_id, resolve_local_model_path
from src.flowgame.settings import get_flowgame_settings

logger = logging.getLogger(__name__)

_local_embedder: Optional[object] = None


class EmbeddingNotConfiguredError(RuntimeError):
    pass


def _resolve_embedding_api_url() -> str:
    return get_flowgame_settings().embedding_api_url.strip()


def is_embedding_enabled() -> bool:
    if _resolve_embedding_api_url():
        return True
    return get_embedding_model_id() != "http"


def get_embedding_mode() -> str:
    if _resolve_embedding_api_url():
        return "http"
    if resolve_local_model_path():
        return "local"
    model_id = get_embedding_model_id()
    if model_id != "http":
        return "remote"
    return "none"


def get_default_vector_size() -> int:
    import os

    if _resolve_embedding_api_url():
        return int(os.getenv("EMBEDDING_VECTOR_SIZE", "512"))

    try:
        embedder = _get_local_embedder()
        dim = embedder.model.get_sentence_embedding_dimension()
        return int(dim) if dim else 512
    except Exception:
        return int(os.getenv("EMBEDDING_VECTOR_SIZE", "512"))


def _get_local_embedder():
    global _local_embedder
    if _local_embedder is not None:
        return _local_embedder

    from src.flowgame.embeddings.chinese_embeddings import ChineseEmbeddings

    model_name = get_embedding_model_id()
    if model_name == "http":
        from src.flowgame.qdrant.embedding_config import DEFAULT_LOCAL_MODEL_DIR

        raise EmbeddingNotConfiguredError(
            "未配置 EMBEDDING_API_URL，且未找到本地模型。"
            f"请将模型放到 {DEFAULT_LOCAL_MODEL_DIR}，"
            "或设置 EMBEDDING_MODEL_PATH / EMBEDDING_API_URL。"
        )

    logger.info("FlowGame 使用本地 Embedding 模型: %s", model_name)
    _local_embedder = ChineseEmbeddings(model_name)
    return _local_embedder


def _embed_via_http(texts: Sequence[str], api_url: str, timeout: int) -> List[List[float]]:
    try:
        response = requests.post(
            api_url,
            json={"texts": list(texts)},
            timeout=timeout,
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()
        result = response.json()
    except Exception as exc:
        logger.error("Embedding HTTP 调用失败: %s", exc)
        raise RuntimeError(f"Embedding 服务调用失败: {exc}") from exc

    return _extract_embeddings(result, len(texts))


def _embed_via_local(texts: Sequence[str]) -> List[List[float]]:
    embedder = _get_local_embedder()
    vectors = embedder.embed_documents(list(texts))
    if len(vectors) != len(texts):
        raise RuntimeError(f"Embedding 数量不匹配: 期望 {len(texts)}, 实际 {len(vectors)}")
    return [[float(x) for x in vec] for vec in vectors]


def embed_texts(texts: Sequence[str]) -> List[List[float]]:
    if not texts:
        return []

    cfg = get_flowgame_settings()
    api_url = _resolve_embedding_api_url()
    if api_url:
        return _embed_via_http(texts, api_url, cfg.embedding_api_timeout)

    try:
        return _embed_via_local(texts)
    except EmbeddingNotConfiguredError:
        raise
    except Exception as exc:
        logger.error("本地 Embedding 失败: %s", exc, exc_info=True)
        raise RuntimeError(f"Embedding 失败: {exc}") from exc


def embed_text(text: str) -> List[float]:
    return embed_texts([text])[0]


def _extract_embeddings(result: object, expected: int) -> List[List[float]]:
    if isinstance(result, dict):
        for key in ("embeddings", "data", "vectors", "embedding"):
            if key in result:
                value = result[key]
                if key == "embedding" and isinstance(value, list) and value and isinstance(value[0], (int, float)):
                    return [list(value)]
                if isinstance(value, list):
                    embeddings = [_as_vector(item) for item in value]
                    _ensure_count(embeddings, expected)
                    return embeddings
        if "result" in result and isinstance(result["result"], list):
            embeddings = [_as_vector(item) for item in result["result"]]
            _ensure_count(embeddings, expected)
            return embeddings

    if isinstance(result, list):
        embeddings = [_as_vector(item) for item in result]
        _ensure_count(embeddings, expected)
        return embeddings

    raise RuntimeError(f"无法解析 Embedding 响应: {result!r}")


def _ensure_count(embeddings: List[List[float]], expected: int) -> None:
    if len(embeddings) != expected:
        raise RuntimeError(f"Embedding 数量不匹配: 期望 {expected}, 实际 {len(embeddings)}")


def _as_vector(item: object) -> List[float]:
    if isinstance(item, list):
        return [float(x) for x in item]
    if isinstance(item, dict):
        for key in ("embedding", "vector", "values"):
            if key in item and isinstance(item[key], list):
                return [float(x) for x in item[key]]
    raise RuntimeError(f"无法解析向量项: {item!r}")
