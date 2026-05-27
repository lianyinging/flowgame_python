"""
FlowGame 独立 FastAPI 应用入口。

单独启动（推荐开源/独立部署）::

    uvicorn src.flowgame.app:app --host 0.0.0.0 --port 8001 --reload

接口前缀默认为 ``/api/v1/flowGame``，例如：

- POST /api/v1/flowGame/execute
- GET  /api/v1/flowGame/redis?redisKey=...
- GET  /api/v1/flowGame/qdrant/collections
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    _root = Path(__file__).resolve().parents[2]
    load_dotenv(_root / ".env")
except ImportError:
    pass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.flowgame.constants import API_PREFIX
from src.flowgame.registry import register_routes

app = FastAPI(
    title="FlowGame API",
    description="Tinyflow 工作流编排、Redis 与 Qdrant 管理接口",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

    host = os.getenv("FLOWGAME_HOST", "0.0.0.0")
    port = int(os.getenv("FLOWGAME_PORT", "8001"))
    uvicorn.run("src.flowgame.app:app", host=host, port=port, reload=True)


if __name__ == "__main__":
    start_server()
