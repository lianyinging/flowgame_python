"""Render talk HTML pages from Jinja2 templates."""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.flowgame.constants import API_PREFIX
from src.flowgame.key_prefix import get_redis_key_prefix
from src.flowgame.workflow_talk_rules import resolve_talk_template

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)


def render_talk_page(
    *,
    method_key: str,
    talk_title: str = "",
    welcome_message: str = "",
    talk_template: str = "default",
    session_id: str = "",
    api_prefix: str = API_PREFIX,
    redis_key_prefix: str = "",
) -> str:
    template_name = f"{resolve_talk_template(talk_template)}.html"
    template = _env.get_template(template_name)
    return template.render(
        method_key=method_key,
        talk_title=(talk_title or "对话").strip() or "对话",
        welcome_message=welcome_message or "",
        session_id=session_id or "",
        api_prefix=api_prefix.rstrip("/"),
        message_api_url=f"{api_prefix.rstrip('/')}/talk/message",
        redis_key_prefix=(redis_key_prefix or get_redis_key_prefix()).strip(),
    )
