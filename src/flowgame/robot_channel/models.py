"""会话机器人数据模型。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
from typing import Any, Dict, List, Literal, Optional

RobotType = Literal["wecom_aibot"]
DesiredStatus = Literal["stopped", "running"]
RuntimeStatus = Literal["stopped", "running", "connecting", "error"]
# 列表展示用（兼容旧前端）
DisplayStatus = Literal["stopped", "running", "connecting", "error", "offline"]

DEFAULT_INPUT_MAPPING: List[Dict[str, str]] = [
    {"source": "text", "target": "message"},
    {"source": "target", "target": "chatId"},
    {"source": "userid", "target": "userId"},
    {"source": "chattype", "target": "chatType"},
]

DEFAULT_OUTPUT_MAPPING: List[Dict[str, str]] = [
    {"source": "assistantMessage", "target": "reply_markdown"},
]

SECRET_MASK = "***"


@dataclass
class FieldMapping:
    source: str
    target: str

    def to_dict(self) -> Dict[str, str]:
        return {"source": self.source, "target": self.target}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FieldMapping":
        return cls(
            source=str(data.get("source") or "").strip(),
            target=str(data.get("target") or "").strip(),
        )


def _migrate_desired(data: Dict[str, Any]) -> str:
    if data.get("desiredStatus"):
        return str(data["desiredStatus"])
    # 兼容旧字段 status
    old = str(data.get("status") or "stopped")
    return "running" if old == "running" else "stopped"


def _migrate_runtime(data: Dict[str, Any]) -> str:
    if data.get("runtimeStatus"):
        return str(data["runtimeStatus"])
    old = str(data.get("status") or "stopped")
    if old == "error":
        return "error"
    if old == "running":
        return "stopped"  # 旧进程内 running 迁移后需 Worker 重新拉起
    return "stopped"


@dataclass
class SessionRobot:
    robotId: str = ""
    name: str = ""
    type: RobotType = "wecom_aibot"
    botId: str = ""
    secret: str = ""
    methodKey: str = ""
    # 单机器人 /execute 超时（秒）；None / 未配置 → 用 FLOWGAME_ROBOT_EXECUTE_TIMEOUT_SEC
    executeTimeoutSec: Optional[int] = None
    inputMapping: List[FieldMapping] = field(default_factory=list)
    outputMapping: List[FieldMapping] = field(default_factory=list)
    desiredStatus: DesiredStatus = "stopped"
    runtimeStatus: RuntimeStatus = "stopped"
    runtimeMessage: str = ""
    runtimeHeartbeatAt: str = ""
    runtimeOwner: str = ""
    createdAt: str = ""
    updatedAt: str = ""

    def to_dict(
        self,
        *,
        mask_secret: bool = True,
        worker_online: Optional[bool] = None,
        stale_sec: int = 30,
    ) -> Dict[str, Any]:
        secret = self.secret
        if mask_secret and secret:
            secret = SECRET_MASK
        display, message = self.display_status(
            worker_online=worker_online, stale_sec=stale_sec
        )
        return {
            "robotId": self.robotId,
            "name": self.name,
            "type": self.type,
            "botId": self.botId,
            "secret": secret,
            "hasSecret": bool(self.secret),
            "methodKey": self.methodKey,
            "executeTimeoutSec": self.executeTimeoutSec,
            "inputMapping": [m.to_dict() for m in self.inputMapping],
            "outputMapping": [m.to_dict() for m in self.outputMapping],
            "desiredStatus": self.desiredStatus,
            "runtimeStatus": self.runtimeStatus,
            "runtimeMessage": self.runtimeMessage,
            "runtimeHeartbeatAt": self.runtimeHeartbeatAt,
            "runtimeOwner": self.runtimeOwner,
            # 兼容旧前端：以聚合展示为准，勿再用旧 runtimeMessage 覆盖空串
            "status": display,
            "statusMessage": message,
            "createdAt": self.createdAt,
            "updatedAt": self.updatedAt,
        }

    def display_status(
        self,
        *,
        worker_online: Optional[bool] = None,
        stale_sec: int = 30,
    ) -> tuple[str, str]:
        if self.desiredStatus != "running":
            return "stopped", ""
        if worker_online is False:
            return "offline", "Robot 监听进程未在线（请用 run.py 启动，或单独起 worker）"
        if self._heartbeat_stale(stale_sec):
            return "offline", "Robot 心跳超时，监听可能已中断"
        if self.runtimeStatus == "running":
            return "running", ""
        if self.runtimeStatus == "connecting":
            return "connecting", self.runtimeMessage or "正在连接…"
        if self.runtimeStatus == "error":
            return "error", self.runtimeMessage or "运行异常"
        return "connecting", self.runtimeMessage or "等待 Robot Worker 拉起…"

    def _heartbeat_stale(self, stale_sec: int) -> bool:
        if self.desiredStatus != "running":
            return False
        if not self.runtimeHeartbeatAt:
            return False
        try:
            ts = datetime.fromisoformat(self.runtimeHeartbeatAt.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds()
            return age > stale_sec
        except Exception:  # noqa: BLE001
            return False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionRobot":
        inputs = data.get("inputMapping") or DEFAULT_INPUT_MAPPING
        outputs = data.get("outputMapping") or DEFAULT_OUTPUT_MAPPING
        return cls(
            robotId=str(data.get("robotId") or "").strip(),
            name=str(data.get("name") or "").strip(),
            type=(data.get("type") or "wecom_aibot"),  # type: ignore[arg-type]
            botId=str(data.get("botId") or "").strip(),
            secret=str(data.get("secret") or ""),
            methodKey=str(data.get("methodKey") or "").strip(),
            executeTimeoutSec=parse_execute_timeout_sec(data.get("executeTimeoutSec")),
            inputMapping=[
                FieldMapping.from_dict(x)
                for x in inputs
                if isinstance(x, dict) and (x.get("source") or x.get("target"))
            ],
            outputMapping=[
                FieldMapping.from_dict(x)
                for x in outputs
                if isinstance(x, dict) and (x.get("source") or x.get("target"))
            ],
            desiredStatus=_migrate_desired(data),  # type: ignore[arg-type]
            runtimeStatus=_migrate_runtime(data),  # type: ignore[arg-type]
            runtimeMessage=(
                str(data["runtimeMessage"])
                if "runtimeMessage" in data
                else str(data.get("statusMessage") or "")
            ),
            runtimeHeartbeatAt=str(data.get("runtimeHeartbeatAt") or ""),
            runtimeOwner=str(data.get("runtimeOwner") or ""),
            createdAt=str(data.get("createdAt") or ""),
            updatedAt=str(data.get("updatedAt") or ""),
        )


def parse_execute_timeout_sec(value: Any) -> Optional[int]:
    """解析机器人级执行超时：空 / 非法 / ≤0 → None（走环境变量默认）。"""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            value = float(text)
        except ValueError:
            return None
    try:
        sec = int(value)
    except (TypeError, ValueError):
        return None
    if sec <= 0:
        return None
    return sec


def default_execute_timeout_sec() -> int:
    """全局默认：FLOWGAME_ROBOT_EXECUTE_TIMEOUT_SEC。"""
    try:
        return max(1, int(float(os.getenv("FLOWGAME_ROBOT_EXECUTE_TIMEOUT_SEC", "120"))))
    except (TypeError, ValueError):
        return 120


def normalize_mappings(
    mappings: Optional[List[Any]],
    defaults: List[Dict[str, str]],
) -> List[FieldMapping]:
    if not mappings:
        return [FieldMapping.from_dict(x) for x in defaults]
    result: List[FieldMapping] = []
    for item in mappings:
        if not isinstance(item, dict):
            continue
        m = FieldMapping.from_dict(item)
        if m.source and m.target:
            result.append(m)
    return result or [FieldMapping.from_dict(x) for x in defaults]
