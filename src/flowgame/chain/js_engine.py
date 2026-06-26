"""JavaScript evaluation for conditions and code nodes."""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# py-mini-racer 原生库缺失时置为 False，后续直接走备选引擎
_MINI_RACER_USABLE: Optional[bool] = None


def _bindings_from_chain_memory(memory: Dict[str, Any], extra: Dict[str, Any] | None = None) -> Dict[str, Any]:
    params: Dict[str, Any] = {}
    for key, value in memory.items():
        dot = key.find(".")
        if dot >= 0:
            params[key[dot + 1 :]] = value
        else:
            params[key] = value
    if extra:
        params.update(extra)
    return params


def eval_js_bool(code: str, memory: Dict[str, Any], extra: Dict[str, Any] | None = None) -> bool:
    result = eval_js(code, memory, extra)
    if result is None:
        return False
    result_str = str(result).lower().strip()
    return result_str not in ("0", "false", "")


def _looks_like_javascript(code: str) -> bool:
    markers = ("var ", "let ", "const ", "function ", "=>", "new Date", "JSON.", "===", "!==")
    return any(marker in code for marker in markers)


def ensure_json_serializable(value: Any) -> Any:
    """将 JS 引擎产物（如 JSObject）等转为可 json.dumps 的 Python 值。"""
    try:
        json.dumps(value)
        return value
    except TypeError:
        pass

    if isinstance(value, dict):
        return {str(k): ensure_json_serializable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [ensure_json_serializable(item) for item in value]

    type_name = type(value).__name__
    if type_name in {"JSObject", "JSFunction", "JSSymbol"}:
        return None
    return str(value)


def _eval_with_mini_racer(code: str, bindings: Dict[str, Any]) -> Any:
    from py_mini_racer import py_mini_racer

    ctx = py_mini_racer.MiniRacer()
    ctx.eval("var _chain = null; var _edge = null; var _context = null;")
    for key, value in bindings.items():
        ctx.eval(f"var {key} = {json.dumps(value, ensure_ascii=False, default=str)};")
    # eval() 对 object/array 会返回 JSObject，流式进度 json.dumps 会失败；统一 JSON 往返。
    code_literal = json.dumps(code, ensure_ascii=False)
    ctx.eval(f"var __last_eval_result__ = eval({code_literal});")
    json_str = ctx.eval(
        "JSON.stringify(__last_eval_result__ === undefined ? null : __last_eval_result__)"
    )
    if json_str is None:
        return None
    return json.loads(json_str)


def _eval_with_node(code: str, bindings: Dict[str, Any]) -> Any:
    node = shutil.which("node")
    if not node:
        raise RuntimeError(
            "JavaScript 引擎不可用：请执行 pip install --force-reinstall py-mini-racer，"
            "或安装 Node.js 后重试。"
        )
    # 通过 stdin 传参，避免工作流 memory 过大时 argv 超过系统 ARG_MAX（Argument list too long）
    script = r"""
const fs = require('fs');
const { bindings, userCode } = JSON.parse(fs.readFileSync(0, 'utf8'));
for (const [k, v] of Object.entries(bindings)) globalThis[k] = v;
const result = eval(userCode);
const out = { ok: true, result: result === undefined ? null : result };
console.log(JSON.stringify(out));
"""
    payload = json.dumps(
        {"bindings": bindings, "userCode": code},
        ensure_ascii=False,
        default=str,
    )
    proc = subprocess.run(
        [node, "-e", script],
        input=payload,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "node 执行失败").strip()
        raise RuntimeError(err)
    try:
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as exc:
        raise RuntimeError(f"node 返回无法解析: {proc.stdout!r}") from exc
    if not payload.get("ok"):
        raise RuntimeError(str(payload.get("error") or "node 执行失败"))
    return payload.get("result")


def _eval_as_python(code: str, bindings: Dict[str, Any]) -> Any:
    """无 JS 引擎时尝试按 Python 执行（仅适合简单表达式）。"""
    local_vars = dict(bindings)
    try:
        return eval(code, {"__builtins__": {}}, local_vars)
    except SyntaxError:
        exec_globals = {"__builtins__": __builtins__}
        exec_globals.update(bindings)
        local_result: Dict[str, Any] = {}
        exec(code, exec_globals, local_result)
        if "result" in local_result:
            return local_result["result"]
        return local_result


def eval_js(code: str, memory: Dict[str, Any], extra: Dict[str, Any] | None = None) -> Any:
    global _MINI_RACER_USABLE
    bindings = _bindings_from_chain_memory(memory, extra)
    stripped = (code or "").strip()
    if not stripped:
        return None

    if _MINI_RACER_USABLE is not False:
        try:
            result = ensure_json_serializable(_eval_with_mini_racer(stripped, bindings))
            _MINI_RACER_USABLE = True
            return result
        except ImportError as exc:
            _MINI_RACER_USABLE = False
            logger.warning("py-mini-racer 未安装，动态代码将使用备选引擎: %s", exc)
        except Exception as exc:
            _MINI_RACER_USABLE = False
            logger.warning(
                "py-mini-racer 不可用（%s），动态代码将使用 Node.js 或 Python 备选",
                exc,
            )

    if shutil.which("node"):
        try:
            return ensure_json_serializable(_eval_with_node(stripped, bindings))
        except Exception as exc:
            logger.warning("Node.js 执行动态代码失败: %s", exc)

    if _looks_like_javascript(stripped):
        raise RuntimeError(
            "JavaScript 动态代码执行失败：py-mini-racer 不可用，且 Node.js 备选执行失败。"
            "请检查容器内 Node.js 是否可用，或修复 py-mini-racer 原生库。"
        )

    try:
        return _eval_as_python(stripped, bindings)
    except Exception as exc:
        raise RuntimeError(
            "动态代码执行失败：本机 py-mini-racer 原生库不可用，且代码无法按 Python 解析。"
            "请执行: pip install --force-reinstall py-mini-racer；"
            "或将代码改为 Python 语法 / 安装 Node.js。"
            f" 原始错误: {exc}"
        ) from exc
