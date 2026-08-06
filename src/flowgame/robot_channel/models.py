"""会话机器人数据模型。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
from typing import Any, Dict, List, Literal, Optional

RobotType = Literal["wecom_aibot"]
BindType = Literal["flow", "team"]
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

# 绑 AgentTeam 时推荐的输出映射（Team.output → 回发）
DEFAULT_TEAM_OUTPUT_MAPPING: List[Dict[str, str]] = [
    {"source": "output", "target": "reply_markdown"},
]


def normalize_bind_type(raw: Any) -> BindType:
    text = str(raw or "").strip().lower()
    if text in {"team", "agentteam", "agent_team"}:
        return "team"
    return "flow"


def default_team_execute_timeout_sec() -> int:
    """绑 Team 时的默认超时（秒）。"""
    try:
        return max(1, int(float(os.getenv("FLOWGAME_ROBOT_TEAM_TIMEOUT_SEC", "600"))))
    except (TypeError, ValueError):
        return 600

SECRET_MASK = "***"

DEFAULT_ROUTER_MODEL = "deepseek-v4-flash"


def normalize_employee_ids(
    raw: Any,
    *,
    legacy_employee_id: str = "",
) -> List[str]:
    """规范化数字员工 ID 列表；兼容单值 employeeId（仅列表为空时回填）。"""
    ids: List[str] = []
    if isinstance(raw, list):
        for item in raw:
            text = str(item or "").strip()
            if text and text not in ids:
                ids.append(text)
    elif raw is not None and str(raw).strip():
        text = str(raw).strip()
        ids.append(text)
    if not ids:
        legacy = (legacy_employee_id or "").strip()
        if legacy:
            ids.append(legacy)
    return ids


def default_router_model() -> str:
    return (
        os.getenv("FLOWGAME_ROBOT_ROUTER_MODEL", "").strip()
        or os.getenv("DEEPSEEK_MODEL", "").strip()
        or DEFAULT_ROUTER_MODEL
    )


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
    # 可绑定多个数字员工；≥2 时用 LLM 按员工描述自动路由
    employeeIds: List[str] = field(default_factory=list)
    # 兼容旧数据：等同 employeeIds[0]
    employeeId: str = ""
    # 路由失败时的默认员工；空则取列表第一位
    defaultEmployeeId: str = ""
    # 路由 LLM（仅多员工时使用）；Key 空则回落 DEEPSEEK_API_KEY
    routerApiKey: str = ""
    # 预置厂家：deepseek / openai / qwen / moonshot / zhipu（决定接口地址）
    routerProvider: str = "deepseek"
    # 兼容旧数据；有 routerProvider 时执行以厂家为准，忽略自定义 URL
    routerBaseUrl: str = ""
    routerModel: str = ""
    # 以下为兼容旧数据：无员工时仍可直接绑决策/任务
    # flow = 任务目标绑单个流程 methodKey；team = 绑 AgentTeam teamKey
    bindType: BindType = "flow"
    methodKey: str = ""
    teamKey: str = ""
    # 可选：决策流程（先跑，再决定是否执行任务目标）
    decisionMethodKey: str = ""
    # 执行超时（秒）；优先于数字员工；None → 员工或环境变量默认
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

    def resolved_employee_ids(self) -> List[str]:
        return normalize_employee_ids(self.employeeIds, legacy_employee_id=self.employeeId)

    def primary_employee_id(self) -> str:
        ids = self.resolved_employee_ids()
        return ids[0] if ids else ""

    def needs_employee_routing(self) -> bool:
        return len(self.resolved_employee_ids()) >= 2

    def is_bound(self) -> bool:
        """任务目标是否已绑定（优先数字员工）。"""
        if self.resolved_employee_ids():
            from src.flowgame.digital_employee.binding import robot_has_task_binding

            return robot_has_task_binding(self)
        if self.bindType == "team":
            return bool((self.teamKey or "").strip())
        return bool((self.methodKey or "").strip())

    def has_decision_flow(self) -> bool:
        if self.resolved_employee_ids():
            try:
                from src.flowgame.digital_employee.binding import resolve_robot_binding

                return resolve_robot_binding(self).has_decision_flow()
            except Exception:  # noqa: BLE001
                return False
        return bool((self.decisionMethodKey or "").strip())

    def bind_label(self) -> str:
        ids = self.resolved_employee_ids()
        if ids:
            if len(ids) == 1:
                try:
                    from src.flowgame.digital_employee.binding import resolve_robot_binding

                    return resolve_robot_binding(self).bind_label()
                except Exception:  # noqa: BLE001
                    return f"员工 {ids[0]}"
            return f"{len(ids)} 名数字员工（自动路由）"
        if self.bindType == "team":
            return (self.teamKey or "").strip() or "（未绑 Team）"
        return (self.methodKey or "").strip() or "（未绑流程）"

    def resolve_execute_timeout_sec(self) -> float:
        if self.resolved_employee_ids():
            try:
                from src.flowgame.digital_employee.binding import resolve_robot_binding

                return resolve_robot_binding(self).resolve_execute_timeout_sec(
                    self.executeTimeoutSec
                )
            except Exception:  # noqa: BLE001
                pass
        if self.executeTimeoutSec is not None and self.executeTimeoutSec > 0:
            return float(self.executeTimeoutSec)
        if self.bindType == "team":
            return float(default_team_execute_timeout_sec())
        return float(default_execute_timeout_sec())

    def to_dict(
        self,
        *,
        mask_secret: bool = True,
        worker_online: Optional[bool] = None,
        stale_sec: int = 30,
    ) -> Dict[str, Any]:
        secret = self.secret
        router_key = self.routerApiKey
        if mask_secret:
            if secret:
                secret = SECRET_MASK
            if router_key:
                router_key = SECRET_MASK
        display, message = self.display_status(
            worker_online=worker_online, stale_sec=stale_sec
        )
        employee_ids = self.resolved_employee_ids()
        return {
            "robotId": self.robotId,
            "name": self.name,
            "type": self.type,
            "botId": self.botId,
            "secret": secret,
            "hasSecret": bool(self.secret),
            "employeeIds": employee_ids,
            "employeeId": employee_ids[0] if employee_ids else "",
            "defaultEmployeeId": self.defaultEmployeeId,
            "routerApiKey": router_key,
            "hasRouterApiKey": bool(self.routerApiKey),
            "routerProvider": self.routerProvider or "deepseek",
            "routerBaseUrl": self.routerBaseUrl,
            "routerModel": self.routerModel or default_router_model(),
            "bindType": self.bindType,
            "methodKey": self.methodKey,
            "teamKey": self.teamKey,
            "decisionMethodKey": self.decisionMethodKey,
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
        bind_type = normalize_bind_type(data.get("bindType"))
        inputs = data.get("inputMapping") or DEFAULT_INPUT_MAPPING
        if "outputMapping" in data:
            outputs = data.get("outputMapping") or (
                DEFAULT_TEAM_OUTPUT_MAPPING
                if bind_type == "team"
                else DEFAULT_OUTPUT_MAPPING
            )
        else:
            outputs = (
                DEFAULT_TEAM_OUTPUT_MAPPING
                if bind_type == "team"
                else DEFAULT_OUTPUT_MAPPING
            )
        employee_ids = normalize_employee_ids(
            data.get("employeeIds"),
            legacy_employee_id=str(data.get("employeeId") or "").strip(),
        )
        return cls(
            robotId=str(data.get("robotId") or "").strip(),
            name=str(data.get("name") or "").strip(),
            type=(data.get("type") or "wecom_aibot"),  # type: ignore[arg-type]
            botId=str(data.get("botId") or "").strip(),
            secret=str(data.get("secret") or ""),
            employeeIds=employee_ids,
            employeeId=employee_ids[0] if employee_ids else "",
            defaultEmployeeId=str(data.get("defaultEmployeeId") or "").strip(),
            routerApiKey=str(data.get("routerApiKey") or ""),
            routerProvider=str(data.get("routerProvider") or "deepseek").strip() or "deepseek",
            routerBaseUrl=str(data.get("routerBaseUrl") or "").strip(),
            routerModel=str(data.get("routerModel") or "").strip(),
            bindType=bind_type,
            methodKey=str(data.get("methodKey") or "").strip(),
            teamKey=str(data.get("teamKey") or "").strip(),
            decisionMethodKey=str(data.get("decisionMethodKey") or "").strip(),
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
