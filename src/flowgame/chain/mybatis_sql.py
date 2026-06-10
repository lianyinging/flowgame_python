"""MyBatis-style SQL template rendering (#{} / ${} + common dynamic tags)."""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

_HASH_PARAM = re.compile(r"#\{([^}]+)\}")
_DOLLAR_PARAM = re.compile(r"\$\{([^}]+)\}")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_ATTR = re.compile(r'(\w+)\s*=\s*"([^"]*)"')


def _parse_attrs(raw: str) -> Dict[str, str]:
    return {m.group(1): m.group(2) for m in _ATTR.finditer(raw or "")}


def _param_name(raw: str) -> str:
    name = (raw or "").strip()
    if not name:
        return ""
    return name.split(",")[0].strip()


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, (list, dict, tuple)) and len(value) == 0:
        return True
    return False


def _eval_test(test: str, params: Dict[str, Any]) -> bool:
    expr = (test or "").strip()
    if not expr:
        return True

    parts = re.split(r"\s+and\s+", expr, flags=re.IGNORECASE)
    for part in parts:
        part = part.strip()
        m = re.fullmatch(r"(\w+)\s*!=\s*null", part, flags=re.IGNORECASE)
        if m:
            if _is_empty(params.get(m.group(1))):
                return False
            continue
        m = re.fullmatch(r"(\w+)\s*==\s*null", part, flags=re.IGNORECASE)
        if m:
            if not _is_empty(params.get(m.group(1))):
                return False
            continue
        m = re.fullmatch(r"(\w+)\s*!=\s*''", part)
        if m:
            value = params.get(m.group(1))
            if value is None or (isinstance(value, str) and value == ""):
                return False
            continue
        m = re.fullmatch(r"(\w+)\.(size|length)\s*>\s*0", part, flags=re.IGNORECASE)
        if m:
            value = params.get(m.group(1))
            if not isinstance(value, (list, dict, tuple, str)) or len(value) == 0:
                return False
            continue
        m = re.fullmatch(r"(\w+)\s*!=\s*null\s+or\s+(\w+)\s*!=\s*''", part, flags=re.IGNORECASE)
        if m:
            value = params.get(m.group(1))
            if _is_empty(value):
                return False
            continue
    return True


def _find_tag_block(text: str, tag: str, start: int = 0) -> Optional[Tuple[int, int, str, str]]:
    open_re = re.compile(rf"<\s*{tag}\b([^>]*)>", re.IGNORECASE)
    close_re = re.compile(rf"<\s*/\s*{tag}\s*>", re.IGNORECASE)
    open_match = open_re.search(text, start)
    if not open_match:
        return None
    depth = 1
    cursor = open_match.end()
    while depth > 0:
        next_open = open_re.search(text, cursor)
        next_close = close_re.search(text, cursor)
        if not next_close:
            return None
        if next_open and next_open.start() < next_close.start():
            depth += 1
            cursor = next_open.end()
            continue
        depth -= 1
        if depth == 0:
            inner = text[open_match.end() : next_close.start()]
            return open_match.start(), next_close.end(), open_match.group(1) or "", inner
        cursor = next_close.end()
    return None


def _apply_where(content: str) -> str:
    body = content.strip()
    if not body:
        return ""
    body = re.sub(r"^\s*(AND|OR)\s+", "", body, count=1, flags=re.IGNORECASE)
    return f" WHERE {body}"


def _apply_trim(
    content: str,
    prefix: str = "",
    suffix: str = "",
    prefix_overrides: str = "",
    suffix_overrides: str = "",
) -> str:
    body = content.strip()
    if not body:
        return ""
    for token in [t.strip() for t in prefix_overrides.split("|") if t.strip()]:
        if body.upper().startswith(token.upper()):
            body = body[len(token) :].lstrip()
            break
    for token in [t.strip() for t in suffix_overrides.split("|") if t.strip()]:
        if body.upper().endswith(token.upper()):
            body = body[: -len(token)].rstrip()
            break
    return f"{prefix}{body}{suffix}"


def _render_foreach(
    attrs: Dict[str, str],
    inner: str,
    params: Dict[str, Any],
    bind_values: List[Any],
) -> str:
    collection_name = attrs.get("collection") or attrs.get("item") or ""
    item_name = attrs.get("item") or "item"
    index_name = attrs.get("index") or "index"
    open_text = attrs.get("open", "")
    separator = attrs.get("separator", ",")
    close_text = attrs.get("close", "")

    collection = params.get(collection_name)
    if collection is None:
        collection = params.get(item_name)
    if not isinstance(collection, (list, tuple)):
        if collection is None or collection == "":
            return ""
        collection = [collection]

    parts: List[str] = []
    for idx, value in enumerate(collection):
        scoped = dict(params)
        scoped[item_name] = value
        scoped[index_name] = idx
        inner_sql = _render_dynamic_sql(inner, scoped, bind_values)
        inner_sql = _substitute_dollar_params(inner_sql, scoped)
        sql_part, vals = _extract_hash_params(inner_sql, scoped)
        bind_values.extend(vals)
        parts.append(sql_part)
    if not parts:
        return ""
    return f"{open_text}{separator.join(parts)}{close_text}"


def _render_choose(inner: str, params: Dict[str, Any], bind_values: List[Any]) -> str:
    cursor = 0
    otherwise_text = ""
    while cursor < len(inner):
        when_block = _find_tag_block(inner, "when", cursor)
        if when_block:
            start, end, attr_raw, body = when_block
            if start > cursor:
                cursor = start
            attrs = _parse_attrs(attr_raw)
            if _eval_test(attrs.get("test", ""), params):
                return _render_dynamic_sql(body, params, bind_values)
            cursor = end
            continue
        otherwise_block = _find_tag_block(inner, "otherwise", cursor)
        if otherwise_block:
            _, end, _, body = otherwise_block
            otherwise_text = body
            cursor = end
            continue
        break
    if otherwise_text:
        return _render_dynamic_sql(otherwise_text, params, bind_values)
    return ""


def _render_dynamic_sql(
    template: str,
    params: Dict[str, Any],
    bind_values: Optional[List[Any]] = None,
) -> str:
    text = _COMMENT.sub("", template or "")
    while True:
        replaced = False

        choose_block = _find_tag_block(text, "choose")
        if choose_block:
            start, end, _, inner = choose_block
            rendered = _render_choose(inner, params, bind_values or [])
            text = text[:start] + rendered + text[end:]
            replaced = True
            continue

        foreach_block = _find_tag_block(text, "foreach")
        if foreach_block:
            start, end, attr_raw, inner = foreach_block
            rendered = _render_foreach(
                _parse_attrs(attr_raw),
                inner,
                params,
                bind_values if bind_values is not None else [],
            )
            text = text[:start] + rendered + text[end:]
            replaced = True
            continue

        if_block = _find_tag_block(text, "if")
        if if_block:
            start, end, attr_raw, inner = if_block
            attrs = _parse_attrs(attr_raw)
            rendered = (
                _render_dynamic_sql(inner, params, bind_values)
                if _eval_test(attrs.get("test", ""), params)
                else ""
            )
            text = text[:start] + rendered + text[end:]
            replaced = True
            continue

        where_block = _find_tag_block(text, "where")
        if where_block:
            start, end, _, inner = where_block
            body = _render_dynamic_sql(inner, params, bind_values)
            rendered = _apply_where(body) if body.strip() else ""
            text = text[:start] + rendered + text[end:]
            replaced = True
            continue

        trim_block = _find_tag_block(text, "trim")
        if trim_block:
            start, end, attr_raw, inner = trim_block
            attrs = _parse_attrs(attr_raw)
            body = _render_dynamic_sql(inner, params, bind_values)
            rendered = (
                _apply_trim(
                    body,
                    prefix=attrs.get("prefix", ""),
                    suffix=attrs.get("suffix", ""),
                    prefix_overrides=attrs.get("prefixOverrides", ""),
                    suffix_overrides=attrs.get("suffixOverrides", ""),
                )
                if body.strip()
                else ""
            )
            text = text[:start] + rendered + text[end:]
            replaced = True
            continue

        if not replaced:
            break
    return text


def _substitute_dollar_params(sql: str, params: Dict[str, Any]) -> str:
    def repl(match: re.Match[str]) -> str:
        key = _param_name(match.group(1))
        value = params.get(key)
        if value is None:
            return ""
        return str(value)

    return _DOLLAR_PARAM.sub(repl, sql)


def _extract_hash_params(sql: str, params: Dict[str, Any]) -> Tuple[str, List[Any]]:
    values: List[Any] = []

    def repl(match: re.Match[str]) -> str:
        key = _param_name(match.group(1))
        values.append(params.get(key))
        return "%s"

    rendered = _HASH_PARAM.sub(repl, sql)
    return rendered, values


def render_mybatis_sql(template: str, params: Dict[str, Any]) -> Tuple[str, List[Any]]:
    """Render MyBatis-style SQL to (sql_with_%s, bind_values)."""
    bind_values: List[Any] = []
    dynamic = _render_dynamic_sql(template, params, bind_values)
    with_dollar = _substitute_dollar_params(dynamic, params)
    sql, vals = _extract_hash_params(with_dollar, params)
    return sql, bind_values + vals


def json_safe_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value.hex()
    if isinstance(value, dict):
        return {k: json_safe_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe_value(v) for v in value]
    return value
