"""工作流执行过程日志（由环境变量开关与路径控制）。"""
from __future__ import annotations

import json
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Optional

_LOGGER_NAME = "flowgame.execution"
_DATABASE_SQL_LOGGER_NAME = "flowgame.database"
_CONFIGURED = False
_DATABASE_SQL_LOGGER_CONFIGURED = False


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


def is_execution_logging_enabled() -> bool:
    return _env_bool("FLOWGAME_EXECUTION_LOG_ENABLED", False)


def configure_execution_logging() -> None:
    """在 load_flowgame_dotenv() 之后调用一次。"""
    global _CONFIGURED
    if _CONFIGURED:
        return

    logger = logging.getLogger(_LOGGER_NAME)
    logger.handlers.clear()
    logger.propagate = False

    if not is_execution_logging_enabled():
        _CONFIGURED = True
        return

    log_path = os.getenv(
        "FLOWGAME_EXECUTION_LOG_PATH", "logs/flowgame-execution.log"
    ).strip()
    level_name = os.getenv("FLOWGAME_EXECUTION_LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    console = _env_bool("FLOWGAME_EXECUTION_LOG_CONSOLE", True)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    log_file = Path(log_path)
    if not log_file.is_absolute():
        root = Path(__file__).resolve().parents[2]
        log_file = root / log_file
    log_file.parent.mkdir(parents=True, exist_ok=True)

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=_env_int("FLOWGAME_EXECUTION_LOG_MAX_BYTES", 5 * 1024 * 1024),
        backupCount=_env_int("FLOWGAME_EXECUTION_LOG_BACKUP_COUNT", 5),
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)
    logger.addHandler(file_handler)

    if console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(level)
        logger.addHandler(console_handler)

    logger.setLevel(level)
    _CONFIGURED = True
    logger.info("execution logging enabled path=%s", log_file)


def get_execution_logger() -> logging.Logger:
    return logging.getLogger(_LOGGER_NAME)


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


def _truncate_for_log(value: Any, max_len: int = 800) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        text = str(value)
    if len(text) <= max_len:
        return text
    return f"{text[:max_len]}…(truncated)"


def log_workflow_event(
    event: str,
    *,
    message: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
) -> None:
    logger = get_execution_logger()
    if not logger.handlers:
        return
    parts = [f"event={event}"]
    if message:
        parts.append(message)
    if extra:
        parts.append(_truncate_for_log(extra))
    logger.info(" ".join(parts))


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

    logger = get_execution_logger()
    if not logger.handlers:
        return
    parts = ["event=database_sql_executed"]
    if node_id:
        parts.append(f"nodeId={node_id}")
    if node_name:
        parts.append(f"nodeName={node_name}")
    parts.append(f"sql={sql}")
    logger.info(" ".join(parts))


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
    logger = get_execution_logger()
    if not logger.handlers:
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
    if output is not None:
        parts.append(f"output={_truncate_for_log(output)}")
    logger.info(" ".join(parts))
