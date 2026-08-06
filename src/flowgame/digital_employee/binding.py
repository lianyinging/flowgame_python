"""将会话机器人解析为有效任务绑定（优先数字员工，兼容旧机器人直绑）。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

from src.flowgame.digital_employee.models import DigitalEmployee
from src.flowgame.robot_channel.models import (
    BindType,
    SessionRobot,
    default_execute_timeout_sec,
    default_team_execute_timeout_sec,
)


@dataclass
class EffectiveBinding:
    """运行时使用的决策 + 任务目标。"""

    employeeId: str = ""
    employeeName: str = ""
    decisionMethodKey: str = ""
    bindType: BindType = "flow"
    methodKey: str = ""
    teamKey: str = ""
    executeTimeoutSec: Optional[int] = None
    # employee | legacy | routed
    source: str = "employee"

    def is_task_bound(self) -> bool:
        if self.bindType == "team":
            return bool((self.teamKey or "").strip())
        return bool((self.methodKey or "").strip())

    def has_decision_flow(self) -> bool:
        return bool((self.decisionMethodKey or "").strip())

    def bind_label(self) -> str:
        if self.bindType == "team":
            return (self.teamKey or "").strip() or "（未绑 Team）"
        return (self.methodKey or "").strip() or "（未绑流程）"

    def resolve_execute_timeout_sec(self, robot_override: Optional[int] = None) -> float:
        if robot_override is not None and robot_override > 0:
            return float(robot_override)
        if self.executeTimeoutSec is not None and self.executeTimeoutSec > 0:
            return float(self.executeTimeoutSec)
        if self.bindType == "team":
            return float(default_team_execute_timeout_sec())
        return float(default_execute_timeout_sec())


class BindingResolveError(ValueError):
    """数字员工不存在或未绑定任务。"""


class RouteGuideNeeded(Exception):
    """多员工路由判定为闲聊/无法匹配，应直接回发引导文案。"""

    def __init__(self, reply: str, reason: str = ""):
        super().__init__(reason or reply)
        self.reply = (reply or "").strip()
        self.reason = (reason or "").strip()


def _binding_from_employee(
    emp: DigitalEmployee,
    *,
    source: str = "employee",
) -> EffectiveBinding:
    return EffectiveBinding(
        employeeId=emp.employeeId,
        employeeName=emp.name,
        decisionMethodKey=emp.decisionMethodKey,
        bindType=emp.bindType,
        methodKey=emp.methodKey,
        teamKey=emp.teamKey,
        executeTimeoutSec=emp.executeTimeoutSec,
        source=source,
    )


def load_robot_employees(robot: SessionRobot) -> List[DigitalEmployee]:
    """按配置顺序加载机器人绑定的数字员工（跳过缺失项）。"""
    from src.flowgame.digital_employee import store as employee_store

    result: List[DigitalEmployee] = []
    seen = set()
    for eid in robot.resolved_employee_ids():
        if eid in seen:
            continue
        seen.add(eid)
        emp = employee_store.get_employee(eid)
        if emp:
            result.append(emp)
    return result


def resolve_robot_binding(
    robot: SessionRobot,
    *,
    employee_id: Optional[str] = None,
) -> EffectiveBinding:
    """
    解析任务绑定：
    - 显式 employee_id（路由结果）→ 该员工
    - 否则若仅 1 名员工 → 该员工
    - 多员工且未指定 id → 取 defaultEmployeeId 或第一位（启动校验用；运行时应收消息后路由）
    - 无员工 → 回退机器人自身旧字段
    """
    from src.flowgame.digital_employee import store as employee_store

    explicit = (employee_id or "").strip()
    ids = robot.resolved_employee_ids()

    if explicit:
        emp = employee_store.get_employee(explicit)
        if not emp:
            raise BindingResolveError(f"数字员工不存在: {explicit}")
        if ids and explicit not in ids:
            raise BindingResolveError(f"数字员工未绑定到该机器人: {explicit}")
        return _binding_from_employee(emp, source="routed" if len(ids) > 1 else "employee")

    if ids:
        pick = (robot.defaultEmployeeId or "").strip()
        if pick not in ids:
            pick = ids[0]
        emp = employee_store.get_employee(pick)
        if not emp:
            # 默认位缺失时尝试列表中第一个存在的
            for eid in ids:
                emp = employee_store.get_employee(eid)
                if emp:
                    break
        if not emp:
            raise BindingResolveError(f"数字员工不存在: {pick or ids[0]}")
        return _binding_from_employee(emp, source="employee")

    return EffectiveBinding(
        employeeId="",
        employeeName="",
        decisionMethodKey=robot.decisionMethodKey,
        bindType=robot.bindType,
        methodKey=robot.methodKey,
        teamKey=robot.teamKey,
        executeTimeoutSec=robot.executeTimeoutSec,
        source="legacy",
    )


def robot_has_task_binding(robot: SessionRobot) -> bool:
    """是否已具备可启动的任务目标（任一绑定员工已绑任务，或旧直绑）。"""
    employees = load_robot_employees(robot)
    if employees:
        return any(e.is_bound() for e in employees)
    try:
        return resolve_robot_binding(robot).is_task_bound()
    except BindingResolveError:
        return False


def resolve_binding_for_message(
    robot: SessionRobot,
    message: str,
) -> EffectiveBinding:
    """
    收到消息后解析绑定：
    - 0 员工：legacy
    - 1 员工：直接用
    - ≥2：LLM 按描述路由；闲聊/无法匹配时抛 RouteGuideNeeded
    """
    employees = load_robot_employees(robot)
    if not employees:
        return resolve_robot_binding(robot)

    if len(employees) == 1:
        return _binding_from_employee(employees[0], source="employee")

    from src.flowgame.robot_channel.employee_router import route_employee_id

    routed = route_employee_id(
        message=message or "",
        employees=employees,
        default_employee_id=robot.defaultEmployeeId,
        api_key=robot.routerApiKey,
        provider=robot.routerProvider,
        base_url=robot.routerBaseUrl,
        model=robot.routerModel,
    )
    if routed.should_guide:
        raise RouteGuideNeeded(routed.guideReply, routed.reason)
    if not routed.employeeId:
        raise BindingResolveError(f"无法路由数字员工: {routed.reason}")
    binding = resolve_robot_binding(robot, employee_id=routed.employeeId)
    binding.source = "routed"
    return binding
