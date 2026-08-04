"""数字员工 HTTP API。"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel

from src.flowgame.digital_employee import store as employee_store
from src.flowgame.robot_channel.models import (
    default_execute_timeout_sec,
    default_team_execute_timeout_sec,
)

digital_employee_router = APIRouter()


class ApiResponse(BaseModel):
    code: int = 200
    msg: str = "ok"
    data: Optional[Any] = None


def _ok(msg: str, data: Any = None) -> ApiResponse:
    return ApiResponse(code=200, msg=msg, data=data)


@digital_employee_router.get(
    "/digital-employees/defaults",
    response_model=ApiResponse,
    summary="数字员工默认选项",
)
def employee_defaults_api():
    return _ok(
        "ok",
        {
            "bindTypes": [
                {"value": "flow", "label": "任务目标：流程（methodKey）"},
                {"value": "team", "label": "任务目标：AgentTeam（teamKey）"},
            ],
            "defaultExecuteTimeoutSec": default_execute_timeout_sec(),
            "defaultTeamExecuteTimeoutSec": default_team_execute_timeout_sec(),
        },
    )


@digital_employee_router.get(
    "/digital-employees",
    response_model=ApiResponse,
    summary="列出数字员工",
)
def list_employees_api():
    try:
        items = [e.to_dict() for e in employee_store.list_employees()]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _ok("ok", {"items": items, "total": len(items)})


@digital_employee_router.get(
    "/digital-employees/{employee_id}",
    response_model=ApiResponse,
    summary="获取数字员工",
)
def get_employee_api(employee_id: str):
    try:
        emp = employee_store.get_employee(employee_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not emp:
        raise HTTPException(status_code=404, detail="数字员工不存在")
    return _ok("ok", emp.to_dict())


@digital_employee_router.put(
    "/digital-employees",
    response_model=ApiResponse,
    summary="新增/更新数字员工",
)
def put_employee_api(body: Dict[str, Any] = Body(...)):
    try:
        saved = employee_store.save_employee(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _ok("已保存", saved.to_dict())


@digital_employee_router.delete(
    "/digital-employees/{employee_id}",
    response_model=ApiResponse,
    summary="删除数字员工",
)
def delete_employee_api(employee_id: str):
    try:
        ok = employee_store.delete_employee(employee_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=404, detail="数字员工不存在")
    return _ok("已删除", {"deleted": True})
