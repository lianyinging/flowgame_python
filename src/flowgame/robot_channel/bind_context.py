"""机器人绑定上下文：注入黑板变量、Topic 兜底、Team 结果扁平化。"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Mapping, Optional

from src.flowgame.robot_channel.mapping import coerce_reply_text
from src.flowgame.robot_channel.models import SessionRobot
from src.flowgame.robot_channel.qiyeweixing.wecom._util import (
    ENV_BOT_ID,
    ENV_BOT_SECRET,
    ENV_CHATID,
    ENV_ROBOT_ID,
)

# 可注入黑板供动态代码使用；扁平化回发结果时脱敏，避免明文进 reply 映射/日志
SECRET_BLACKBOARD_KEYS = frozenset({"wecomBotSecret", "botSecret", "secret"})


def scrub_secret_fields(payload: Dict[str, Any]) -> Dict[str, Any]:
    """去掉凭证字段（就地修改并返回同一 dict）。"""
    for key in SECRET_BLACKBOARD_KEYS:
        payload.pop(key, None)
    return payload


def enrich_robot_variables(
    robot: SessionRobot,
    variables: Dict[str, Any],
    *,
    meta: Optional[Mapping[str, Any]] = None,
    binding: Any = None,
) -> Dict[str, Any]:
    """写入机器人相关入参（供单流程 variables / Team 黑板共用）。"""
    meta = meta or {}
    variables.setdefault("robotId", robot.robotId)
    variables.setdefault(
        "sessionId",
        meta.get("target") or meta.get("userid") or variables.get("chatId") or "",
    )

    bind_type = getattr(binding, "bindType", None) or robot.bindType
    team_key = getattr(binding, "teamKey", None) or robot.teamKey
    method_key = getattr(binding, "methodKey", None) or robot.methodKey
    decision_key = getattr(binding, "decisionMethodKey", None) or robot.decisionMethodKey
    employee_id = getattr(binding, "employeeId", None) or robot.employeeId

    variables.setdefault("bindType", bind_type)
    if employee_id:
        variables.setdefault("employeeId", employee_id)
    if bind_type == "team" and team_key:
        variables.setdefault("teamKey", team_key)
    if method_key:
        variables.setdefault("methodKey", method_key)
    if decision_key:
        variables.setdefault("decisionMethodKey", decision_key)

    # 凭证：配置里已有 botId/secret，一并注入黑板供动态代码显式传参
    if robot.botId:
        variables.setdefault("botId", robot.botId)
    if robot.secret:
        variables.setdefault("wecomBotSecret", robot.secret)

    try:
        from src.flowgame.robot_space import ensure_robot_workspace

        variables.setdefault(
            "robotSpace",
            str(ensure_robot_workspace(robot.robotId, robot.type)),
        )
    except Exception:  # noqa: BLE001
        pass

    # chatId 兜底：mapping 未写时从 meta.target 补
    if not str(variables.get("chatId") or "").strip():
        chat = meta.get("target") or meta.get("chatid") or ""
        if chat:
            variables["chatId"] = chat
    if not str(variables.get("userId") or "").strip() and meta.get("userid"):
        variables["userId"] = meta.get("userid")
    if not str(variables.get("chatType") or "").strip() and meta.get("chattype"):
        variables["chatType"] = meta.get("chattype")

    return variables


def ensure_team_topic(variables: Dict[str, Any], *, inbound_text: str = "") -> str:
    """保证 Team 所需 topic：topic → message → 原始文本。"""
    topic = str(variables.get("topic") or "").strip()
    if topic:
        return topic
    message = str(variables.get("message") or "").strip()
    if message:
        variables["topic"] = message
        return message
    text = (inbound_text or "").strip()
    if text:
        variables["topic"] = text
        if not str(variables.get("message") or "").strip():
            variables["message"] = text
        return text
    raise ValueError("绑 AgentTeam 时 topic/message 不能为空")


def flatten_team_result(result: Any) -> Dict[str, Any]:
    """把 TeamRunResult 摊成可做 outputMapping 的业务字典（不含 secret）。"""
    if hasattr(result, "to_dict"):
        data = result.to_dict()
    elif isinstance(result, dict):
        data = dict(result)
    else:
        return {}

    blackboard = data.get("blackboard")
    payload: Dict[str, Any] = {}
    if isinstance(blackboard, dict):
        payload.update(blackboard)

    output = data.get("output")
    if output is not None:
        payload.setdefault("output", output)
        # 兼容仍映射 assistantMessage 的旧配置
        if "assistantMessage" not in payload:
            payload["assistantMessage"] = output

    for key in ("teamKey", "strategy", "status", "exit_reason"):
        if key in data and data[key] is not None:
            payload.setdefault(key, data[key])
    return scrub_secret_fields(payload)


def team_reply_fallback(payload: Mapping[str, Any]) -> Optional[str]:
    """映射未命中时，尝试从 Team 扁平结果取一段回发文案。"""
    for key in ("output", "assistantMessage", "article", "report_md", "content"):
        text = coerce_reply_text(payload.get(key))
        if text:
            return text
    return None


def _coerce_should_run(raw: Any, *, default: bool = True) -> bool:
    """解析决策流程 shouldRun；字段缺失时默认 True（仅补齐入参也可放行）。"""
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    text = str(raw).strip().lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "y", "run", "ok", "是"}:
        return True
    if text in {"0", "false", "no", "n", "skip", "否"}:
        return False
    return default


def apply_decision_result(
    variables: Dict[str, Any],
    decision_result: Any,
) -> Dict[str, Any]:
    """解析决策流程结果，合并进 variables，并写入 shouldRun / decisionReason。

    回发文案不在这里取——由机器人配置的 ``outputMapping`` 对决策结果做映射。
    决策结束节点建议产出：
      - shouldRun: bool（是否执行任务目标）
      - 回发相关字段（如 output / assistantMessage）供输出映射使用
      - topic 及其它黑板字段
      - reason: 可选说明
    """
    from src.flowgame.robot_channel.mapping import extract_business_payload

    payload = extract_business_payload(decision_result)
    if not isinstance(payload, dict):
        payload = {}

    # 合并决策产出（不覆盖机器人系统键 / 不写入明文 secret 别名）
    protect = {
        "robotId",
        "robotSpace",
        "botId",
        "wecomBotSecret",
        "bindType",
        "decisionMethodKey",
        "employeeId",
        *SECRET_BLACKBOARD_KEYS,
    }
    for key, value in payload.items():
        if not key or key in protect:
            continue
        if value is None:
            continue
        variables[key] = value

    should_raw = None
    for key in ("shouldRun", "should_run", "run"):
        if key in payload:
            should_raw = payload.get(key)
            break
    should_run = _coerce_should_run(should_raw, default=True)
    variables["shouldRun"] = should_run

    reason = payload.get("reason") or payload.get("decisionReason") or ""
    if reason:
        variables["decisionReason"] = str(reason)

    return {
        "shouldRun": should_run,
        "reason": str(reason or ""),
        "payload": payload,
    }


@contextmanager
def robot_wecom_env(robot: SessionRobot, variables: Mapping[str, Any]) -> Iterator[None]:
    """Team/流程执行期间临时写入企微凭证 env，供动态代码 aibot 解析。"""
    keys = (ENV_BOT_ID, ENV_BOT_SECRET, ENV_CHATID, ENV_ROBOT_ID)
    saved = {k: os.environ.get(k) for k in keys}
    try:
        if robot.botId:
            os.environ[ENV_BOT_ID] = robot.botId
        if robot.secret:
            os.environ[ENV_BOT_SECRET] = robot.secret
        if robot.robotId:
            os.environ[ENV_ROBOT_ID] = robot.robotId
        chat = str(variables.get("chatId") or "").strip()
        if chat:
            os.environ[ENV_CHATID] = chat
        yield
    finally:
        for k, old in saved.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old
