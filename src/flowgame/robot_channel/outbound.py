"""会话机器人出站消息队列：流程里 aibot 可投递，由 Worker 长连接发送。"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Dict, Optional

from src.flowgame.key_prefix import get_redis_key_prefix

logger = logging.getLogger("flowgame.session_robot.outbound")

# 出站任务 / 结果 TTL
OUTBOUND_TASK_TTL_SEC = 300
OUTBOUND_RESULT_TTL_SEC = 120


def outbound_queue_key(robot_id: str) -> str:
    return f"{get_redis_key_prefix()}session_robots:{robot_id.strip()}:outbound"


def outbound_result_key(req_id: str) -> str:
    return f"{get_redis_key_prefix()}session_robots:outbound_result:{req_id.strip()}"


def _redis():
    from src.flowgame.redis.client import redis_client

    if not redis_client.ping():
        raise RuntimeError("Redis 不可用")
    return redis_client


def enqueue_outbound(
    robot_id: str,
    *,
    msgtype: str = "markdown",
    content: str = "",
    chatid: str = "",
    file_path: str = "",
    media_type: str = "",
) -> str:
    """投递出站任务，返回 reqId。"""
    rid = (robot_id or "").strip()
    if not rid:
        raise ValueError("robotId 不能为空")
    cid = (chatid or "").strip()
    if not cid:
        raise ValueError("chatid 不能为空")
    req_id = f"ob_{uuid.uuid4().hex[:16]}"
    task: Dict[str, Any] = {
        "reqId": req_id,
        "robotId": rid,
        "msgtype": (msgtype or "markdown").strip(),
        "content": content or "",
        "chatid": cid,
        "filePath": (file_path or "").strip(),
        "mediaType": (media_type or "").strip(),
        "createdAt": time.time(),
    }
    client = _redis()
    raw = json.dumps(task, ensure_ascii=False)
    # rpush + blpop → FIFO
    client.rpush(outbound_queue_key(rid), raw)
    try:
        client.expire(outbound_queue_key(rid), OUTBOUND_TASK_TTL_SEC)
    except Exception:  # noqa: BLE001
        pass
    logger.info(
        "outbound enqueued robot=%s reqId=%s type=%s chatid=%s",
        rid,
        req_id,
        task["msgtype"],
        cid,
    )
    return req_id


def set_outbound_result(req_id: str, result: Dict[str, Any]) -> None:
    client = _redis()
    client.set(
        outbound_result_key(req_id),
        json.dumps(result, ensure_ascii=False),
        ex=OUTBOUND_RESULT_TTL_SEC,
    )


def wait_outbound_result(
    req_id: str,
    *,
    timeout_sec: float = 30,
    poll_sec: float = 0.2,
) -> Dict[str, Any]:
    """轮询等待 Worker 回写结果。"""
    deadline = time.monotonic() + max(0.5, float(timeout_sec))
    client = _redis()
    key = outbound_result_key(req_id)
    while time.monotonic() < deadline:
        raw = client.get(key)
        if raw:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            if isinstance(raw, dict):
                return raw
            try:
                data = json.loads(raw)
                return data if isinstance(data, dict) else {"ok": False, "error": "bad result"}
            except json.JSONDecodeError:
                return {"ok": False, "error": "bad result json"}
        time.sleep(max(0.05, float(poll_sec)))
    return {"ok": False, "error": "等待 Worker 发送超时", "reqId": req_id}


def pop_outbound_task(
    robot_id: str,
    *,
    timeout_sec: float = 1.0,
) -> Optional[Dict[str, Any]]:
    """Worker 阻塞弹出一条出站任务（BLPOP）。"""
    client = _redis()
    key = outbound_queue_key(robot_id)
    item = client.blpop(key, timeout=max(1, int(timeout_sec)))
    if not item:
        return None
    raw = item[1] if isinstance(item, (list, tuple)) and len(item) >= 2 else item
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        logger.warning("outbound bad json: %s", str(raw)[:200])
        return None
