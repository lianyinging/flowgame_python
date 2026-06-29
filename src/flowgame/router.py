"""FastAPI routes for Tinyflow workflow execution."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from src.flowgame.qdrant.router import qdrant_router
from src.flowgame.redis.router import redis_router
from src.flowgame.key_prefix import bind_request_key_prefixes
from src.flowgame.service import FlowGameExecuteError, flow_game_execute_service
from src.flowgame.workflow_runner import WorkflowQueueFullError

flowgame_router = APIRouter()
flowgame_router.include_router(redis_router, prefix="/redis", tags=["FlowGame-Redis"])
flowgame_router.include_router(qdrant_router, prefix="/qdrant", tags=["FlowGame-Qdrant"])


class FlowGameExecuteResponse(BaseModel):
    code: int = Field(description="200 表示成功")
    msg: str = Field(description="响应消息")
    data: Optional[Dict[str, Any]] = Field(default=None, description="执行结果")


class FlowGameTalkMessageResponse(BaseModel):
    code: int = Field(description="200 表示成功")
    msg: str = Field(description="响应消息")
    data: Optional[Dict[str, Any]] = Field(default=None, description="assistantMessage 等")


@flowgame_router.get("/talk", response_class=HTMLResponse)
def talk_page(
    methodKey: str = Query(..., description="流程 methodKey"),
    sessionId: Optional[str] = Query(None, description="可选会话 ID"),
    redisKeyPrefix: Optional[str] = Query(
        None,
        description="Redis 键前缀，与编辑器保存一致（默认 flow_game:）；浏览器直连时必填若与后端环境变量不同",
    ),
):
    """
    打开对话页 HTML。

    根据流程中「对话开始」节点的模板配置渲染页面（default / minimal）。
    """
    if redisKeyPrefix and str(redisKeyPrefix).strip():
        bind_request_key_prefixes(redis_key_prefix=str(redisKeyPrefix).strip())
    try:
        html = flow_game_execute_service.render_talk_html(
            methodKey,
            session_id=sessionId,
        )
    except FlowGameExecuteError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return HTMLResponse(content=html)


@flowgame_router.post("/talk/message", response_model=FlowGameTalkMessageResponse)
def talk_message(
    request: Request,
    body: Dict[str, Any] = Body(...),
    user_id: Optional[str] = Header(None, alias="userId"),
):
    """
    发送对话消息并执行工作流。

    请求体::
        {"methodKey": "流程名称", "message": "用户输入", "sessionId": "可选", "variables": {...}}

    响应 data 含 assistantMessage: {"role": "assistant", "content": "..."}
    """
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="请求体必须是 JSON 对象")

    redis_key_prefix = body.get("redisKeyPrefix")
    if redis_key_prefix is not None and str(redis_key_prefix).strip():
        bind_request_key_prefixes(redis_key_prefix=str(redis_key_prefix).strip())

    try:
        result = flow_game_execute_service.execute_talk_message(
            body, user_id=user_id, http_headers=request.headers
        )
    except WorkflowQueueFullError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except FlowGameExecuteError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return FlowGameTalkMessageResponse(code=200, msg="执行成功", data=result)


@flowgame_router.post("/execute", response_model=FlowGameExecuteResponse)
def execute_flow(
    request: Request,
    body: Dict[str, Any] = Body(...),
    user_id: Optional[str] = Header(None, alias="userId"),
):
    """
    执行 Tinyflow 工作流。

    外部调用（推荐）::
        {"methodKey": "流程名称", "variables": {...}}

    侧栏 headers 分组字段仅通过 HTTP 请求头传入（body 勿传 headers）。

    从 Redis 键 ``flow_game:flow_list:{methodKey}`` 加载已保存的工作流并执行。

    管理端调试::
        {"workflow": {...tinyflow.getData()...}, "variables": {...}}

    响应 data：apiOutput / endNodeOutput、lastNodeOutput、nodeExecutions（各节点执行详情）、methodKey、status 等
    """
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="请求体必须是 JSON 对象")

    try:
        result = flow_game_execute_service.execute(
            body, user_id=user_id, http_headers=request.headers
        )
    except WorkflowQueueFullError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except FlowGameExecuteError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    api_output = result.get("apiOutput") or result.get("lastNodeOutput") or {}
    has_outputs = isinstance(api_output, dict) and len(api_output) > 0
    msg = (
        "执行成功"
        if has_outputs
        else "执行成功，当前无输出（请检查 Api接口开始 节点 output 引用配置）"
    )
    return FlowGameExecuteResponse(code=200, msg=msg, data=result)


@flowgame_router.post("/execute/stream")
def execute_flow_stream(
    request: Request,
    body: Dict[str, Any] = Body(...),
    user_id: Optional[str] = Header(None, alias="userId"),
):
    """
    流式执行工作流（NDJSON），用于管理端试运行实时进度。

    每行 JSON：{"event": "node_started"|"node_finished"|"workflow_finished"|"workflow_error", "data": {...}}
    """
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="请求体必须是 JSON 对象")

    def generate():
        yield from flow_game_execute_service.iter_execute_stream(
            body, user_id=user_id, http_headers=request.headers
        )

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
