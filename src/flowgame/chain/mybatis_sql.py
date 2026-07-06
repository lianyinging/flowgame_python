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


def _param_modifier(raw: str) -> str:
    parts = [p.strip().lower() for p in (raw or "").strip().split(",") if p.strip()]
    if len(parts) < 2:
        return ""
    return parts[1]


def _parse_test_literal(raw: str) -> Any:
    text = (raw or "").strip()
    if not text:
        return ""
    if (text.startswith("'") and text.endswith("'")) or (
        text.startswith('"') and text.endswith('"')
    ):
        inner = text[1:-1]
        if text[0] == "'":
            return inner.replace("\\'", "'")
        return inner.replace('\\"', '"')
    lower = text.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d+\.\d+", text):
        return float(text)
    return text


def _values_equal(actual: Any, expected: Any) -> bool:
    if actual is None and expected is None:
        return True
    if actual is None or expected is None:
        return False
    if isinstance(expected, bool) and not isinstance(actual, bool):
        if isinstance(actual, str):
            normalized = actual.strip().lower()
            if normalized in ("true", "1", "yes", "on"):
                return expected is True
            if normalized in ("false", "0", "no", "off", ""):
                return expected is False
        if isinstance(actual, (int, float)) and not isinstance(actual, bool):
            return bool(actual) == expected
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        if isinstance(actual, str) and actual.strip().isdigit():
            try:
                return float(actual) == float(expected)
            except ValueError:
                pass
    return str(actual) == str(expected)


def _apply_bind_modifier(value: Any, modifier: str) -> Any:
    mode = (modifier or "").strip().lower()
    if not mode:
        return value
    if value is None:
        return None
    text = str(value)
    if not text:
        return text
    if mode == "like":
        if any(ch in text for ch in ("%", "_")):
            return text
        return f"%{text}%"
    if mode == "likeleft":
        return text if text.startswith("%") else f"%{text}"
    if mode == "likeright":
        return text if text.endswith("%") else f"{text}%"
    return value


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, (list, dict, tuple)) and len(value) == 0:
        return True
    return False


def _eval_single_test(part: str, params: Dict[str, Any]) -> bool:
    part = (part or "").strip()
    if not part:
        return True

    m = re.fullmatch(r"(\w+)\s*!=\s*null", part, flags=re.IGNORECASE)
    if m:
        return not _is_empty(params.get(m.group(1)))

    m = re.fullmatch(r"(\w+)\s*==\s*null", part, flags=re.IGNORECASE)
    if m:
        return _is_empty(params.get(m.group(1)))

    m = re.fullmatch(r"(\w+)\s*!=\s*''", part)
    if m:
        value = params.get(m.group(1))
        return not (value is None or (isinstance(value, str) and value == ""))

    m = re.fullmatch(r"(\w+)\s*==\s*''", part)
    if m:
        value = params.get(m.group(1))
        return value is None or (isinstance(value, str) and value == "")

    m = re.fullmatch(r"(\w+)\.(size|length)\s*>\s*0", part, flags=re.IGNORECASE)
    if m:
        value = params.get(m.group(1))
        return isinstance(value, (list, dict, tuple, str)) and len(value) > 0

    m = re.fullmatch(r"(\w+)\s*!=\s*null\s+or\s+(\w+)\s*!=\s*''", part, flags=re.IGNORECASE)
    if m:
        return not _is_empty(params.get(m.group(1)))

    m = re.fullmatch(
        r"(\w+)\s*==\s*('(?:\\'|[^'])*'|\"(?:\\\"|[^\"])*\"|-?\d+(?:\.\d+)?|true|false)",
        part,
        flags=re.IGNORECASE,
    )
    if m:
        expected = _parse_test_literal(m.group(2))
        return _values_equal(params.get(m.group(1)), expected)

    m = re.fullmatch(
        r"(\w+)\s*!=\s*('(?:\\'|[^'])*'|\"(?:\\\"|[^\"])*\"|-?\d+(?:\.\d+)?|true|false)",
        part,
        flags=re.IGNORECASE,
    )
    if m:
        expected = _parse_test_literal(m.group(2))
        return not _values_equal(params.get(m.group(1)), expected)

    return False


def _eval_test(test: str, params: Dict[str, Any]) -> bool:
    expr = (test or "").strip()
    if not expr:
        return True

    parts = re.split(r"\s+and\s+", expr, flags=re.IGNORECASE)
    return all(_eval_single_test(part.strip(), params) for part in parts if part.strip())


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
        raw = match.group(1)
        key = _param_name(raw)
        value = _apply_bind_modifier(params.get(key), _param_modifier(raw))
        values.append(value)
        return "%s"

    rendered = _HASH_PARAM.sub(repl, sql)
    return rendered, values


def escape_pymysql_percent_literals(sql: str) -> str:
    """将 SQL 中非占位符的 % 转义为 %%，避免 pymysql 参数绑定时误解析。"""
    parts: List[str] = []
    i = 0
    text = sql or ""
    while i < len(text):
        if text[i : i + 2] == "%s":
            parts.append("%s")
            i += 2
            continue
        if text[i] == "%":
            parts.append("%%")
            i += 1
            continue
        parts.append(text[i])
        i += 1
    return "".join(parts)


def render_mybatis_sql(template: str, params: Dict[str, Any]) -> Tuple[str, List[Any]]:
    """Render MyBatis-style SQL to (sql_with_%s, bind_values)."""
    bind_values: List[Any] = []
    dynamic = _render_dynamic_sql(template, params, bind_values)
    with_dollar = _substitute_dollar_params(dynamic, params)
    sql, vals = _extract_hash_params(with_dollar, params)
    return escape_pymysql_percent_literals(sql), bind_values + vals


def split_sql_statements(sql: str) -> List[str]:
    """按分号拆分多条 SQL，忽略字符串字面量内的分号。"""
    text = (sql or "").strip()
    if not text:
        return []

    statements: List[str] = []
    current: List[str] = []
    in_single = False
    in_double = False
    in_backtick = False
    escape = False
    i = 0
    length = len(text)

    while i < length:
        ch = text[i]
        if escape:
            current.append(ch)
            escape = False
            i += 1
            continue
        if ch == "\\" and (in_single or in_double):
            escape = True
            current.append(ch)
            i += 1
            continue
        if ch == "'" and not in_double and not in_backtick:
            in_single = not in_single
            current.append(ch)
            i += 1
            continue
        if ch == '"' and not in_single and not in_backtick:
            in_double = not in_double
            current.append(ch)
            i += 1
            continue
        if ch == "`" and not in_single and not in_double:
            in_backtick = not in_backtick
            current.append(ch)
            i += 1
            continue
        if ch == ";" and not in_single and not in_double and not in_backtick:
            stmt = "".join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
            i += 1
            continue
        current.append(ch)
        i += 1

    stmt = "".join(current).strip()
    if stmt:
        statements.append(stmt)
    return statements


def split_bind_values_for_statements(
    statements: List[str],
    bind_values: List[Any],
) -> List[List[Any]]:
    """按每条语句中的 %s 数量切分预编译参数（与 pymysql.execute 一致）。"""
    grouped: List[List[Any]] = []
    offset = 0
    for stmt in statements:
        count = stmt.count("%s")
        grouped.append(list(bind_values[offset:offset + count]))
        offset += count
    if offset != len(bind_values):
        raise ValueError(
            f"SQL 预编译参数数量不匹配：模板产生 {len(bind_values)} 个，语句需要 {offset} 个"
        )
    return grouped


def _is_select_statement(sql_text: str) -> bool:
    return sql_text.lstrip().upper().startswith("SELECT")


def format_executed_sql(sql: str, binds: List[Any], *, cursor: Any = None) -> str:
    """将预编译 SQL 与绑定参数格式化为可读的完整语句（仅用于日志/调试）。"""
    if cursor is not None:
        try:
            raw = cursor.mogrify(sql, binds or ())
        except Exception:
            raw = None
        if raw is not None:
            if isinstance(raw, bytes):
                return raw.decode("utf-8", errors="replace")
            return str(raw)

    from pymysql.converters import escape_item

    charset = "utf8mb4"
    parts: List[str] = []
    bind_iter = iter(binds or [])
    i = 0
    text = sql or ""
    while i < len(text):
        if text[i : i + 2] == "%%":
            parts.append("%")
            i += 2
            continue
        if text[i : i + 2] == "%s":
            parts.append(escape_item(next(bind_iter, None), charset))
            i += 2
            continue
        parts.append(text[i])
        i += 1
    return "".join(parts)


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
