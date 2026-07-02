"""启动时打印基础设施连接配置（不含密码/密钥明文）。"""
from __future__ import annotations

import logging
import os

from src.flowgame.settings import get_flowgame_settings

_LOGGER_NAME = "flowgame.startup"
_CONFIGURED = False


def _secret_status(value: str | None) -> str:
    return "set" if value and str(value).strip() else "empty"


def configure_startup_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    logger = logging.getLogger(_LOGGER_NAME)
    if not logger.handlers:
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

    _CONFIGURED = True


def get_infra_logger() -> logging.Logger:
    configure_startup_logging()
    return logging.getLogger(_LOGGER_NAME)


def log_infrastructure_config() -> None:
    """在 load_flowgame_dotenv() 之后调用一次。"""
    configure_startup_logging()
    logger = get_infra_logger()
    cfg = get_flowgame_settings()
    app_env = os.getenv("APP_ENV", "").strip() or "(unset)"

    if cfg.mysql_host:
        logger.info(
            "MySQL host=%s port=%s user=%s database=%s charset=%s password=%s",
            cfg.mysql_host,
            cfg.mysql_port,
            cfg.mysql_user or "(unset)",
            cfg.mysql_database or "(unset)",
            cfg.mysql_charset,
            _secret_status(cfg.mysql_password),
        )
    else:
        logger.info("MySQL not configured (MYSQL_HOST empty)")

    logger.info(
        "Redis host=%s port=%s db=%s keyPrefix=%s password=%s",
        cfg.redis_host,
        cfg.redis_port,
        cfg.redis_db,
        cfg.redis_key_prefix,
        _secret_status(cfg.redis_password),
    )

    logger.info(
        "Qdrant host=%s port=%s timeout=%ss kbPrefix=%s embeddingApi=%s",
        cfg.qdrant_host,
        cfg.qdrant_port,
        cfg.qdrant_timeout,
        cfg.qdrant_kb_prefix,
        cfg.embedding_api_url or "(local)",
    )

    if cfg.oss_endpoint and cfg.oss_bucket:
        logger.info(
            "OSS endpoint=%s bucket=%s keyPrefix=%s publicRead=%s publicBaseUrl=%s accessKey=%s secret=%s",
            cfg.oss_endpoint,
            cfg.oss_bucket,
            cfg.oss_key_prefix,
            cfg.oss_public_read,
            cfg.oss_public_base_url or "(unset)",
            _secret_status(cfg.oss_access_key_id),
            _secret_status(cfg.oss_access_key_secret),
        )
    else:
        logger.info("OSS not configured (OSS_ENDPOINT or OSS_BUCKET empty)")

    logger.info("APP_ENV=%s", app_env)
