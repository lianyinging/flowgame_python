"""{{ variable }} template formatting (TextPromptTemplate port)."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

_PLACEHOLDER = re.compile(r"\{\{\s*(.+?)\s*}}")


def _get_by_path(root: Dict[str, Any], path: str) -> Any:
    if not path:
        return None
    parts = path.split(".")
    current: Any = root
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
        if current is None:
            return None
    return current


def format_template(template: Optional[str], root_map: Optional[Dict[str, Any]] = None) -> str:
    if not template:
        return ""
    root = root_map or {}

    def replacer(match: re.Match) -> str:
        content = match.group(1).strip()
        parts = re.split(r"\s*\?\?\s*", content, maxsplit=1)
        expr = parts[0].strip()
        default = ""
        if len(parts) == 2:
            default_raw = parts[1].strip()
            if (default_raw.startswith("'") and default_raw.endswith("'")) or (
                default_raw.startswith('"') and default_raw.endswith('"')
            ):
                default = default_raw[1:-1]
            else:
                default = default_raw
        value = _get_by_path(root, expr)
        if value is None:
            return default
        if isinstance(value, (dict, list)):
            try:
                return json.dumps(value, ensure_ascii=False, default=str)
            except TypeError:
                return str(value)
        return str(value)

    return _PLACEHOLDER.sub(replacer, template)
