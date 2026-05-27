"""独立项目 Embedding 路径解析（不依赖 smartAi）。"""
from __future__ import annotations

import os

# flowgame_python 项目根目录（src/flowgame/qdrant -> 上三级）
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
DEFAULT_LOCAL_MODEL_DIR = os.path.join(_PROJECT_ROOT, "model", "BAAI", "bge-small-zh-v1.5")
REMOTE_FALLBACK_MODEL = "BAAI/bge-small-zh-v1.5"


def _find_local_model_dir(base_dir: str) -> str | None:
    """递归查找含 config.json / modules.json 的目录（兼容 HuggingFace snapshots 结构）。"""
    if not os.path.isdir(base_dir):
        return None

    if os.path.isfile(os.path.join(base_dir, "config.json")) or os.path.isfile(
        os.path.join(base_dir, "modules.json")
    ):
        return base_dir

    for root, _dirs, files in os.walk(base_dir):
        if "config.json" in files or "sentence_bert_config.json" in files or "modules.json" in files:
            return root
    return None


def resolve_local_model_path() -> str | None:
    """返回可用的本地模型目录，否则 None。"""
    candidates: list[str] = []
    env_path = os.getenv("EMBEDDING_MODEL_PATH", "").strip()
    if env_path:
        candidates.append(env_path)
    candidates.append(DEFAULT_LOCAL_MODEL_DIR)

    for base in candidates:
        found = _find_local_model_dir(os.path.abspath(base))
        if found:
            return found
    return None


def get_embedding_model_id() -> str:
    """
    获取当前 Embedding 模型标识。
    - 已配置 EMBEDDING_API_URL 时返回 \"http\"
    - 否则返回本地目录路径或远程模型名
    """
    from src.flowgame.settings import get_flowgame_settings

    if get_flowgame_settings().embedding_api_url.strip():
        return "http"

    local = resolve_local_model_path()
    if local:
        return local
    return REMOTE_FALLBACK_MODEL
