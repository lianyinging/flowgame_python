"""Team Runtime：sequential / supervisor 执行主循环。"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from src.flowgame.team.builtin import (
    MASTER_SYSTEM_PROMPT,
    SUB_AGENT_SPECS,
    build_agent_catalog,
    resolve_builtin_role,
)
from src.flowgame.team.context import ContextEngine, clip
from src.flowgame.team.models import AgentTeamDef, FlowAgentConfig

logger = logging.getLogger(__name__)

ProgressCb = Optional[Callable[[Dict[str, Any]], None]]


def extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    text = (text or "").strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


@dataclass
class OrchestratorDecision:
    thinking: str = ""
    action: str = ""
    next_agent: Optional[str] = None
    focus: str = ""
    done_reason: str = ""
    raw: str = ""
    valid: bool = False
    error: str = ""


@dataclass
class TeamRunResult:
    teamKey: str
    strategy: str
    status: str
    exit_reason: str
    output: Any = None
    blackboard: Dict[str, Any] = field(default_factory=dict)
    trace: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "teamKey": self.teamKey,
            "strategy": self.strategy,
            "status": self.status,
            "exit_reason": self.exit_reason,
            "output": self.output,
            "blackboard": self.blackboard,
            "trace": self.trace,
        }


class TeamRuntimeError(Exception):
    pass


class TeamRuntime:
    """
    子 Agent 调用优先走已保存流程（methodKey）；
    若无流程或执行失败，则回退到内置角色 Prompt（demo_orchestrator 同款）。
    """

    DEFAULT_STATUS_KEYS = [
        "topic",
        "requirement",
        "target_words",
        # 情报链路（搜索/抓取）
        "documents",
        "articles",
        # 内容工厂链路
        "research",
        "outline",
        "content",
        "review",
        "article",
        # 本次运行工作目录
        "runtimeSpace",
        "runId",
    ]

    def __init__(
        self,
        team: AgentTeamDef,
        agents: Dict[str, FlowAgentConfig],
        *,
        progress_callback: ProgressCb = None,
    ) -> None:
        self.team = team
        self.agents = agents
        self.progress = progress_callback
        self.context = ContextEngine()
        self.state: Dict[str, Any] = {}
        self.trace: List[Dict[str, Any]] = []
        self._same_agent_streak = 0
        self._last_agent: Optional[str] = None
        self._llm = None

    def _emit(self, event: str, **payload: Any) -> None:
        if self.progress:
            try:
                self.progress({"event": event, **payload})
            except Exception:  # noqa: BLE001
                logger.exception("team progress callback failed")

    def _get_llm(self):
        if self._llm is None:
            from src.flowgame.tinyflow_config import DeepSeekLlmClient

            self._llm = DeepSeekLlmClient()
        return self._llm

    def _chat(self, system: str, user: str, temperature: float = 0.3) -> str:
        llm = self._get_llm()
        resp = llm.chat(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
        )
        if resp.get("error"):
            raise TeamRuntimeError(f"LLM 调用失败: {resp['error']}")
        return str(resp.get("content") or "").strip()

    def _allowed_aliases(self) -> List[str]:
        harness = self.team.harness
        if harness.allowedAgents:
            return list(harness.allowedAgents)
        return [m.alias for m in self.team.members]

    def _member_by_alias(self, alias: str) -> Optional[str]:
        """alias → agentKey"""
        for m in self.team.members:
            if m.alias == alias or m.agentKey == alias:
                return m.agentKey
        return None

    def _resolve_output_key(self, agent_key: str, alias: str) -> str:
        cfg = self.agents.get(agent_key)
        if cfg and cfg.outputKey:
            return cfg.outputKey
        if cfg and cfg.outputSchema:
            return cfg.outputSchema[0].name
        role = resolve_builtin_role(agent_key, alias)
        if role and role in SUB_AGENT_SPECS:
            return str(SUB_AGENT_SPECS[role]["output_key"])
        return alias or agent_key

    def _status_card_keys(self) -> List[str]:
        """Team 可配置主控看板字段；未配置时用默认列表。"""
        configured = [
            str(k).strip()
            for k in (self.team.statusCardKeys or [])
            if str(k).strip()
        ]
        # 去重保序
        seen: set[str] = set()
        keys: List[str] = []
        for k in configured:
            if k not in seen:
                seen.add(k)
                keys.append(k)
        return keys or list(self.DEFAULT_STATUS_KEYS)

    def _try_execute_flow(self, method_key: str, variables: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not (method_key or "").strip():
            return None
        try:
            from src.flowgame.service import flow_game_execute_service
            from src.flowgame.workflow_store import (
                FlowGameWorkflowStoreError,
                load_workflow_json_by_method_key,
            )

            workflow_json = load_workflow_json_by_method_key(method_key)
            return flow_game_execute_service.execute_workflow(
                workflow_json,
                variables=variables,
                method_key=method_key,
                flow_name=method_key,
            )
        except FlowGameWorkflowStoreError:
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("team flow execute failed methodKey=%s err=%s", method_key, exc)
            return {"_flow_error": str(exc)}

    def _extract_flow_outputs(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """从流程结果取出结束节点输出（保持 list/dict，不要整包 stringify）。

        注意：必须优先 endNodeOutput / lastNodeOutput。
        apiOutput 来自 Api开始（headers/body/statusCode），body 往往是入参
        （topic/requirement），不是结束节点的 documents；若优先 apiOutput
        会把下游黑板上的 documents 冲掉。

        Agent 流程通常关闭「输出过程详情」：此时返回体就是精简自定义字段
        （如 menuContent / menuStatus），没有 endNodeOutput 外壳，必须整包认作产出。
        """
        if not isinstance(result, dict) or not result:
            return {}

        merged: Dict[str, Any] = {}
        for bag_name in ("endNodeOutput", "lastNodeOutput"):
            bag = result.get(bag_name)
            if isinstance(bag, dict) and bag:
                merged.update(bag)
        if merged:
            return merged

        # Api接口结束关闭过程详情：响应顶层即自定义输出参数
        skip_top = {
            "status",
            "message",
            "methodKey",
            "nodeExecutions",
            "apiOutput",
            "endNodeOutput",
            "lastNodeOutput",
            "apiDescription",
            "requestType",
            "externalUrl",
            "_flow_error",
        }
        slim = {
            k: v
            for k, v in result.items()
            if k not in skip_top and v is not None
        }
        # 精简响应：只要有任意业务字段就整包写回（含 menuContent 等，不维护白名单）
        # 完整响应通常还有 nodeExecutions/apiOutput，slim 为空或只剩杂项时走后面分支
        if slim and not any(k in result for k in ("nodeExecutions", "apiOutput")):
            return slim
        # 兼容：完整壳里偶发顶层也带了业务字段
        if slim and any(
            k in slim
            for k in (
                "documents",
                "articles",
                "article",
                "content",
                "decision",
                "output",
                "research",
                "outline",
                "review",
                "menuContent",
                "menuStatus",
                "menu",
                "currentSearch",
                "documentNull",
            )
        ):
            return slim

        # 无结束输出时再看 apiOutput：若 body 里已是结束字段则摊平
        api = result.get("apiOutput")
        if isinstance(api, dict) and api:
            body = api.get("body")
            if isinstance(body, dict) and any(
                k in body
                for k in (
                    "documents",
                    "articles",
                    "article",
                    "content",
                    "decision",
                    "menuContent",
                    "menuStatus",
                    "menu",
                    "currentSearch",
                )
            ):
                return dict(body)
            # 最后手段：不要把 headers/statusCode 当业务字段写回
            if isinstance(body, dict) and body:
                return dict(body)

        nodes = result.get("nodeExecutions") or []
        if isinstance(nodes, list):
            for node in reversed(nodes):
                if not isinstance(node, dict):
                    continue
                ntype = str(node.get("nodeType") or "")
                # 跳过开始节点，避免把入参 body 当成产出
                if ntype in ("node_start_api", "startNode", "node_start_talk"):
                    continue
                out = node.get("output")
                if isinstance(out, dict) and out:
                    if ntype in ("endNode", "node_end_api") or "documents" in out or "articles" in out or "menuContent" in out:
                        return dict(out)
            # 再扫一遍非开始节点的最后输出
            for node in reversed(nodes):
                if not isinstance(node, dict):
                    continue
                ntype = str(node.get("nodeType") or "")
                if ntype in ("node_start_api", "startNode", "node_start_talk"):
                    continue
                out = node.get("output")
                if isinstance(out, dict) and out:
                    return dict(out)
        return {}

    def _extract_flow_text(self, result: Dict[str, Any], output_key: str) -> str:
        outputs = self._extract_flow_outputs(result)
        if output_key in outputs and outputs[output_key] is not None:
            val = outputs[output_key]
            return val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)
        if "output" in outputs and outputs["output"] is not None:
            val = outputs["output"]
            return val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)
        if "decision" in outputs and outputs["decision"] is not None:
            val = outputs["decision"]
            return val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)
        if outputs:
            return json.dumps(outputs, ensure_ascii=False)[:4000]
        return json.dumps(result, ensure_ascii=False)[:4000]

    def invoke_worker(self, alias: str, focus: str = "") -> str:
        agent_key = self._member_by_alias(alias) or alias
        cfg = self.agents.get(agent_key)
        role = resolve_builtin_role(agent_key, alias)
        output_key = self._resolve_output_key(agent_key, alias)

        variables: Dict[str, Any] = dict(self.state)
        variables["focus"] = focus or "按你的职责完成任务"

        method_key = (cfg.methodKey if cfg else "") or ""
        flow_result = self._try_execute_flow(method_key, variables)
        if flow_result and flow_result.get("_flow_error"):
            raise TeamRuntimeError(
                f"子 Agent「{alias}」流程执行失败（methodKey={method_key or agent_key}）："
                f"{flow_result.get('_flow_error')}"
            )
        if flow_result and not flow_result.get("_flow_error"):
            outputs = self._extract_flow_outputs(flow_result)
            # 整包写回黑板，供下游 Agent 引用 documents / articles 等
            for k, v in outputs.items():
                if k and v is not None and k not in ("headers", "statusCode"):
                    self.state[k] = v
            # 兼容：结束输出在 body 嵌套时再摊一层 documents
            body = outputs.get("body")
            if isinstance(body, dict):
                for k, v in body.items():
                    if k and v is not None and k not in self.state:
                        self.state[k] = v
            if output_key and output_key not in outputs and output_key not in self.state:
                text = self._extract_flow_text(flow_result, output_key)
                self.state[output_key] = text
                return text
            primary = self.state.get(output_key)
            if primary is None:
                primary = outputs.get(output_key)
            if primary is None and outputs:
                for k in ("documents", "articles", "article", "content", "output"):
                    if k in self.state:
                        primary = self.state[k]
                        break
                    if k in outputs:
                        primary = outputs[k]
                        break
            if primary is None:
                primary = self._extract_flow_text(flow_result, output_key)
            self.state[output_key] = primary
            return primary if isinstance(primary, str) else json.dumps(primary, ensure_ascii=False)

        # 内置 Prompt 回退
        if role and role in SUB_AGENT_SPECS:
            spec = SUB_AGENT_SPECS[role]
            packed = self.context.pack_for_worker(role, self.state, focus)
            user = spec["user_template"].format_map(
                {**{k: "" for k in spec["input_keys"]}, **packed, "focus": packed["focus"]}
            )
            text = self._chat(spec["system"], user, temperature=float(spec["temperature"]))
            self.state[spec["output_key"]] = text
            return text

        # 配置了 systemPrompt / userTemplate
        if cfg and (cfg.systemPrompt or cfg.userTemplate):
            input_keys = [f.name for f in cfg.inputSchema] or list(self.state.keys())
            packed = self.context.pack_for_worker(alias, self.state, focus, input_keys=input_keys)
            template = cfg.userTemplate or "请根据以下上下文完成任务：\n{focus}\n\n{topic}"
            try:
                user = template.format_map({**{k: "" for k in packed}, **packed})
            except Exception:  # noqa: BLE001
                user = template + "\n\n" + json.dumps(packed, ensure_ascii=False)
            system = cfg.systemPrompt or f"你是子 Agent「{cfg.name or alias}」。"
            text = self._chat(system, user, temperature=float(cfg.temperature or 0.4))
            self.state[output_key] = text
            return text

        raise TeamRuntimeError(
            f"子 Agent「{alias}」无法执行：未找到 methodKey 流程，且无内置角色/Prompt。"
            f"请保存流程 {method_key or agent_key}，或使用内置角色名（researcher/writer/…）。"
        )

    def ask_supervisor(self, step_idx: int, repair_hint: str = "") -> OrchestratorDecision:
        allowed = self._allowed_aliases()
        catalog = build_agent_catalog(allowed)
        status_keys = self._status_card_keys()
        system = MASTER_SYSTEM_PROMPT.format(agent_catalog=catalog)
        user = self.context.pack_for_master(
            self.state,
            self.trace,
            step_idx,
            self.team.harness.maxSteps,
            status_keys,
        )
        if repair_hint:
            user = user + "\n\n" + repair_hint

        # 尝试主控流程
        supervisor_key = self.team.supervisorAgentKey or ""
        cfg = self.agents.get(supervisor_key) if supervisor_key else None
        method_key = cfg.methodKey if cfg else ""
        if method_key:
            vars_ = {
                **self.state,
                "status_card": self.context.status_card(self.state, status_keys),
                "recent_trace": json.dumps(self.trace[-8:], ensure_ascii=False),
                "agent_catalog": catalog,
            }
            flow_result = self._try_execute_flow(method_key, vars_)
            if flow_result and not flow_result.get("_flow_error"):
                raw = self._extract_flow_text(flow_result, "decision")
                return self._parse_and_validate_decision(raw, allowed)

        raw = self._chat(system, user, temperature=0.2)
        return self._parse_and_validate_decision(raw, allowed)

    def _parse_and_validate_decision(
        self, raw: str, allowed: List[str]
    ) -> OrchestratorDecision:
        decision = OrchestratorDecision(raw=raw)
        obj = extract_json_object(raw)
        if not obj:
            decision.error = "无法解析 JSON 决策"
            return decision

        decision.thinking = str(obj.get("thinking") or "").strip()
        decision.action = str(obj.get("action") or "").strip().upper()
        next_agent = obj.get("next_agent")
        decision.next_agent = (
            None if next_agent in (None, "null", "") else str(next_agent).strip()
        )
        decision.focus = str(obj.get("focus") or "").strip()
        decision.done_reason = str(obj.get("done_reason") or "").strip()

        if decision.action not in {"CALL_AGENT", "FINISH"}:
            decision.error = f"非法 action: {decision.action}"
            return decision

        if decision.action == "FINISH":
            decision.valid = True
            return decision

        if not decision.next_agent:
            decision.error = "CALL_AGENT 但 next_agent 为空"
            return decision
        if decision.next_agent not in allowed:
            decision.error = f"next_agent 不在白名单: {decision.next_agent}"
            return decision

        if (
            decision.next_agent == self._last_agent
            and self._same_agent_streak >= self.team.harness.maxSameAgentStreak
        ):
            decision.error = (
                f"禁止连续第 {self._same_agent_streak + 1} 次调用 "
                f"{decision.next_agent}，请换其它 Agent 或 FINISH"
            )
            return decision

        decision.valid = True
        return decision

    def decide_with_retries(self, step_idx: int) -> OrchestratorDecision:
        decision = self.ask_supervisor(step_idx)
        retries = 0
        max_retries = self.team.harness.maxDecisionRetries
        while not decision.valid and retries < max_retries:
            retries += 1
            self._emit(
                "decision_retry",
                step=step_idx,
                error=decision.error,
                retry=retries,
            )
            hint = (
                f"上一次输出非法：{decision.error}\n"
                f"上一次原文：\n{clip(decision.raw, 800)}\n"
                "请重新输出合法 JSON 决策。"
            )
            decision = self.ask_supervisor(step_idx, repair_hint=hint)
        return decision

    def run(self, variables: Optional[Dict[str, Any]] = None) -> TeamRunResult:
        self.state = {}
        for k, v in (self.team.blackboardDefaults or {}).items():
            if v is not None and str(v) != "":
                self.state[k] = v
        for k, v in (variables or {}).items():
            if v is not None:
                self.state[k] = v

        if not str(self.state.get("topic") or "").strip():
            raise TeamRuntimeError("variables.topic 不能为空")

        # 为本次运行创建临时工作目录，路径写入黑板供子 Agent / 后续 WebSocket 使用
        try:
            from src.flowgame.runtime_space import (
                BLACKBOARD_RUN_ID,
                BLACKBOARD_RUNTIME_SPACE,
                create_team_runtime_dir,
            )

            # 允许调用方预传 runId；未传则自动生成
            preset_run_id = str(self.state.get(BLACKBOARD_RUN_ID) or "").strip() or None
            run_id, space_path = create_team_runtime_dir(
                self.team.teamKey or "team",
                run_id=preset_run_id,
            )
            self.state[BLACKBOARD_RUN_ID] = run_id
            self.state[BLACKBOARD_RUNTIME_SPACE] = str(space_path)
        except OSError as exc:
            raise TeamRuntimeError(f"创建 runtimeSpace 失败: {exc}") from exc

        self.trace = []
        self._same_agent_streak = 0
        self._last_agent = None
        strategy = self.team.strategy

        self._emit(
            "team_started",
            teamKey=self.team.teamKey,
            strategy=strategy,
            state=dict(self.state),
            runId=self.state.get("runId"),
            runtimeSpace=self.state.get("runtimeSpace"),
        )

        if strategy == "sequential":
            return self._run_sequential()
        if strategy == "supervisor":
            return self._run_supervisor()
        if strategy == "loop_until":
            # 一期：用 sequential 成员列表跑一轮；完整 loop_until 后续补
            return self._run_sequential(exit_reason_prefix="loop_until_once")
        raise TeamRuntimeError(f"不支持的策略: {strategy}")

    def _finish(
        self,
        exit_reason: str,
        status: str = "success",
    ) -> TeamRunResult:
        primary = self.team.outputPrimaryKey or "article"
        output = self.state.get(primary)
        if output is None:
            for key in ("article", "report_md", "content", "output"):
                if self.state.get(key):
                    output = self.state[key]
                    break
        result = TeamRunResult(
            teamKey=self.team.teamKey,
            strategy=self.team.strategy,
            status=status,
            exit_reason=exit_reason,
            output=output,
            blackboard=dict(self.state),
            trace=list(self.trace),
        )
        self._emit("team_finished", **result.to_dict())
        return result

    def _run_sequential(self, exit_reason_prefix: str = "sequential") -> TeamRunResult:
        for idx, member in enumerate(self.team.members, 1):
            alias = member.alias
            self._emit("agent_started", step=idx, agent=alias)
            try:
                text = self.invoke_worker(alias, focus="")
                self.trace.append(
                    {
                        "step": idx,
                        "action": "CALL_AGENT",
                        "next_agent": alias,
                        "ok": True,
                        "note": f"ok ({len(text)} chars)",
                    }
                )
                self._emit("agent_finished", step=idx, agent=alias, ok=True)
            except Exception as exc:  # noqa: BLE001
                self.trace.append(
                    {
                        "step": idx,
                        "action": "CALL_AGENT",
                        "next_agent": alias,
                        "ok": False,
                        "note": str(exc),
                    }
                )
                self._emit("agent_finished", step=idx, agent=alias, ok=False, error=str(exc))
                self.state["exit_reason"] = "agent_error"
                return self._finish("agent_error", status="error")
        return self._finish(f"{exit_reason_prefix}_done")

    def _run_supervisor(self) -> TeamRunResult:
        if not self.team.supervisorAgentKey:
            raise TeamRuntimeError("supervisor 策略须配置 supervisorAgentKey")
        if not self.team.members:
            raise TeamRuntimeError("Team 成员不能为空")

        max_steps = max(1, int(self.team.harness.maxSteps or 12))
        for step_idx in range(1, max_steps + 1):
            self._emit("supervisor_decide", step=step_idx, maxSteps=max_steps)
            decision = self.decide_with_retries(step_idx)

            if not decision.valid:
                note = f"决策最终非法，强制 FINISH：{decision.error}"
                self.trace.append(
                    {
                        "step": step_idx,
                        "action": "FORCE_FINISH",
                        "next_agent": None,
                        "ok": False,
                        "note": note,
                        "thinking": decision.thinking,
                        "raw": decision.raw,
                    }
                )
                self.state["exit_reason"] = "invalid_decision"
                return self._finish("invalid_decision", status="error")

            self._emit(
                "supervisor_decision",
                step=step_idx,
                action=decision.action,
                next_agent=decision.next_agent,
                thinking=decision.thinking,
            )

            if decision.action == "FINISH":
                self.trace.append(
                    {
                        "step": step_idx,
                        "action": "FINISH",
                        "next_agent": None,
                        "ok": True,
                        "note": decision.done_reason or "主控宣布完成",
                        "thinking": decision.thinking,
                    }
                )
                self.state["exit_reason"] = "master_finish"
                self.state["done_reason"] = decision.done_reason
                return self._finish("master_finish")

            alias = decision.next_agent or ""
            try:
                text = self.invoke_worker(alias, focus=decision.focus)
                ok, note = True, f"ok ({len(text)} chars)"
            except Exception as exc:  # noqa: BLE001
                ok, note = False, f"子Agent异常: {exc}"
                logger.exception("worker failed alias=%s", alias)

            if alias == self._last_agent:
                self._same_agent_streak += 1
            else:
                self._same_agent_streak = 1
                self._last_agent = alias

            self.trace.append(
                {
                    "step": step_idx,
                    "action": "CALL_AGENT",
                    "next_agent": alias,
                    "ok": ok,
                    "note": note,
                    "thinking": decision.thinking,
                    "focus": decision.focus,
                }
            )
            self._emit("agent_finished", step=step_idx, agent=alias, ok=ok, note=note)
            if not ok:
                self.state["exit_reason"] = "agent_error"
                return self._finish("agent_error", status="error")

        self.state["exit_reason"] = "max_steps"
        return self._finish("max_steps")
