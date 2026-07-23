"""Team / Agent HTTP API。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

from src.flowgame.team.models import AgentTeamDef, FlowAgentConfig
from src.flowgame.team.runtime import TeamRuntime, TeamRuntimeError
from src.flowgame.team import store as team_store

team_router = APIRouter()


class ApiResponse(BaseModel):
    code: int = 200
    msg: str = "ok"
    data: Optional[Any] = None


class TeamRunBody(BaseModel):
    teamKey: Optional[str] = Field(None, description="已保存的 teamKey")
    team: Optional[Dict[str, Any]] = Field(None, description="内联 Team 定义（可覆盖）")
    agents: Optional[List[Dict[str, Any]]] = Field(
        None, description="内联 Agent 列表（可与 Redis 合并）"
    )
    variables: Dict[str, Any] = Field(default_factory=dict, description="黑板初始变量")


def _ok(msg: str, data: Any = None) -> ApiResponse:
    return ApiResponse(code=200, msg=msg, data=data)


@team_router.get("/agents", response_model=ApiResponse, summary="列出已发布 Agent")
def list_agents_api():
    try:
        items = [a.to_dict() for a in team_store.list_agents()]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _ok("ok", {"items": items, "total": len(items)})


@team_router.put("/agents", response_model=ApiResponse, summary="保存/发布 Agent")
def put_agent_api(body: Dict[str, Any] = Body(...)):
    try:
        agent = FlowAgentConfig.from_dict(body)
        if not agent.agentKey:
            raise HTTPException(status_code=400, detail="agentKey 不能为空")
        saved = team_store.save_agent(agent)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _ok("已保存", saved.to_dict())


@team_router.get("/teams", response_model=ApiResponse, summary="列出 AgentTeam")
def list_teams_api():
    try:
        items = [t.to_dict() for t in team_store.list_teams()]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _ok("ok", {"items": items, "total": len(items)})


@team_router.get("/teams/{team_key}", response_model=ApiResponse, summary="获取 Team")
def get_team_api(team_key: str):
    try:
        team = team_store.get_team(team_key)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not team:
        raise HTTPException(status_code=404, detail="Team 不存在")
    return _ok("ok", team.to_dict())


@team_router.put("/teams", response_model=ApiResponse, summary="保存 AgentTeam")
def put_team_api(body: Dict[str, Any] = Body(...)):
    try:
        team = AgentTeamDef.from_dict(body)
        if not team.teamKey:
            raise HTTPException(status_code=400, detail="teamKey 不能为空")
        saved = team_store.save_team(team)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _ok("已保存", saved.to_dict())


@team_router.delete("/teams/{team_key}", response_model=ApiResponse, summary="删除 Team")
def delete_team_api(team_key: str):
    try:
        deleted = team_store.delete_team(team_key)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _ok("已删除" if deleted else "不存在", {"deleted": deleted})


@team_router.post("/teams/run", response_model=ApiResponse, summary="执行 AgentTeam")
def run_team_api(body: TeamRunBody = Body(...)):
    """
    执行协同 Team。

    - strategy=supervisor：主控动态调度（对齐 demo_orchestrator）
    - strategy=sequential：按 members 顺序执行

    子 Agent：优先执行 methodKey 对应 Redis 流程；无流程时回退内置角色 Prompt。
    请求可内联 team + agents，不必先落库。
    """
    try:
        team = _resolve_team(body)
        agents = _resolve_agents(body, team)
        runtime = TeamRuntime(team, agents)
        result = runtime.run(body.variables or {})
        # 可选：把内联定义写回 Redis，便于下次按 teamKey 跑
        if body.team:
            try:
                team_store.save_team(team)
            except Exception:  # noqa: BLE001
                pass
        for agent in agents.values():
            try:
                team_store.save_agent(agent)
            except Exception:  # noqa: BLE001
                pass
        return _ok("执行完成", result.to_dict())
    except TeamRuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _resolve_team(body: TeamRunBody) -> AgentTeamDef:
    if body.team:
        return AgentTeamDef.from_dict(body.team)
    if body.teamKey:
        team = team_store.get_team(body.teamKey)
        if team:
            return team
        raise HTTPException(status_code=404, detail=f"Team 不存在: {body.teamKey}")
    raise HTTPException(status_code=400, detail="须提供 teamKey 或 team")


def _resolve_agents(body: TeamRunBody, team: AgentTeamDef) -> Dict[str, FlowAgentConfig]:
    agents: Dict[str, FlowAgentConfig] = {}
    # Redis 已有
    try:
        for a in team_store.list_agents():
            agents[a.agentKey] = a
    except Exception:  # noqa: BLE001
        pass
    # 内联覆盖
    for raw in body.agents or []:
        cfg = FlowAgentConfig.from_dict(raw)
        if cfg.agentKey:
            agents[cfg.agentKey] = cfg
    # 确保成员 / 主控至少有占位配置
    keys = [m.agentKey for m in team.members]
    if team.supervisorAgentKey:
        keys.append(team.supervisorAgentKey)
    for key in keys:
        if key and key not in agents:
            agents[key] = FlowAgentConfig(
                agentKey=key,
                methodKey=key,
                name=key,
                published=True,
            )
    return agents
