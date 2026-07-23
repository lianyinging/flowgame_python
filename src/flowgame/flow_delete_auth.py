"""流程删除密码校验（FLOWGAME_FLOW_DELETE_PASSWORD）。"""
from __future__ import annotations

import os
import secrets
from typing import Optional

from fastapi import HTTPException


def get_flow_delete_password() -> str:
    return (os.getenv("FLOWGAME_FLOW_DELETE_PASSWORD") or "").strip()


def flow_delete_password_required() -> bool:
    return bool(get_flow_delete_password())


def assert_flow_delete_password(provided: Optional[str]) -> None:
    """未配置 env 时不校验；已配置则必须与请求密码一致。"""
    expected = get_flow_delete_password()
    if not expected:
        return
    actual = (provided or "").strip()
    if not actual or not secrets.compare_digest(actual, expected):
        raise HTTPException(status_code=403, detail="删除密码错误")
