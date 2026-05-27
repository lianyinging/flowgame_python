"""本地中文 Embedding（BGE 等 sentence-transformers 模型）。"""
from __future__ import annotations

import json
import logging
import os
from typing import List

from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


class ChineseEmbeddings:
    def __init__(self, model_name: str = "BAAI/bge-small-zh-v1.5") -> None:
        is_local_path = os.path.isabs(model_name) or (
            os.path.sep in model_name and os.path.exists(model_name)
        )

        if is_local_path:
            model_path = os.path.abspath(model_name)
            if not os.path.isdir(model_path):
                raise ValueError(f"模型路径不存在: {model_path}")

            required_files = ("config.json", "modules.json")
            if not any(os.path.exists(os.path.join(model_path, f)) for f in required_files):
                raise ValueError(f"模型目录缺少必要文件: {model_path}")

            logger.info("从本地路径加载 Embedding 模型: %s", model_path)
            try:
                from sentence_transformers.models import Pooling, Transformer

                config_path = os.path.join(model_path, "config_sentence_transformers.json")
                max_seq_length = 512
                if os.path.exists(config_path):
                    with open(config_path, encoding="utf-8") as f:
                        st_config = json.load(f)
                    max_seq_length = int(st_config.get("max_seq_length", 512))

                word_embedding_model = Transformer(model_path, max_seq_length=max_seq_length)
                pooling_model = Pooling(word_embedding_model.get_word_embedding_dimension())
                self.model = SentenceTransformer(modules=[word_embedding_model, pooling_model])
            except Exception as exc:
                logger.warning("手动组装 SentenceTransformer 失败，尝试直接加载: %s", exc)
                self.model = SentenceTransformer(model_path)
        else:
            logger.info("加载远程 Embedding 模型: %s", model_name)
            self.model = SentenceTransformer(model_name)

        logger.info(
            "Embedding 模型就绪: dim=%s max_len=%s",
            self.model.get_sentence_embedding_dimension(),
            self.model.max_seq_length,
        )

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        embeddings = self.model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return embeddings.tolist()

    def embed_query(self, text: str) -> List[float]:
        embedding = self.model.encode(
            [text],
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return embedding[0].tolist()
