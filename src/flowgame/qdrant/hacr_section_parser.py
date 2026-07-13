"""Markdown 章节解析（HACR 入库用）。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

from src.flowgame.qdrant.document_parser import _decode_text_content

_MD_HEADING_LINE = re.compile(r"^(#{1,6})\s+(.+)$")
_MD_HEADING_SPLIT = re.compile(r"(?=^#{1,6}\s)", re.MULTILINE)


def _count_heading_lines(text: str, level: int) -> int:
    pattern = re.compile(rf"^{'#' * level}\s+", re.MULTILINE)
    return len(pattern.findall(text or ""))


def _split_md_parts(text: str) -> List[str]:
    """产品类 MD 优先按 ## / ### 分节，避免整篇合成一个 parent。"""
    normalized = (text or "").replace("\r\n", "\n").strip()
    if not normalized:
        return []

    h3_count = _count_heading_lines(normalized, 3)
    h2_count = _count_heading_lines(normalized, 2)

    if h3_count >= 2:
        parts = [part.strip() for part in re.split(r"(?=^###\s+)", normalized, flags=re.MULTILINE) if part.strip()]
        if len(parts) >= 2:
            return parts

    if h2_count >= 2:
        parts = [part.strip() for part in re.split(r"(?=^##\s+)", normalized, flags=re.MULTILINE) if part.strip()]
        parts = [part for part in parts if part.startswith("##")]
        if len(parts) >= 2:
            return parts

    parts = [part.strip() for part in _MD_HEADING_SPLIT.split(normalized) if part.strip()]
    return parts if parts else [normalized]


@dataclass(frozen=True)
class HacrSection:
    title: str
    body: str
    raw_text: str

    @property
    def char_count(self) -> int:
        return len(self.raw_text or "")


def _strip_heading(section_text: str) -> tuple[str, str]:
    lines = (section_text or "").splitlines()
    if not lines:
        return "", (section_text or "").strip()

    match = _MD_HEADING_LINE.match(lines[0].strip())
    if match:
        title = (match.group(2) or "").strip()
        body = "\n".join(lines[1:]).strip()
        return title, body

    return "", section_text.strip()


def parse_md_sections(content: bytes | str) -> List[HacrSection]:
    if isinstance(content, bytes):
        text = _decode_text_content(content).replace("\r\n", "\n").strip()
    else:
        text = (content or "").replace("\r\n", "\n").strip()

    if not text:
        return []

    parts = _split_md_parts(text)

    sections: List[HacrSection] = []
    for index, part in enumerate(parts):
        title, body = _strip_heading(part)
        if not title and index == 0 and len(parts) == 1:
            title = "文档"
        if not title and body:
            title = body.split("\n", 1)[0].strip()[:80] or f"章节 {index + 1}"
        raw_text = part.strip()
        if raw_text:
            sections.append(HacrSection(title=title or f"章节 {index + 1}", body=body or raw_text, raw_text=raw_text))

    return sections
