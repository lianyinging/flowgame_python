"""Team / Agent 数据模型（对齐多 Agent 协同架构方案）。"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AgentSchemaField:
    name: str
    dataType: str = "String"
    required: bool = False
    description: str = ""

    @classmethod
    def from_dict(cls, raw: Any) -> "AgentSchemaField":
        if not isinstance(raw, dict):
            return cls(name="")
        return cls(
            name=str(raw.get("name") or "").strip(),
            dataType=str(raw.get("dataType") or "String"),
            required=bool(raw.get("required")),
            description=str(raw.get("description") or ""),
        )


@dataclass
class FlowAgentConfig:
    agentKey: str
    methodKey: str
    redisKey: str = ""
    name: str = ""
    description: str = ""
    version: str = "1.0.0"
    published: bool = True
    timeoutMs: int = 120000
    tags: List[str] = field(default_factory=list)
    inputSchema: List[AgentSchemaField] = field(default_factory=list)
    outputSchema: List[AgentSchemaField] = field(default_factory=list)
    updatedAt: str = ""
    # 内联执行用（无画布流程时）
    systemPrompt: str = ""
    userTemplate: str = ""
    outputKey: str = ""
    temperature: float = 0.4

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "FlowAgentConfig":
        inputs = [AgentSchemaField.from_dict(x) for x in (raw.get("inputSchema") or [])]
        outputs = [AgentSchemaField.from_dict(x) for x in (raw.get("outputSchema") or [])]
        return cls(
            agentKey=str(raw.get("agentKey") or "").strip(),
            methodKey=str(raw.get("methodKey") or "").strip(),
            redisKey=str(raw.get("redisKey") or ""),
            name=str(raw.get("name") or "").strip(),
            description=str(raw.get("description") or ""),
            version=str(raw.get("version") or "1.0.0"),
            published=bool(raw.get("published", True)),
            timeoutMs=int(raw.get("timeoutMs") or 120000),
            tags=[str(t) for t in (raw.get("tags") or [])],
            inputSchema=[f for f in inputs if f.name],
            outputSchema=[f for f in outputs if f.name],
            updatedAt=str(raw.get("updatedAt") or ""),
            systemPrompt=str(raw.get("systemPrompt") or ""),
            userTemplate=str(raw.get("userTemplate") or ""),
            outputKey=str(raw.get("outputKey") or ""),
            temperature=float(raw.get("temperature") or 0.4),
        )

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


@dataclass
class AgentTeamMember:
    agentKey: str
    alias: str

    @classmethod
    def from_dict(cls, raw: Any) -> "AgentTeamMember":
        if not isinstance(raw, dict):
            return cls(agentKey="", alias="")
        key = str(raw.get("agentKey") or "").strip()
        alias = str(raw.get("alias") or key).strip()
        return cls(agentKey=key, alias=alias)


@dataclass
class AgentTeamHarness:
    maxSteps: int = 12
    maxSameAgentStreak: int = 2
    maxDecisionRetries: int = 2
    maxTokenBudget: int = 200000
    allowedAgents: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: Any) -> "AgentTeamHarness":
        if not isinstance(raw, dict):
            return cls()
        return cls(
            maxSteps=int(raw.get("maxSteps") or 12),
            maxSameAgentStreak=int(raw.get("maxSameAgentStreak") or 2),
            maxDecisionRetries=int(raw.get("maxDecisionRetries") or 2),
            maxTokenBudget=int(raw.get("maxTokenBudget") or 200000),
            allowedAgents=[str(a) for a in (raw.get("allowedAgents") or [])],
        )


@dataclass
class AgentTeamDef:
    teamKey: str
    name: str
    description: str = ""
    strategy: str = "supervisor"  # sequential | loop_until | supervisor
    members: List[AgentTeamMember] = field(default_factory=list)
    supervisorAgentKey: Optional[str] = None
    blackboardDefaults: Dict[str, str] = field(default_factory=dict)
    # 主控看板字段（status_card）；空则 Runtime 用 DEFAULT_STATUS_KEYS
    statusCardKeys: List[str] = field(default_factory=list)
    harness: AgentTeamHarness = field(default_factory=AgentTeamHarness)
    outputPrimaryKey: str = ""
    updatedAt: str = ""

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "AgentTeamDef":
        members = [AgentTeamMember.from_dict(m) for m in (raw.get("members") or [])]
        members = [m for m in members if m.agentKey]
        status_keys_raw = raw.get("statusCardKeys") or []
        status_keys: List[str] = []
        if isinstance(status_keys_raw, str):
            status_keys = [
                p.strip()
                for p in re.split(r"[,|\n]", status_keys_raw)
                if p and str(p).strip()
            ]
        elif isinstance(status_keys_raw, (list, tuple)):
            for item in status_keys_raw:
                key = str(item).strip()
                if key and key not in status_keys:
                    status_keys.append(key)
        return cls(
            teamKey=str(raw.get("teamKey") or "").strip(),
            name=str(raw.get("name") or "").strip(),
            description=str(raw.get("description") or ""),
            strategy=str(raw.get("strategy") or "supervisor").strip().lower(),
            members=members,
            supervisorAgentKey=(
                str(raw.get("supervisorAgentKey")).strip()
                if raw.get("supervisorAgentKey")
                else None
            ),
            blackboardDefaults={
                str(k): str(v) for k, v in (raw.get("blackboardDefaults") or {}).items()
            },
            statusCardKeys=status_keys,
            harness=AgentTeamHarness.from_dict(raw.get("harness")),
            outputPrimaryKey=str(raw.get("outputPrimaryKey") or ""),
            updatedAt=str(raw.get("updatedAt") or ""),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "teamKey": self.teamKey,
            "name": self.name,
            "description": self.description,
            "strategy": self.strategy,
            "members": [asdict(m) for m in self.members],
            "supervisorAgentKey": self.supervisorAgentKey,
            "blackboardDefaults": self.blackboardDefaults,
            "statusCardKeys": list(self.statusCardKeys),
            "harness": asdict(self.harness),
            "outputPrimaryKey": self.outputPrimaryKey,
            "updatedAt": self.updatedAt,
        }
