"""从 PDF / DOCX / Markdown 提取纯文本。"""
from __future__ import annotations

import logging
import re
from io import BytesIO
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

ALLOWED_DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".md", ".markdown"}
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024

_MD_HEADING_SPLIT = re.compile(r"(?=^#{1,6}\s)", re.MULTILINE)


class DocumentParseError(Exception):
    pass


def _extension(filename: str) -> str:
    name = (filename or "").strip().lower()
    dot = name.rfind(".")
    return name[dot:] if dot >= 0 else ""


def _parse_pdf(content: bytes) -> List[Tuple[str, Optional[int]]]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise DocumentParseError("服务端未安装 pypdf，无法解析 PDF") from exc

    reader = PdfReader(BytesIO(content))
    segments: List[Tuple[str, Optional[int]]] = []
    for index, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except Exception as exc:
            logger.debug("PDF page extract failed page=%s: %s", index + 1, exc)
            text = ""
        cleaned = text.replace("\r\n", "\n").strip()
        if cleaned:
            segments.append((cleaned, index + 1))
    return segments


def _parse_docx(content: bytes) -> List[Tuple[str, Optional[int]]]:
    try:
        from docx import Document
    except ImportError as exc:
        raise DocumentParseError("服务端未安装 python-docx，无法解析 Word") from exc

    document = Document(BytesIO(content))
    lines = [p.text.strip() for p in document.paragraphs if (p.text or "").strip()]
    if not lines:
        return []
    return [("\n".join(lines), None)]


def _decode_text_content(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _parse_markdown(content: bytes) -> List[Tuple[str, Optional[int]]]:
    text = _decode_text_content(content).replace("\r\n", "\n").strip()
    if not text:
        return []

    sections = [part.strip() for part in _MD_HEADING_SPLIT.split(text) if part.strip()]
    if not sections:
        return [(text, None)]
    return [(section, None) for section in sections]


def extract_document_segments(filename: str, content: bytes) -> List[Tuple[str, Optional[int]]]:
    if not content:
        raise DocumentParseError("文件内容为空")
    if len(content) > MAX_DOCUMENT_BYTES:
        raise DocumentParseError(f"文件超过 {MAX_DOCUMENT_BYTES // (1024 * 1024)}MB 限制")

    ext = _extension(filename)
    if ext not in ALLOWED_DOCUMENT_EXTENSIONS:
        raise DocumentParseError("仅支持 .pdf、.docx、.md 文件")

    if ext == ".pdf":
        segments = _parse_pdf(content)
    elif ext in (".md", ".markdown"):
        segments = _parse_markdown(content)
    else:
        segments = _parse_docx(content)

    if not segments:
        raise DocumentParseError("未能从文件中提取到有效文本，请确认文件含可选中文字")

    return segments
