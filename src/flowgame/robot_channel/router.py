"""会话机器人 HTTP API（启停只改 desiredStatus，监听由独立 Worker 负责）。"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel

from src.flowgame.robot_channel import store as robot_store
from src.flowgame.robot_channel.models import (
    DEFAULT_INPUT_MAPPING,
    DEFAULT_OUTPUT_MAPPING,
    DEFAULT_TEAM_OUTPUT_MAPPING,
    default_execute_timeout_sec,
    default_router_model,
    default_team_execute_timeout_sec,
)
from src.flowgame.robot_channel.employee_router import (
    DEFAULT_ROUTER_BASE_URL,
    default_router_base_url,
)
from src.flowgame.robot_channel.runtime import RobotRuntimeError, session_robot_manager

robot_router = APIRouter()


class ApiResponse(BaseModel):
    code: int = 200
    msg: str = "ok"
    data: Optional[Any] = None


def _ok(msg: str, data: Any = None) -> ApiResponse:
    return ApiResponse(code=200, msg=msg, data=data)


def _stale_sec() -> int:
    return int(os.getenv("FLOWGAME_ROBOT_STALE_SEC", "30"))


def _serialize(robot: Any) -> Dict[str, Any]:
    online = robot_store.is_worker_online(stale_sec=_stale_sec())
    data = robot.to_dict(
        mask_secret=True,
        worker_online=online,
        stale_sec=_stale_sec(),
    )
    # 列表展示：用数字员工覆盖决策/任务字段
    employee_ids = list(data.get("employeeIds") or [])
    if not employee_ids:
        legacy = str(data.get("employeeId") or "").strip()
        if legacy:
            employee_ids = [legacy]
    if employee_ids:
        try:
            from src.flowgame.digital_employee import store as employee_store

            names: list[str] = []
            summaries: list[str] = []
            any_bound = False
            for eid in employee_ids:
                emp = employee_store.get_employee(eid)
                if not emp:
                    names.append(eid)
                    summaries.append(f"{eid}（不存在）")
                    continue
                names.append(emp.name)
                summaries.append(
                    f"{emp.name}: {emp.bind_label()}"
                    + (f" / 决策 {emp.decisionMethodKey}" if emp.decisionMethodKey else "")
                )
                any_bound = any_bound or emp.is_bound()
            data["employeeNames"] = names
            data["employeeName"] = "、".join(names)
            data["employeeSummaries"] = summaries
            data["employeeBound"] = any_bound
            data["employeeBindLabel"] = (
                f"{len(employee_ids)} 人自动路由"
                if len(employee_ids) >= 2
                else (summaries[0] if summaries else "")
            )
            # 单员工时继续回填决策/任务便于旧列展示
            if len(employee_ids) == 1:
                emp = employee_store.get_employee(employee_ids[0])
                if emp:
                    data["decisionMethodKey"] = emp.decisionMethodKey
                    data["bindType"] = emp.bindType
                    data["methodKey"] = emp.methodKey
                    data["teamKey"] = emp.teamKey
        except Exception:  # noqa: BLE001
            data["employeeName"] = ""
            data["employeeBound"] = False
    return data


@robot_router.get("/robots/defaults", response_model=ApiResponse, summary="默认入出参映射")
def robot_defaults_api():
    return _ok(
        "ok",
        {
            "types": [{"value": "wecom_aibot", "label": "企业微信智能机器人"}],
            "bindTypes": [
                {"value": "flow", "label": "任务目标：流程（methodKey）"},
                {"value": "team", "label": "任务目标：AgentTeam（teamKey）"},
            ],
            "note": "决策目标与任务目标请在「数字员工」上配置；会话机器人可绑定多名员工，≥2 时按描述 LLM 自动路由。",
            "routerModels": [
                {"value": "deepseek-v4-flash", "label": "deepseekFlash（deepseek-v4-flash）"},
                {"value": "deepseek-chat", "label": "deepseek-chat"},
                {"value": "deepseek-reasoner", "label": "deepseek-reasoner"},
            ],
            "defaultRouterModel": default_router_model(),
            "defaultRouterBaseUrl": default_router_base_url() or DEFAULT_ROUTER_BASE_URL,
            "inputMapping": DEFAULT_INPUT_MAPPING,
            "outputMapping": DEFAULT_OUTPUT_MAPPING,
            "teamOutputMapping": DEFAULT_TEAM_OUTPUT_MAPPING,
            "inboundFields": [
                "text",
                "kind",
                "target",
                "chatid",
                "userid",
                "chattype",
                "msgid",
                "msgtype",
            ],
            "outputTargets": [
                {"value": "reply_markdown", "label": "回发 markdown"},
                {"value": "reply_text", "label": "回发文本"},
                {"value": "reply_file", "label": "回发文件（本地路径）"},
            ],
            "defaultExecuteTimeoutSec": default_execute_timeout_sec(),
            "defaultTeamExecuteTimeoutSec": default_team_execute_timeout_sec(),
        },
    )


@robot_router.get("/robots/worker", response_model=ApiResponse, summary="Robot Worker 在线状态")
def robot_worker_status_api():
    stale = _stale_sec()
    presence = robot_store.get_worker_presence()
    online = robot_store.is_worker_online(stale_sec=stale)
    return _ok(
        "ok",
        {
            "online": online,
            "presence": presence,
            "staleSec": stale,
            "hint": None
            if online
            else "未检测到 Robot Worker。请使用 APP_ENV=dev python run.py（会自动拉起），或单独运行 python -m src.flowgame.robot_channel.worker",
        },
    )


@robot_router.get("/robots", response_model=ApiResponse, summary="列出会话机器人")
def list_robots_api():
    try:
        items = [_serialize(r) for r in robot_store.list_robots()]
        worker = {
            "online": robot_store.is_worker_online(stale_sec=_stale_sec()),
            "presence": robot_store.get_worker_presence(),
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _ok("ok", {"items": items, "total": len(items), "worker": worker})


@robot_router.get("/robots/{robot_id}", response_model=ApiResponse, summary="获取机器人")
def get_robot_api(robot_id: str):
    try:
        robot = robot_store.get_robot(robot_id, include_secret=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not robot:
        raise HTTPException(status_code=404, detail="机器人不存在")
    return _ok("ok", _serialize(robot))


@robot_router.put("/robots", response_model=ApiResponse, summary="新增/更新会话机器人")
def put_robot_api(body: Dict[str, Any] = Body(...)):
    try:
        saved = robot_store.save_robot(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _ok("已保存", _serialize(saved))


@robot_router.delete("/robots/{robot_id}", response_model=ApiResponse, summary="删除机器人")
def delete_robot_api(robot_id: str):
    try:
        # 先下发停止意图，再删配置
        if robot_store.get_robot(robot_id):
            try:
                session_robot_manager.stop(robot_id)
            except RobotRuntimeError:
                pass
        ok = robot_store.delete_robot(robot_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=404, detail="机器人不存在")
    return _ok("已删除", {"deleted": True})


@robot_router.post("/robots/{robot_id}/start", response_model=ApiResponse, summary="启动监听（写意图）")
def start_robot_api(robot_id: str):
    try:
        robot = session_robot_manager.start(robot_id)
    except RobotRuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    data = _serialize(robot)
    if not robot_store.is_worker_online(stale_sec=_stale_sec()):
        data["statusMessage"] = (
            "已下发启动；但 Robot Worker 未在线。"
            "请用 python run.py 启动（自动拉起 Worker）。"
        )
    return _ok("已下发启动", data)


@robot_router.post("/robots/{robot_id}/stop", response_model=ApiResponse, summary="停止监听（写意图）")
def stop_robot_api(robot_id: str):
    try:
        robot = session_robot_manager.stop(robot_id)
    except RobotRuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _ok("已下发停止", _serialize(robot))
