"""会话机器人：按数字员工描述做 LLM 自动路由（无记忆/TTL）。"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.flowgame.digital_employee.models import DigitalEmployee
from src.flowgame.llm import LlmClient

logger = logging.getLogger("flowgame.session_robot.router")

DEFAULT_ROUTER_MODEL = "deepseek-v4-flash"
DEFAULT_ROUTER_BASE_URL = "https://api.deepseek.com"


@dataclass
class RouteResult:
    """路由结果。guideReply 非空时不应执行员工任务，直接回发引导。"""

    employeeId: str = ""
    reason: str = ""
    guideReply: str = ""

    @property
    def should_guide(self) -> bool:
        return bool((self.guideReply or "").strip())


def default_router_model() -> str:
    return (
        os.getenv("FLOWGAME_ROBOT_ROUTER_MODEL", "").strip()
        or os.getenv("DEEPSEEK_MODEL", "").strip()
        or DEFAULT_ROUTER_MODEL
    )


def default_router_base_url() -> str:
    return (
        os.getenv("FLOWGAME_ROBOT_ROUTER_BASE_URL", "").strip()
        or os.getenv("DEEPSEEK_BASE_URL", "").strip()
        or DEFAULT_ROUTER_BASE_URL
    )


def resolve_router_api_key(robot_api_key: str = "") -> str:
    key = (robot_api_key or "").strip()
    if key:
        return key
    return os.getenv("DEEPSEEK_API_KEY", "").strip()


def build_capability_guide(employees: Sequence[DigitalEmployee]) -> str:
    """根据数字员工列表生成默认能力引导文案。"""
    lines: List[str] = []
    for emp in employees:
        if not emp:
            continue
        name = (emp.name or "").strip() or emp.employeeId
        desc = (emp.description or "").strip()
        if desc:
            lines.append(f"- **{name}**：{desc}")
        else:
            lines.append(f"- **{name}**")
    catalog = "\n".join(lines) if lines else "- （暂未配置可用能力）"
    return (
        "你好，我暂时无法处理这条消息（可能是闲聊，或意图不够明确）。\n"
        "我目前可以帮你做这些事：\n"
        f"{catalog}\n"
        "请直接说明你的具体需求，我会为你匹配对应能力。"
    )


def _build_prompt(employees: Sequence[DigitalEmployee], message: str) -> List[Dict[str, str]]:
    lines = []
    for emp in employees:
        desc = (emp.description or "").strip() or "（无描述）"
        lines.append(
            f"- employeeId: {emp.employeeId}\n"
            f"  name: {emp.name}\n"
            f"  description: {desc}"
        )
    catalog = "\n".join(lines)
    system = (
        "你是会话机器人的意图路由助手，负责把用户消息分配给最合适的数字员工，"
        "或在无法服务时给出能力引导。\n"
        "\n"
        "判断规则：\n"
        "1) 用户意图清晰，且与某位数字员工的 description 明显匹配 → action=route，"
        "填写该员工的 employeeId（必须来自列表，禁止编造）。\n"
        "2) 闲聊/打招呼/感谢/无意义内容、意图模糊、或与所有员工职责都不相关 → action=guide。\n"
        "   - guideReply 用简洁友好的中文：先说明暂时帮不了当前这句话，"
        "再基于下方员工的 name+description 列出「我可以做什么」，引导用户换具体需求提问。\n"
        "3) 多个员工都可能相关时，选匹配度最高的一位；仍无法判断则 action=guide。\n"
        "\n"
        "只输出一个 JSON 对象，不要其它文字或 markdown 代码块。\n"
        'route 格式：{"action":"route","employeeId":"...","reason":"简短原因"}\n'
        'guide 格式：{"action":"guide","reason":"闲聊|意图不明|不相关","guideReply":"引导文案"}'
    )
    user = (
        f"可选数字员工：\n{catalog}\n\n"
        f"用户消息：\n{(message or '').strip() or '（空）'}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _extract_json_object(content: str) -> Optional[Dict[str, Any]]:
    text = (content or "").strip()
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.I)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    # 容错：截取第一个 { ... }
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            return None
    return None


def _resolve_employee_id_from_data(
    data: Dict[str, Any],
    allowed: Dict[str, DigitalEmployee],
) -> str:
    eid = str(data.get("employeeId") or data.get("id") or "").strip()
    if eid in allowed:
        return eid
    name = str(data.get("name") or "").strip()
    if name:
        for emp in allowed.values():
            if emp.name == name:
                return emp.employeeId
    return ""


def _parse_route_result(
    content: str,
    allowed: Dict[str, DigitalEmployee],
    employees: Sequence[DigitalEmployee],
) -> RouteResult:
    data = _extract_json_object(content)
    if not data:
        # 兜底：正文里出现唯一合法 employeeId
        hits = [eid for eid in allowed if eid in (content or "")]
        if len(hits) == 1:
            return RouteResult(employeeId=hits[0], reason="从正文解析到唯一员工")
        return RouteResult(reason="路由结果无法解析")

    action = str(data.get("action") or "").strip().lower()
    reason = str(data.get("reason") or "").strip()
    guide_reply = str(
        data.get("guideReply") or data.get("reply") or data.get("message") or ""
    ).strip()
    eid = _resolve_employee_id_from_data(data, allowed)

    # 显式 guide，或未给出合法员工
    if action in {"guide", "help", "clarify", "unknown", "chat"}:
        return RouteResult(
            reason=reason or "需要引导",
            guideReply=guide_reply or build_capability_guide(employees),
        )
    if action in {"route", "assign", ""} and eid:
        return RouteResult(employeeId=eid, reason=reason or f"LLM 路由选中 {eid}")
    if eid and action not in {"guide", "help", "clarify", "unknown", "chat"}:
        # 兼容旧格式：仅有 employeeId
        return RouteResult(employeeId=eid, reason=reason or f"LLM 路由选中 {eid}")

    # employeeId 为空 / 非法 → 引导，不硬回退默认员工（避免闲聊误跑任务）
    return RouteResult(
        reason=reason or "未匹配到员工",
        guideReply=guide_reply or build_capability_guide(employees),
    )


def pick_fallback_employee_id(
    employees: Sequence[DigitalEmployee],
    *,
    default_employee_id: str = "",
) -> str:
    default_id = (default_employee_id or "").strip()
    ids = {e.employeeId for e in employees}
    if default_id and default_id in ids:
        return default_id
    return employees[0].employeeId if employees else ""


def route_employee_id(
    *,
    message: str,
    employees: Sequence[DigitalEmployee],
    default_employee_id: str = "",
    api_key: str = "",
    provider: str = "",
    base_url: str = "",
    model: str = "",
    temperature: float = 0.0,
) -> RouteResult:
    """
    多员工路由。
    - 0 个：空 employeeId
    - 1 个：直接返回该员工
    - ≥2：LLM 路由；闲聊/无法匹配 → guideReply；技术失败 → 回退默认员工
    """
    items = [e for e in employees if e and (e.employeeId or "").strip()]
    if not items:
        return RouteResult(reason="无可用数字员工")
    if len(items) == 1:
        return RouteResult(
            employeeId=items[0].employeeId,
            reason="仅绑定一名数字员工，跳过路由",
        )

    fallback = pick_fallback_employee_id(
        items, default_employee_id=default_employee_id
    )
    key = resolve_router_api_key(api_key)
    if not key:
        logger.warning("路由 LLM 无 API Key，回退默认员工 %s", fallback)
        return RouteResult(employeeId=fallback, reason="无路由 API Key，使用默认员工")

    use_provider = (provider or "").strip()
    use_model = (model or "").strip() or default_router_model()
    # 有厂家时走预置地址；无厂家时兼容旧 routerBaseUrl
    url = "" if use_provider else ((base_url or "").strip() or default_router_base_url())
    allowed = {e.employeeId: e for e in items}

    messages = _build_prompt(items, message)
    logger.info(
        "机器人路由 prompt | provider=%s model=%s employees=%s\n%s",
        use_provider or "(legacy-url)",
        use_model,
        [e.employeeId for e in items],
        "\n---\n".join(
            f"[{m.get('role')}] {m.get('content')}" for m in messages
        ),
    )

    result = LlmClient().chat(
        messages,
        provider=use_provider or None,
        model=use_model,
        api_key=key,
        base_url=url or None,
        temperature=temperature,
        top_p=1.0,
        timeout_sec=60.0,
    )
    if not result.ok:
        logger.warning("LLM 路由失败，回退默认员工: %s", result.error)
        return RouteResult(
            employeeId=fallback,
            reason=f"路由失败: {result.error}",
        )

    content = result.content or ""
    logger.info("机器人路由 LLM 回复 | raw=%s", content[:1000])
    parsed = _parse_route_result(content, allowed, items)
    if parsed.should_guide:
        logger.info("机器人路由引导用户 | reason=%s", parsed.reason)
        return parsed
    if parsed.employeeId:
        return parsed
    logger.warning("路由结果无效，回退 %s | raw=%s", fallback, content[:200])
    return RouteResult(employeeId=fallback, reason="路由结果无效，使用默认员工")


def employees_catalog_for_prompt(employees: Sequence[DigitalEmployee]) -> List[Dict[str, Any]]:
    return [
        {
            "employeeId": e.employeeId,
            "name": e.name,
            "description": e.description or "",
        }
        for e in employees
    ]
