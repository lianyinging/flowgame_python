"""会话机器人：按数字员工描述做 LLM 自动路由（无记忆/TTL）。"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from openai import OpenAI

from src.flowgame.digital_employee.models import DigitalEmployee

logger = logging.getLogger("flowgame.session_robot.router")

DEFAULT_ROUTER_MODEL = "deepseek-v4-flash"
DEFAULT_ROUTER_BASE_URL = "https://api.deepseek.com"


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


def _build_prompt(employees: Sequence[DigitalEmployee], message: str) -> List[Dict[str, str]]:
    lines = []
    for emp in employees:
        desc = (emp.description or "").strip() or "（无描述）"
        lines.append(
            f"- employeeId={emp.employeeId}\n"
            f"  name={emp.name}\n"
            f"  description={desc}"
        )
    catalog = "\n".join(lines)
    system = (
        "你是会话机器人的路由助手。根据用户消息与数字员工职责描述，"
        "从给定列表中选择最合适的一位数字员工。"
        "只能从列表中选择，禁止编造 employeeId。"
        "只输出 JSON：{\"employeeId\":\"...\",\"reason\":\"简短原因\"}，不要其它文字。"
    )
    user = (
        f"可选数字员工：\n{catalog}\n\n"
        f"用户消息：\n{(message or '').strip() or '（空）'}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _parse_employee_id(content: str, allowed: Dict[str, DigitalEmployee]) -> Optional[str]:
    text = (content or "").strip()
    if not text:
        return None
    # 去掉 markdown 代码块
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.I)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            eid = str(data.get("employeeId") or data.get("id") or "").strip()
            if eid in allowed:
                return eid
            # 允许按 name 命中
            name = str(data.get("name") or "").strip()
            if name:
                for emp in allowed.values():
                    if emp.name == name:
                        return emp.employeeId
    except json.JSONDecodeError:
        pass
    # 兜底：正文里出现唯一合法 employeeId
    hits = [eid for eid in allowed if eid in text]
    if len(hits) == 1:
        return hits[0]
    return None


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
    base_url: str = "",
    model: str = "",
    temperature: float = 0.0,
) -> Tuple[str, str]:
    """
    返回 (employeeId, reason)。
    - 0 个：空串
    - 1 个：直接返回
    - ≥2：LLM 路由；失败则默认员工 / 列表第一位
    """
    items = [e for e in employees if e and (e.employeeId or "").strip()]
    if not items:
        return "", "无可用数字员工"
    if len(items) == 1:
        return items[0].employeeId, "仅绑定一名数字员工，跳过路由"

    fallback = pick_fallback_employee_id(
        items, default_employee_id=default_employee_id
    )
    key = resolve_router_api_key(api_key)
    if not key:
        logger.warning("路由 LLM 无 API Key，回退默认员工 %s", fallback)
        return fallback, "无路由 API Key，使用默认员工"

    url = (base_url or "").strip() or default_router_base_url()
    use_model = (model or "").strip() or default_router_model()
    allowed = {e.employeeId: e for e in items}

    try:
        client = OpenAI(api_key=key, base_url=url.rstrip("/"))
        resp = client.chat.completions.create(
            model=use_model,
            messages=_build_prompt(items, message),
            temperature=temperature,
            top_p=1.0,
        )
        content = (resp.choices[0].message.content or "") if resp.choices else ""
        picked = _parse_employee_id(content, allowed)
        if picked:
            return picked, f"LLM 路由选中 {picked}"
        logger.warning("路由结果无法解析，回退 %s | raw=%s", fallback, content[:200])
        return fallback, "路由结果无效，使用默认员工"
    except Exception as exc:  # noqa: BLE001
        logger.exception("LLM 路由失败，回退默认员工")
        return fallback, f"路由失败: {exc}"


def employees_catalog_for_prompt(employees: Sequence[DigitalEmployee]) -> List[Dict[str, Any]]:
    return [
        {
            "employeeId": e.employeeId,
            "name": e.name,
            "description": e.description or "",
        }
        for e in employees
    ]
