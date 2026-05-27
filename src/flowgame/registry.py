"""将 FlowGame 路由注册到已有 FastAPI 应用（可选）。"""
from __future__ import annotations

from fastapi import FastAPI

from src.flowgame.constants import API_PREFIX
from src.flowgame.router import flowgame_router


def register_routes(app: FastAPI, prefix: str = API_PREFIX) -> None:
    """把 FlowGame 全部接口挂到指定 FastAPI 应用上。"""
    app.include_router(flowgame_router, prefix=prefix, tags=["FlowGame"])
