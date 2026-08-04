"""数字员工数据模型。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.flowgame.robot_channel.models import (
    BindType,
    normalize_bind_type,
    parse_execute_timeout_sec,
)


@dataclass
class DigitalEmployee:
    """数字员工：决策目标 + 任务目标（流程或 AgentTeam）。"""

    employeeId: str = ""
    name: str = ""
    description: str = ""
    # 可选：决策流程 methodKey
    decisionMethodKey: str = ""
    # flow = 任务目标绑单个流程；team = 绑 AgentTeam
    bindType: BindType = "flow"
    methodKey: str = ""
    teamKey: str = ""
    executeTimeoutSec: Optional[int] = None
    createdAt: str = ""
    updatedAt: str = ""

    def is_bound(self) -> bool:
        if self.bindType == "team":
            return bool((self.teamKey or "").strip())
        return bool((self.methodKey or "").strip())

    def has_decision_flow(self) -> bool:
        return bool((self.decisionMethodKey or "").strip())

    def bind_label(self) -> str:
        if self.bindType == "team":
            return (self.teamKey or "").strip() or "（未绑 Team）"
        return (self.methodKey or "").strip() or "（未绑流程）"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "employeeId": self.employeeId,
            "name": self.name,
            "description": self.description,
            "decisionMethodKey": self.decisionMethodKey,
            "bindType": self.bindType,
            "methodKey": self.methodKey,
            "teamKey": self.teamKey,
            "executeTimeoutSec": self.executeTimeoutSec,
            "createdAt": self.createdAt,
            "updatedAt": self.updatedAt,
            "bound": self.is_bound(),
            "bindLabel": self.bind_label(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DigitalEmployee":
        return cls(
            employeeId=str(data.get("employeeId") or "").strip(),
            name=str(data.get("name") or "").strip(),
            description=str(data.get("description") or "").strip(),
            decisionMethodKey=str(data.get("decisionMethodKey") or "").strip(),
            bindType=normalize_bind_type(data.get("bindType")),
            methodKey=str(data.get("methodKey") or "").strip(),
            teamKey=str(data.get("teamKey") or "").strip(),
            executeTimeoutSec=parse_execute_timeout_sec(data.get("executeTimeoutSec")),
            createdAt=str(data.get("createdAt") or ""),
            updatedAt=str(data.get("updatedAt") or ""),
        )
