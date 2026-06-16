"""OSS file type metadata for upload Content-Type and extension."""
from __future__ import annotations

from typing import Dict, Tuple

FILE_TYPE_META: Dict[str, Tuple[str, str]] = {
    "image": ("image/png", ".png"),
    "html": ("text/html; charset=utf-8", ".html"),
    "txt": ("text/plain; charset=utf-8", ".txt"),
    "json": ("application/json; charset=utf-8", ".json"),
    "xml": ("application/xml; charset=utf-8", ".xml"),
    "css": ("text/css; charset=utf-8", ".css"),
    "js": ("application/javascript; charset=utf-8", ".js"),
}

DEFAULT_FILE_TYPE = "txt"


def resolve_file_type_meta(file_type: str) -> Tuple[str, str]:
    key = (file_type or DEFAULT_FILE_TYPE).strip().lower()
    return FILE_TYPE_META.get(key, FILE_TYPE_META[DEFAULT_FILE_TYPE])
