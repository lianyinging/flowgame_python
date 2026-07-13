"""HACR：LLM 通读整篇文档 → 划分主题（小块检索）+ 主题对应原文（大块生成）。"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List

from src.flowgame.qdrant import hacr_config
from src.flowgame.qdrant.hacr_section_parser import HacrSection, parse_md_sections
from src.flowgame.qdrant.document_parser import _decode_text_content

logger = logging.getLogger(__name__)

_JSON_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)
_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class HacrChildChunk:
    snippet: str
    snippet_type: str
    parent_index: int
    child_index: int
    parent_text: str
    section_title: str


@dataclass
class HacrProcessResult:
    chunks: List[HacrChildChunk]
    parent_count: int
    used_llm: bool
    chunking_version: str


def _extract_json_object(text: str) -> Dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("LLM 返回为空")

    fence = _JSON_FENCE.search(raw)
    if fence:
        raw = fence.group(1).strip()

    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("未找到 JSON 对象")
    return json.loads(raw[start : end + 1])


def _truncate(text: str, limit: int) -> str:
    value = (text or "").strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _normalize_ws(text: str) -> str:
    return _WS.sub(" ", (text or "").strip())


def _decode_document_text(content: bytes | str) -> str:
    if isinstance(content, bytes):
        return _decode_text_content(content).replace("\r\n", "\n").strip()
    return (content or "").replace("\r\n", "\n").strip()


def _content_in_document(original: str, document: str, *, min_overlap: int = 40) -> bool:
    """校验 original_content 是否来自文档（允许空白差异）。"""
    orig = _normalize_ws(original)
    doc = _normalize_ws(document)
    if not orig or not doc:
        return False
    if orig in doc:
        return True
    probe_len = min(max(min_overlap, len(orig) // 3), len(orig), 200)
    probe = orig[:probe_len]
    return bool(probe) and probe in doc


def _build_theme_snippet(theme_title: str, retrieval_text: str) -> str:
    title = (theme_title or "").strip()
    retrieval = (retrieval_text or "").strip()
    if title and retrieval:
        return _truncate(f"{title}\n{retrieval}", 400)
    return _truncate(title or retrieval, 400)


def _build_theme_parent(theme_title: str, original_content: str) -> str:
    title = (theme_title or "").strip()
    body = (original_content or "").strip()
    if title and body:
        text = f"【{title}】\n{body}"
    else:
        text = body or title
    return _truncate(text, hacr_config.max_parent_text_chars())


def _document_theme_prompt(document_text: str, *, file_name: str) -> List[Dict[str, str]]:
    max_chars = hacr_config.max_document_chars()
    body = document_text
    truncated = False
    if len(body) > max_chars:
        body = body[:max_chars].rstrip() + "\n…（后续内容已截断）"
        truncated = True

    system = (
        "你是知识库文档分析助手。请通读整篇文档，自适应划分主题（通常 3~20 个，按文档实际结构决定）。\n"
        "每个主题必须包含：\n"
        "1. theme_title：主题名称（简短准确）。\n"
        "2. retrieval_text：用于检索的小块文本（关键词、实体、用户口语问法，50~150字）。\n"
        "3. original_content：该主题在原文中的对应内容，必须从文档原文摘录/拼接，禁止改写、摘要或编造。\n"
        "主题之间尽量不重叠；每个主题的 original_content 应覆盖该主题的完整原文段落。\n"
        "严格输出 JSON，不要输出其它解释。"
    )
    truncate_note = "（注意：下文为截断后的文档）" if truncated else ""
    user = (
        f"文档名：{file_name or 'document'}{truncate_note}\n\n"
        f"文档全文：\n{body}\n\n"
        "输出 JSON：\n"
        '{"themes":[{"theme_title":"...","retrieval_text":"...","original_content":"..."}]}'
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _parse_llm_themes(data: Dict[str, Any], *, document_text: str) -> List[HacrChildChunk]:
    raw_themes = data.get("themes")
    if not isinstance(raw_themes, list) or not raw_themes:
        raise ValueError("themes 为空")

    max_themes = hacr_config.max_themes()
    chunks: List[HacrChildChunk] = []

    for parent_index, item in enumerate(raw_themes[:max_themes]):
        if not isinstance(item, dict):
            continue
        theme_title = str(item.get("theme_title") or item.get("title") or "").strip()
        retrieval_text = str(
            item.get("retrieval_text") or item.get("retrieval_snippet") or item.get("snippet") or ""
        ).strip()
        original_content = str(
            item.get("original_content") or item.get("parent_text") or item.get("content") or ""
        ).strip()

        if not theme_title and not retrieval_text:
            continue
        if not original_content:
            logger.warning("HACR 主题缺少 original_content，跳过 theme=%s", theme_title or parent_index)
            continue

        if not _content_in_document(original_content, document_text):
            logger.warning(
                "HACR 主题原文未在文档中找到，跳过 theme=%s",
                theme_title or parent_index,
            )
            continue

        if not theme_title:
            theme_title = _truncate(original_content.split("\n", 1)[0], 80) or f"主题 {parent_index + 1}"

        chunks.append(
            HacrChildChunk(
                snippet=_build_theme_snippet(theme_title, retrieval_text),
                snippet_type="theme",
                parent_index=parent_index,
                child_index=0,
                parent_text=_build_theme_parent(theme_title, original_content),
                section_title=theme_title,
            )
        )

    if not chunks:
        raise ValueError("无有效主题")
    return chunks


def _extract_themes_with_llm(document_text: str, *, file_name: str) -> List[HacrChildChunk]:
    from src.flowgame.tinyflow_config import DeepSeekLlmClient

    client = DeepSeekLlmClient()
    messages = _document_theme_prompt(document_text, file_name=file_name)
    result = client.chat(
        messages,
        temperature=hacr_config.llm_temperature(),
        top_p=0.9,
        model=hacr_config.llm_model_override() or None,
    )
    if result.get("error"):
        raise ValueError(str(result["error"]))
    content = str(result.get("content") or "")
    data = _extract_json_object(content)
    return _parse_llm_themes(data, document_text=document_text)


def _fallback_themes_from_sections(sections: List[HacrSection]) -> List[HacrChildChunk]:
    """LLM 失败时：按 Markdown 章节作为主题，原文作为大块。"""
    chunks: List[HacrChildChunk] = []
    for parent_index, section in enumerate(sections):
        title = (section.title or "").strip() or f"主题 {parent_index + 1}"
        body = (section.body or section.raw_text or "").strip()
        if len(body) < 5:
            continue
        retrieval = _truncate(body.split("\n", 1)[0], 150)
        chunks.append(
            HacrChildChunk(
                snippet=_build_theme_snippet(title, retrieval),
                snippet_type="theme",
                parent_index=parent_index,
                child_index=0,
                parent_text=_build_theme_parent(title, body),
                section_title=title,
            )
        )
    return chunks


def process_document(content: bytes | str, *, file_name: str = "") -> HacrProcessResult:
    """
    通读整篇文档划分主题：
    - 小块（snippet）= 主题 + 检索短语
    - 大块（parent_text）= 该主题对应的原文
    """
    document_text = _decode_document_text(content)
    if not document_text:
        return HacrProcessResult(
            chunks=[],
            parent_count=0,
            used_llm=False,
            chunking_version=hacr_config.CHUNKING_VERSION_LEGACY,
        )

    chunks: List[HacrChildChunk] = []
    used_llm = False

    if hacr_config.is_llm_configured():
        try:
            chunks = _extract_themes_with_llm(document_text, file_name=file_name)
            used_llm = True
            logger.info(
                "HACR 文档主题划分完成 file=%s themes=%s used_llm=true",
                file_name,
                len(chunks),
            )
        except Exception as exc:
            logger.warning("HACR LLM 文档主题划分失败 file=%s: %s", file_name, exc)
            if not hacr_config.is_llm_fallback_enabled():
                raise

    if not chunks:
        sections = parse_md_sections(document_text)
        chunks = _fallback_themes_from_sections(sections)
        if not chunks and document_text:
            chunks = [
                HacrChildChunk(
                    snippet=_build_theme_snippet(file_name or "文档", _truncate(document_text, 150)),
                    snippet_type="theme",
                    parent_index=0,
                    child_index=0,
                    parent_text=_build_theme_parent(file_name or "文档", document_text),
                    section_title=file_name or "文档",
                )
            ]

    parent_indices = {chunk.parent_index for chunk in chunks}
    return HacrProcessResult(
        chunks=chunks,
        parent_count=len(parent_indices),
        used_llm=used_llm,
        chunking_version=hacr_config.CHUNKING_VERSION_LLM_HACR,
    )


# 兼容旧测试/调用
def process_sections(sections: List[HacrSection]) -> HacrProcessResult:
    combined = "\n\n".join(section.raw_text for section in sections if section.raw_text)
    return process_document(combined, file_name="document")
