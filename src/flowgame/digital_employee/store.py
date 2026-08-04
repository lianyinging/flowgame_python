"""数字员工 Redis 存储。"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.flowgame.digital_employee.models import DigitalEmployee
from src.flowgame.key_prefix import get_redis_key_prefix
from src.flowgame.robot_channel.models import normalize_bind_type, parse_execute_timeout_sec


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def employees_index_key() -> str:
    return f"{get_redis_key_prefix()}digital_employees:__index__"


def employee_data_key(employee_id: str) -> str:
    return f"{get_redis_key_prefix()}digital_employees:{employee_id.strip()}"


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


def _index_add(item_key: str) -> None:
    client = _redis()
    index_key = employees_index_key()
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


def _index_remove(item_key: str) -> None:
    client = _redis()
    index_key = employees_index_key()
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


def get_employee(employee_id: str) -> Optional[DigitalEmployee]:
    data = _read_json(employee_data_key(employee_id))
    if not data:
        return None
    return DigitalEmployee.from_dict(data)


def list_employees() -> List[DigitalEmployee]:
    client = _redis()
    raw = client.get(employees_index_key())
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
    result: List[DigitalEmployee] = []
    for key in keys:
        emp = get_employee(key)
        if emp:
            result.append(emp)
    return result


def save_employee(payload: Dict[str, Any]) -> DigitalEmployee:
    employee_id = str(payload.get("employeeId") or "").strip() or uuid.uuid4().hex[:12]
    existing = get_employee(employee_id)

    if "decisionMethodKey" in payload:
        decision_method_key = str(payload.get("decisionMethodKey") or "").strip()
    else:
        decision_method_key = existing.decisionMethodKey if existing else ""

    if "methodKey" in payload:
        method_key = str(payload.get("methodKey") or "").strip()
    else:
        method_key = existing.methodKey if existing else ""

    if "teamKey" in payload:
        team_key = str(payload.get("teamKey") or "").strip()
    else:
        team_key = existing.teamKey if existing else ""

    if "bindType" in payload:
        bind_type = normalize_bind_type(payload.get("bindType"))
    elif existing:
        bind_type = existing.bindType
    else:
        bind_type = "team" if team_key and not method_key else "flow"

    if "executeTimeoutSec" in payload:
        execute_timeout = parse_execute_timeout_sec(payload.get("executeTimeoutSec"))
    else:
        execute_timeout = existing.executeTimeoutSec if existing else None

    if "description" in payload:
        description = str(payload.get("description") or "").strip()
    else:
        description = existing.description if existing else ""

    emp = DigitalEmployee(
        employeeId=employee_id,
        name=str(payload.get("name") or "").strip() or employee_id,
        description=description,
        decisionMethodKey=decision_method_key,
        bindType=bind_type,
        methodKey=method_key,
        teamKey=team_key,
        executeTimeoutSec=execute_timeout,
        createdAt=existing.createdAt if existing else _now(),
        updatedAt=_now(),
    )
    if emp.bindType == "team" and not emp.teamKey:
        raise ValueError("bindType=team 时须填写 teamKey")
    if emp.bindType == "flow" and not emp.methodKey:
        # 允许先保存未绑定任务，启动会话机器人时再校验
        pass

    _write_json(employee_data_key(emp.employeeId), emp.to_dict())
    _index_add(emp.employeeId)
    return emp


def delete_employee(employee_id: str) -> bool:
    client = _redis()
    key = employee_data_key(employee_id)
    existed = bool(client.exists(key))
    client.delete(key)
    _index_remove(employee_id)
    return existed
