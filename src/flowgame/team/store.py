"""Team / Agent Redis 存储。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.flowgame.key_prefix import get_redis_key_prefix
from src.flowgame.team.models import AgentTeamDef, FlowAgentConfig


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def agents_index_key() -> str:
    return f"{get_redis_key_prefix()}team_agents:__index__"


def agent_data_key(agent_key: str) -> str:
    return f"{get_redis_key_prefix()}team_agents:{agent_key.strip()}"


def teams_index_key() -> str:
    return f"{get_redis_key_prefix()}teams:__index__"


def team_data_key(team_key: str) -> str:
    return f"{get_redis_key_prefix()}teams:{team_key.strip()}"


def _redis():
    from src.flowgame.redis.client import redis_client

    if not redis_client.ping():
        raise RuntimeError("Redis 不可用")
    return redis_client


def _read_json(key: str) -> Optional[Dict[str, Any]]:
    client = _redis()
    raw = client.get(key)
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _write_json(key: str, value: Dict[str, Any]) -> None:
    client = _redis()
    client.set(key, json.dumps(value, ensure_ascii=False))


def _index_add(index_key: str, item_key: str) -> None:
    client = _redis()
    raw = client.get(index_key)
    items: List[str] = []
    if raw:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(parsed, list):
                items = [str(x) for x in parsed]
        except json.JSONDecodeError:
            items = []
    if item_key not in items:
        items.append(item_key)
        client.set(index_key, json.dumps(items, ensure_ascii=False))


def _index_remove(index_key: str, item_key: str) -> None:
    client = _redis()
    raw = client.get(index_key)
    if not raw:
        return
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        items = [str(x) for x in parsed] if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return
    items = [x for x in items if x != item_key]
    client.set(index_key, json.dumps(items, ensure_ascii=False))


def save_agent(config: FlowAgentConfig) -> FlowAgentConfig:
    if not config.agentKey:
        raise ValueError("agentKey 不能为空")
    if not config.updatedAt:
        config.updatedAt = _now()
    else:
        config.updatedAt = _now()
    _write_json(agent_data_key(config.agentKey), config.to_dict())
    _index_add(agents_index_key(), config.agentKey)
    return config


def get_agent(agent_key: str) -> Optional[FlowAgentConfig]:
    data = _read_json(agent_data_key(agent_key))
    if not data:
        return None
    return FlowAgentConfig.from_dict(data)


def list_agents() -> List[FlowAgentConfig]:
    client = _redis()
    raw = client.get(agents_index_key())
    keys: List[str] = []
    if raw:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(parsed, list):
                keys = [str(x) for x in parsed]
        except json.JSONDecodeError:
            keys = []
    out: List[FlowAgentConfig] = []
    for k in keys:
        agent = get_agent(k)
        if agent:
            out.append(agent)
    return out


def save_team(team: AgentTeamDef) -> AgentTeamDef:
    if not team.teamKey:
        raise ValueError("teamKey 不能为空")
    team.updatedAt = _now()
    _write_json(team_data_key(team.teamKey), team.to_dict())
    _index_add(teams_index_key(), team.teamKey)
    return team


def get_team(team_key: str) -> Optional[AgentTeamDef]:
    data = _read_json(team_data_key(team_key))
    if not data:
        return None
    return AgentTeamDef.from_dict(data)


def list_teams() -> List[AgentTeamDef]:
    client = _redis()
    raw = client.get(teams_index_key())
    keys: List[str] = []
    if raw:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(parsed, list):
                keys = [str(x) for x in parsed]
        except json.JSONDecodeError:
            keys = []
    out: List[AgentTeamDef] = []
    for k in keys:
        team = get_team(k)
        if team:
            out.append(team)
    return out


def delete_team(team_key: str) -> bool:
    client = _redis()
    key = team_data_key(team_key)
    existed = bool(client.exists(key))
    client.delete(key)
    _index_remove(teams_index_key(), team_key.strip())
    return existed
