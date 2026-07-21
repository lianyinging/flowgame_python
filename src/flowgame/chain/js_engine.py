"""JavaScript evaluation for conditions and code nodes."""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# mini-racer 状态：None=未探测, True=可用, False=环境级不可用（硬熔断，进程内不再尝试）
_MINI_RACER_USABLE: Optional[bool] = None
# 连续「不明异常」次数，达到阈值后硬熔断（避免偶发抖动误杀）
_MINI_RACER_UNKNOWN_FAILS: int = 0
_MINI_RACER_UNKNOWN_FAIL_THRESHOLD: int = 3

# 原生库 / 环境不可用的典型信息（硬熔断）
_NATIVE_FAIL_MARKERS = (
    "libmini_racer",
    "mini_racer",
    "cannot open shared object",
    "dlopen",
    "dylib",
    "undefined symbol",
    "image not found",
    "no such file",
    "failed to load",
    "wrong elf class",
)


class JsBusinessError(RuntimeError):
    """用户 JS 业务/语法错误：不应触发引擎熔断。"""


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


def _is_native_or_env_failure(exc: BaseException) -> bool:
    """引擎/原生库不可用（应硬熔断）。"""
    if isinstance(exc, (ImportError, OSError, MemoryError)):
        return True
    name = type(exc).__name__
    if name in {"JSEvalException", "JSParseException", "JsBusinessError"}:
        return False
    text = f"{name}: {exc}".lower()
    return any(marker in text for marker in _NATIVE_FAIL_MARKERS)


def _is_js_business_failure(exc: BaseException) -> bool:
    """用户脚本语法/运行错误（不应熔断）。"""
    if isinstance(exc, JsBusinessError):
        return True
    name = type(exc).__name__
    if name in {"JSEvalException", "JSParseException"}:
        return True
    # mini-racer 有时把 JS 错包成普通 Exception，靠文案识别常见模式
    text = str(exc).lower()
    business_markers = (
        "syntaxerror",
        "referenceerror",
        "typeerror",
        "rangeerror",
        "urierror",
        "evalerror",
        "is not defined",
        "unexpected token",
        "unexpected end",
    )
    if any(m in text for m in business_markers) and not _is_native_or_env_failure(exc):
        return True
    return False


def _mark_mini_racer_dead(reason: str) -> None:
    global _MINI_RACER_USABLE, _MINI_RACER_UNKNOWN_FAILS
    _MINI_RACER_USABLE = False
    _MINI_RACER_UNKNOWN_FAILS = 0
    logger.warning("py-mini-racer 硬熔断，后续改用 Node.js/Python 备选: %s", reason)


def _note_mini_racer_unknown_failure(exc: BaseException) -> bool:
    """
    记录不明异常。返回 True 表示已达到阈值并硬熔断。
    """
    global _MINI_RACER_UNKNOWN_FAILS
    _MINI_RACER_UNKNOWN_FAILS += 1
    logger.warning(
        "py-mini-racer 异常（%s/%s，暂不永久熔断）: %s",
        _MINI_RACER_UNKNOWN_FAILS,
        _MINI_RACER_UNKNOWN_FAIL_THRESHOLD,
        exc,
    )
    if _MINI_RACER_UNKNOWN_FAILS >= _MINI_RACER_UNKNOWN_FAIL_THRESHOLD:
        _mark_mini_racer_dead(f"连续不明异常达 {_MINI_RACER_UNKNOWN_FAIL_THRESHOLD} 次: {exc}")
        return True
    return False


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
try {
  const result = eval(userCode);
  const out = { ok: true, result: result === undefined ? null : result };
  console.log(JSON.stringify(out));
} catch (e) {
  const out = { ok: false, error: String(e && e.stack ? e.stack : e) };
  console.log(JSON.stringify(out));
}
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
        raise JsBusinessError(str(payload.get("error") or "node 执行失败"))
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
    global _MINI_RACER_USABLE, _MINI_RACER_UNKNOWN_FAILS
    bindings = _bindings_from_chain_memory(memory, extra)
    stripped = (code or "").strip()
    if not stripped:
        return None

    if _MINI_RACER_USABLE is not False:
        try:
            result = ensure_json_serializable(_eval_with_mini_racer(stripped, bindings))
            _MINI_RACER_USABLE = True
            _MINI_RACER_UNKNOWN_FAILS = 0
            return result
        except Exception as exc:
            if _is_js_business_failure(exc):
                # 业务/语法错误：不熔断，直接失败当前节点
                raise JsBusinessError(f"JavaScript 执行失败: {exc}") from exc
            if _is_native_or_env_failure(exc):
                _mark_mini_racer_dead(str(exc))
            else:
                # 不明异常：累计后硬熔断；本请求继续尝试备选引擎
                _note_mini_racer_unknown_failure(exc)

    node_exc: Optional[BaseException] = None
    if shutil.which("node"):
        try:
            return ensure_json_serializable(_eval_with_node(stripped, bindings))
        except JsBusinessError:
            raise
        except Exception as exc:
            node_exc = exc
            logger.warning("Node.js 执行动态代码失败: %s", exc)

    if _looks_like_javascript(stripped):
        detail = f" Node 错误: {node_exc}" if node_exc else ""
        raise RuntimeError(
            "JavaScript 动态代码执行失败：py-mini-racer 不可用或已熔断，且 Node.js 备选执行失败。"
            "请检查容器内 Node.js 是否可用，或修复 py-mini-racer 原生库。"
            f"{detail}"
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
