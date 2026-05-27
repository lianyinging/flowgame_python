"""文档文本分块（优先按段落，再按字符上限）。"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n+")


def _merge_paragraphs(paragraphs: List[str], max_size: int) -> List[str]:
    """合并过短段落，避免碎片过多。"""
    merged: List[str] = []
    buffer = ""
    for para in paragraphs:
        piece = para.strip()
        if not piece:
            continue
        if not buffer:
            buffer = piece
            continue
        if len(buffer) + len(piece) + 1 <= max_size:
            buffer = f"{buffer}\n{piece}"
        else:
            merged.append(buffer)
            buffer = piece
    if buffer:
        merged.append(buffer)
    return merged


def chunk_text(
    text: str,
    *,
    chunk_size: int = 600,
    overlap: int = 80,
) -> List[str]:
    normalized = (text or "").replace("\r\n", "\n").strip()
    if not normalized:
        return []

    size = max(200, chunk_size)
    ov = max(0, min(overlap, size // 3))

    paragraphs = [p.strip() for p in _PARAGRAPH_BREAK.split(normalized) if p.strip()]
    if not paragraphs:
        paragraphs = [normalized]

    units = _merge_paragraphs(paragraphs, size)
    chunks: List[str] = []

    for unit in units:
        if len(unit) <= size:
            chunks.append(unit)
            continue
        start = 0
        length = len(unit)
        while start < length:
            end = min(start + size, length)
            piece = unit[start:end].strip()
            if piece:
                chunks.append(piece)
            if end >= length:
                break
            start = max(0, end - ov)

    return chunks


def chunk_segments(
    segments: List[Tuple[str, Optional[int]]],
    *,
    chunk_size: int = 600,
    overlap: int = 80,
) -> List[Tuple[str, Optional[int]]]:
    result: List[Tuple[str, Optional[int]]] = []
    for segment_text, page in segments:
        for chunk in chunk_text(segment_text, chunk_size=chunk_size, overlap=overlap):
            result.append((chunk, page))
    return result
