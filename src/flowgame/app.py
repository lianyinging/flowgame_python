"""
FlowGame 独立 FastAPI 应用入口。

单独启动（推荐开源/独立部署）::

    uvicorn src.flowgame.app:app --host 0.0.0.0 --port 8001 --reload

本地一键（API + Robot Worker）::

    APP_ENV=dev python run.py

接口前缀默认为 ``/api/v1/flowGame``。
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from src.flowgame.settings import load_flowgame_dotenv

load_flowgame_dotenv()

from src.flowgame.execution_logging import configure_execution_logging
from src.flowgame.startup_logging import log_infrastructure_config

configure_execution_logging()
log_infrastructure_config()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.flowgame.constants import API_PREFIX
from src.flowgame.prefix_middleware import FlowgameKeyPrefixMiddleware
from src.flowgame.registry import register_routes


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # 监听由独立 Robot Worker 负责，API 进程不再 restore WebSocket
    yield


app = FastAPI(
    title="FlowGame API",
    description="Tinyflow 工作流编排、Redis 与 Qdrant 管理接口",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(FlowgameKeyPrefixMiddleware)

register_routes(app)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "flowgame"}


@app.get("/")
async def root():
    return {
        "service": "flowgame",
        "apiPrefix": API_PREFIX,
        "docs": "/docs",
    }


def start_server() -> None:
    import uvicorn

    from src.flowgame.robot_channel.spawn import (
        start_embedded_robot_worker,
        stop_embedded_robot_worker,
    )

    host = os.getenv("FLOWGAME_HOST", "0.0.0.0")
    port = int(os.getenv("FLOWGAME_PORT", "8001"))
    workers = int(os.getenv("FLOWGAME_UVICORN_WORKERS", "1"))
    reload_env = os.getenv("FLOWGAME_RELOAD", "true").strip().lower()
    reload = reload_env in ("1", "true", "yes")

    # 一条命令同时拉起独立 Robot Worker（可用 FLOWGAME_ROBOT_AUTOSTART=false 关闭）
    start_embedded_robot_worker(api_port=port)

    try:
        if workers > 1:
            if reload:
                reload = False
            uvicorn.run(
                "src.flowgame.app:app",
                host=host,
                port=port,
                workers=workers,
                reload=False,
            )
        else:
            uvicorn.run("src.flowgame.app:app", host=host, port=port, reload=reload)
    finally:
        stop_embedded_robot_worker()


if __name__ == "__main__":
    start_server()
