"""Python 3.10 兼容：wecom-aibot-sdk 需要 typing.NotRequired。"""
from __future__ import annotations

import typing


def ensure_typing_not_required() -> None:
    try:
        from typing import NotRequired as _NotRequired  # noqa: F401
    except ImportError:
        from typing_extensions import NotRequired as _NotRequired

        typing.NotRequired = _NotRequired  # type: ignore[attr-defined]
