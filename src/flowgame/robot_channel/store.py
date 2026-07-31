"""会话机器人 Redis 存储。"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.flowgame.key_prefix import get_redis_key_prefix
from src.flowgame.robot_channel.models import (
    DEFAULT_INPUT_MAPPING,
    DEFAULT_OUTPUT_MAPPING,
    SECRET_MASK,
    SessionRobot,
    normalize_mappings,
    parse_execute_timeout_sec,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def robots_index_key() -> str:
    return f"{get_redis_key_prefix()}session_robots:__index__"


def robot_data_key(robot_id: str) -> str:
    return f"{get_redis_key_prefix()}session_robots:{robot_id.strip()}"


def worker_presence_key() -> str:
    return f"{get_redis_key_prefix()}session_robots:__worker__"


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
    index_key = robots_index_key()
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
    index_key = robots_index_key()
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


def get_robot(robot_id: str, *, include_secret: bool = True) -> Optional[SessionRobot]:
    data = _read_json(robot_data_key(robot_id))
    if not data:
        return None
    robot = SessionRobot.from_dict(data)
    if not include_secret:
        robot.secret = SECRET_MASK if robot.secret else ""
    return robot


def list_robots() -> List[SessionRobot]:
    client = _redis()
    raw = client.get(robots_index_key())
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
    result: List[SessionRobot] = []
    for key in keys:
        robot = get_robot(key, include_secret=True)
        if robot:
            result.append(robot)
    return result


def save_robot(payload: Dict[str, Any]) -> SessionRobot:
    robot_id = str(payload.get("robotId") or "").strip() or uuid.uuid4().hex[:12]
    existing = get_robot(robot_id, include_secret=True)

    secret = str(payload.get("secret") or "")
    if existing and (not secret or secret == SECRET_MASK):
        secret = existing.secret

    if "methodKey" in payload:
        method_key = str(payload.get("methodKey") or "").strip()
    else:
        method_key = existing.methodKey if existing else ""

    if "executeTimeoutSec" in payload:
        execute_timeout = parse_execute_timeout_sec(payload.get("executeTimeoutSec"))
    else:
        execute_timeout = existing.executeTimeoutSec if existing else None

    desired = existing.desiredStatus if existing else "stopped"
    if "desiredStatus" in payload and payload.get("desiredStatus"):
        desired = str(payload["desiredStatus"])

    robot = SessionRobot(
        robotId=robot_id,
        name=str(payload.get("name") or "").strip() or robot_id,
        type=(payload.get("type") or "wecom_aibot"),  # type: ignore[arg-type]
        botId=str(payload.get("botId") or (existing.botId if existing else "")).strip(),
        secret=secret,
        methodKey=method_key,
        executeTimeoutSec=execute_timeout,
        inputMapping=normalize_mappings(
            payload.get("inputMapping"), DEFAULT_INPUT_MAPPING
        ),
        outputMapping=normalize_mappings(
            payload.get("outputMapping"), DEFAULT_OUTPUT_MAPPING
        ),
        desiredStatus=desired,  # type: ignore[arg-type]
        runtimeStatus=existing.runtimeStatus if existing else "stopped",
        runtimeMessage=existing.runtimeMessage if existing else "",
        runtimeHeartbeatAt=existing.runtimeHeartbeatAt if existing else "",
        runtimeOwner=existing.runtimeOwner if existing else "",
        createdAt=existing.createdAt if existing else _now(),
        updatedAt=_now(),
    )
    if robot.type != "wecom_aibot":
        raise ValueError(f"暂不支持的机器人类型: {robot.type}")
    if not robot.botId:
        raise ValueError("botId 不能为空")
    if not robot.secret:
        raise ValueError("secret 不能为空")

    _write_json(robot_data_key(robot.robotId), robot.to_dict(mask_secret=False))
    _index_add(robot.robotId)
    return robot


def set_desired_status(robot_id: str, desired: str) -> SessionRobot:
    robot = get_robot(robot_id, include_secret=True)
    if not robot:
        raise ValueError("机器人不存在")
    if desired not in {"running", "stopped"}:
        raise ValueError("desiredStatus 无效")
    robot.desiredStatus = desired  # type: ignore[assignment]
    if desired == "stopped":
        # 意图停止时先清展示态；Worker 断开后会再写 runtime
        robot.runtimeMessage = ""
    elif robot.runtimeStatus == "running":
        # 已在跑：勿覆盖成「等待拉起」，避免前端状态闪回
        robot.runtimeMessage = ""
    else:
        robot.runtimeStatus = "connecting"  # type: ignore[assignment]
        robot.runtimeMessage = "等待 Robot Worker 拉起…"
    robot.updatedAt = _now()
    _write_json(robot_data_key(robot.robotId), robot.to_dict(mask_secret=False))
    return robot


def update_runtime(
    robot_id: str,
    *,
    runtime_status: str,
    runtime_message: str = "",
    runtime_owner: str = "",
    touch_heartbeat: bool = True,
) -> Optional[SessionRobot]:
    robot = get_robot(robot_id, include_secret=True)
    if not robot:
        return None
    robot.runtimeStatus = runtime_status  # type: ignore[assignment]
    robot.runtimeMessage = runtime_message
    if runtime_owner:
        robot.runtimeOwner = runtime_owner
    if touch_heartbeat:
        robot.runtimeHeartbeatAt = _now()
    robot.updatedAt = _now()
    _write_json(robot_data_key(robot.robotId), robot.to_dict(mask_secret=False))
    return robot


def touch_worker_presence(owner: str, ttl_sec: int = 30) -> None:
    client = _redis()
    payload = {"owner": owner, "at": _now(), "pid": os.getpid()}
    client.set(worker_presence_key(), json.dumps(payload, ensure_ascii=False), ex=ttl_sec)


def get_worker_presence() -> Optional[Dict[str, Any]]:
    return _read_json(worker_presence_key())


def is_worker_online(stale_sec: int = 30) -> bool:
    data = get_worker_presence()
    if not data:
        return False
    raw = str(data.get("at") or "")
    if not raw:
        return False
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds()
        return age <= stale_sec
    except Exception:  # noqa: BLE001
        return False


def delete_robot(robot_id: str) -> bool:
    client = _redis()
    key = robot_data_key(robot_id)
    existed = bool(client.exists(key))
    client.delete(key)
    _index_remove(robot_id)
    return existed
