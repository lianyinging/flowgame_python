"""工作流执行过程日志（由环境变量开关与路径控制）。"""
from __future__ import annotations

import json
import logging
import os
import re
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any, List, Optional

_LOGGER_NAME = "flowgame.execution"
_FILE_LOGGER_NAME = "flowgame.execution.file"
_CONSOLE_LOGGER_NAME = "flowgame.execution.console"
_DATABASE_SQL_LOGGER_NAME = "flowgame.database"
_CONFIGURED = False
_DATABASE_SQL_LOGGER_CONFIGURED = False

# 写文件：默认可看全量；控制台：默认短一些，避免刷屏
_DEFAULT_FILE_FIELD_MAX_LEN = 50000
_DEFAULT_CONSOLE_FIELD_MAX_LEN = 800
_DEFAULT_BACKUP_COUNT = 5

# flowgame-execution-2026-07-29.log
_DAILY_LOG_NAME_RE = re.compile(
    r"^(?P<stem>.+)-(?P<date>\d{4}-\d{2}-\d{2})\.log$"
)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_int_optional(name: str) -> Optional[int]:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def is_execution_logging_enabled() -> bool:
    return _env_bool("FLOWGAME_EXECUTION_LOG_ENABLED", False)


def _daily_log_namer(default_name: str) -> str:
    """把 TimedRotating 默认的 base.log.YYYY-MM-DD 改成 base-YYYY-MM-DD.log。"""
    # 例：/path/flowgame-execution.log.2026-07-29
    #  → /path/flowgame-execution-2026-07-29.log
    path = Path(default_name)
    m = re.match(r"^(?P<stem>.+)\.log\.(?P<date>\d{4}-\d{2}-\d{2})$", path.name)
    if not m:
        return default_name
    return str(path.with_name(f"{m.group('stem')}-{m.group('date')}.log"))


def _daily_log_rotator(source: str, dest: str) -> None:
    src = Path(source)
    dst = Path(dest)
    if not src.exists():
        return
    if dst.exists():
        dst.unlink()
    src.rename(dst)


class DailyExecutionFileHandler(TimedRotatingFileHandler):
    """按自然日滚动；历史文件名为 stem-YYYY-MM-DD.log，并按 backupCount 清理。"""

    def getFilesToDelete(self) -> List[str]:  # noqa: N802  (logging API)
        dir_name = Path(self.baseFilename).parent
        stem = Path(self.baseFilename).stem  # flowgame-execution
        candidates: List[tuple[str, str]] = []
        for path in dir_name.iterdir():
            if not path.is_file():
                continue
            m = _DAILY_LOG_NAME_RE.match(path.name)
            if not m or m.group("stem") != stem:
                continue
            candidates.append((m.group("date"), str(path)))
        candidates.sort(key=lambda x: x[0])
        if self.backupCount <= 0:
            return [p for _, p in candidates]
        excess = len(candidates) - self.backupCount
        if excess <= 0:
            return []
        return [p for _, p in candidates[:excess]]


def configure_execution_logging() -> None:
    """在 load_flowgame_dotenv() 之后调用一次。"""
    global _CONFIGURED
    if _CONFIGURED:
        return

    file_logger = logging.getLogger(_FILE_LOGGER_NAME)
    console_logger = logging.getLogger(_CONSOLE_LOGGER_NAME)

    for lg in (file_logger, console_logger):
        lg.handlers.clear()
        lg.propagate = False

    if not is_execution_logging_enabled():
        _CONFIGURED = True
        return

    log_path = os.getenv(
        "FLOWGAME_EXECUTION_LOG_PATH", "logs/flowgame-execution.log"
    ).strip()
    level_name = os.getenv("FLOWGAME_EXECUTION_LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    console = _env_bool("FLOWGAME_EXECUTION_LOG_CONSOLE", True)
    backup_count = max(0, _env_int("FLOWGAME_EXECUTION_LOG_BACKUP_COUNT", _DEFAULT_BACKUP_COUNT))

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    log_file = Path(log_path)
    if not log_file.is_absolute():
        root = Path(__file__).resolve().parents[2]
        log_file = root / log_file
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # 当天写 base.log；零点滚成 base-YYYY-MM-DD.log
    # BACKUP_COUNT = 保留的历史日文件数（不含当天正在写的 base.log）
    file_handler = DailyExecutionFileHandler(
        filename=str(log_file),
        when="midnight",
        interval=1,
        backupCount=backup_count,
        encoding="utf-8",
        utc=False,
        delay=False,
    )
    file_handler.suffix = "%Y-%m-%d"
    file_handler.extMatch = re.compile(r"^\d{4}-\d{2}-\d{2}(\.\w+)?$", re.ASCII)
    file_handler.namer = _daily_log_namer
    file_handler.rotator = _daily_log_rotator
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)
    file_logger.addHandler(file_handler)
    file_logger.setLevel(level)

    if console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(level)
        console_logger.addHandler(console_handler)
        console_logger.setLevel(level)

    _CONFIGURED = True
    file_logger.info(
        "execution logging enabled path=%s rotate=daily backupCount=%s "
        "fileFieldMaxLen=%s consoleFieldMaxLen=%s",
        log_file,
        backup_count,
        _file_field_max_len(),
        _console_field_max_len(),
    )


def get_execution_logger() -> logging.Logger:
    """兼容旧接口：默认走文件 logger。"""
    return logging.getLogger(_FILE_LOGGER_NAME)


def get_database_sql_logger() -> logging.Logger:
    """数据库节点最终 SQL 的控制台日志（默认开启）。"""
    global _DATABASE_SQL_LOGGER_CONFIGURED
    logger = logging.getLogger(_DATABASE_SQL_LOGGER_NAME)
    if not _DATABASE_SQL_LOGGER_CONFIGURED:
        if not _env_bool("FLOWGAME_DATABASE_SQL_LOG_ENABLED", True):
            logger.disabled = True
            _DATABASE_SQL_LOGGER_CONFIGURED = True
            return logger
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        _DATABASE_SQL_LOGGER_CONFIGURED = True
    return logger


def _file_field_max_len() -> int:
    """写文件时单字段最大字符。

    - FLOWGAME_EXECUTION_LOG_FILE_FIELD_MAX_LEN（优先）
    - 否则回退 FLOWGAME_EXECUTION_LOG_FIELD_MAX_LEN（兼容旧配置）
    - 默认 50000；0 或负数 = 不截断
    """
    specific = _env_int_optional("FLOWGAME_EXECUTION_LOG_FILE_FIELD_MAX_LEN")
    if specific is not None:
        return specific
    legacy = _env_int_optional("FLOWGAME_EXECUTION_LOG_FIELD_MAX_LEN")
    if legacy is not None:
        return legacy
    return _DEFAULT_FILE_FIELD_MAX_LEN


def _console_field_max_len() -> int:
    """控制台打印时单字段最大字符。

    - FLOWGAME_EXECUTION_LOG_CONSOLE_FIELD_MAX_LEN（优先）
    - 否则回退 FLOWGAME_EXECUTION_LOG_FIELD_MAX_LEN（兼容旧配置）
    - 默认 800；0 或负数 = 不截断
    """
    specific = _env_int_optional("FLOWGAME_EXECUTION_LOG_CONSOLE_FIELD_MAX_LEN")
    if specific is not None:
        return specific
    legacy = _env_int_optional("FLOWGAME_EXECUTION_LOG_FIELD_MAX_LEN")
    if legacy is not None:
        return legacy
    return _DEFAULT_CONSOLE_FIELD_MAX_LEN


def _truncate_for_log(value: Any, max_len: int) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        text = str(value)
    if max_len <= 0 or len(text) <= max_len:
        return text
    return f"{text[:max_len]}…(truncated,len={len(text)})"


def _emit_execution(message: str, *, field_value: Any = None, field_prefix: str = "") -> None:
    """同一条事件分别按文件/控制台长度截断后写出。"""
    file_logger = logging.getLogger(_FILE_LOGGER_NAME)
    console_logger = logging.getLogger(_CONSOLE_LOGGER_NAME)

    if field_value is None:
        if file_logger.handlers:
            file_logger.info(message)
        if console_logger.handlers:
            console_logger.info(message)
        return

    if file_logger.handlers:
        file_logger.info(
            "%s %s%s",
            message,
            field_prefix,
            _truncate_for_log(field_value, _file_field_max_len()),
        )
    if console_logger.handlers:
        console_logger.info(
            "%s %s%s",
            message,
            field_prefix,
            _truncate_for_log(field_value, _console_field_max_len()),
        )


def log_workflow_event(
    event: str,
    *,
    message: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
    flow_name: Optional[str] = None,
    method_key: Optional[str] = None,
) -> None:
    file_logger = logging.getLogger(_FILE_LOGGER_NAME)
    console_logger = logging.getLogger(_CONSOLE_LOGGER_NAME)
    if not file_logger.handlers and not console_logger.handlers:
        return

    label = (flow_name or method_key or "").strip() or "(未命名流程)"
    mk = (method_key or "").strip()

    # 开始/结束/错误：醒目分隔线，便于 Team 多流程交替时辨认
    if event in ("workflow_started", "workflow_finished", "workflow_error"):
        if event == "workflow_started":
            mark = "▶ START"
        elif event == "workflow_finished":
            mark = "■ END  "
        else:
            mark = "✖ ERROR"
        banner = (
            f"========== {mark} | 流程={label}"
            + (f" | methodKey={mk}" if mk and mk != label else "")
            + " =========="
        )
        _emit_execution(banner)

    parts = [f"event={event}", f"flowName={label}"]
    if mk:
        parts.append(f"methodKey={mk}")
    if message:
        parts.append(message)
    base = " ".join(parts)
    if extra:
        _emit_execution(base, field_value=extra, field_prefix="")
    else:
        _emit_execution(base)


def log_database_sql(
    *,
    node_id: Optional[str] = None,
    node_name: Optional[str] = None,
    sql: str,
) -> None:
    """数据库节点执行完成后记录最终 SQL。"""
    label = node_name or node_id or "databaseNode"
    console_logger = get_database_sql_logger()
    if not getattr(console_logger, "disabled", False):
        console_logger.info("DatabaseNode[%s] executed SQL: %s", label, sql)

    file_logger = logging.getLogger(_FILE_LOGGER_NAME)
    exec_console = logging.getLogger(_CONSOLE_LOGGER_NAME)
    if not file_logger.handlers and not exec_console.handlers:
        return
    parts = ["event=database_sql_executed"]
    if node_id:
        parts.append(f"nodeId={node_id}")
    if node_name:
        parts.append(f"nodeName={node_name}")
    # SQL 本身也可能很长：按文件/控制台分别截断
    _emit_execution(" ".join(parts), field_value=sql, field_prefix="sql=")


def log_node_event(
    event: str,
    *,
    node_id: Optional[str] = None,
    node_name: Optional[str] = None,
    node_type: Optional[str] = None,
    status: Optional[str] = None,
    duration_ms: Optional[int] = None,
    error: Optional[str] = None,
    output: Optional[Any] = None,
) -> None:
    file_logger = logging.getLogger(_FILE_LOGGER_NAME)
    console_logger = logging.getLogger(_CONSOLE_LOGGER_NAME)
    if not file_logger.handlers and not console_logger.handlers:
        return
    parts = [f"event={event}"]
    if node_id:
        parts.append(f"nodeId={node_id}")
    if node_name:
        parts.append(f"nodeName={node_name}")
    if node_type:
        parts.append(f"nodeType={node_type}")
    if status:
        parts.append(f"status={status}")
    if duration_ms is not None:
        parts.append(f"durationMs={duration_ms}")
    if error:
        parts.append(f"error={error}")
    base = " ".join(parts)
    if output is not None:
        _emit_execution(base, field_value=output, field_prefix="output=")
    else:
        _emit_execution(base)
