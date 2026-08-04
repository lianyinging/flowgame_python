"""数字员工绑定解析 / LLM 路由单元测试。"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src.flowgame.digital_employee.binding import (
    BindingResolveError,
    resolve_binding_for_message,
    resolve_robot_binding,
    robot_has_task_binding,
)
from src.flowgame.digital_employee.models import DigitalEmployee
from src.flowgame.robot_channel.employee_router import (
    pick_fallback_employee_id,
    route_employee_id,
)
from src.flowgame.robot_channel.models import SessionRobot, normalize_employee_ids


class NormalizeEmployeeIdsTests(unittest.TestCase):
    def test_from_list_and_legacy(self) -> None:
        self.assertEqual(normalize_employee_ids(["a", "b", "a"]), ["a", "b"])
        self.assertEqual(
            normalize_employee_ids(None, legacy_employee_id="x"),
            ["x"],
        )
        # 已有列表时不以 legacy 覆盖/插入
        self.assertEqual(
            normalize_employee_ids(["b"], legacy_employee_id="a"),
            ["b"],
        )


class DigitalEmployeeBindingTests(unittest.TestCase):
    def test_legacy_robot_binding(self) -> None:
        robot = SessionRobot(
            robotId="r1",
            bindType="team",
            teamKey="intel",
            decisionMethodKey="decide_flow",
        )
        binding = resolve_robot_binding(robot)
        self.assertEqual(binding.source, "legacy")
        self.assertTrue(binding.is_task_bound())
        self.assertTrue(binding.has_decision_flow())
        self.assertEqual(binding.teamKey, "intel")

    def test_employee_binding(self) -> None:
        emp = DigitalEmployee(
            employeeId="e1",
            name="情报员工",
            decisionMethodKey="d1",
            bindType="flow",
            methodKey="task_flow",
        )
        robot = SessionRobot(robotId="r1", employeeIds=["e1"], employeeId="e1")
        with patch(
            "src.flowgame.digital_employee.store.get_employee",
            return_value=emp,
        ):
            binding = resolve_robot_binding(robot)
            self.assertEqual(binding.source, "employee")
            self.assertEqual(binding.employeeName, "情报员工")
            self.assertEqual(binding.methodKey, "task_flow")
            self.assertTrue(robot_has_task_binding(robot))
            self.assertTrue(robot.is_bound())

    def test_missing_employee(self) -> None:
        robot = SessionRobot(robotId="r1", employeeIds=["missing"], employeeId="missing")
        with patch(
            "src.flowgame.digital_employee.store.get_employee",
            return_value=None,
        ):
            with self.assertRaises(BindingResolveError):
                resolve_robot_binding(robot)
            self.assertFalse(robot_has_task_binding(robot))
            self.assertFalse(robot.is_bound())

    def test_employee_model_bound(self) -> None:
        emp = DigitalEmployee(bindType="flow", methodKey="")
        self.assertFalse(emp.is_bound())
        emp.methodKey = "f1"
        self.assertTrue(emp.is_bound())
        emp2 = DigitalEmployee(bindType="team", teamKey="t1")
        self.assertTrue(emp2.is_bound())


class EmployeeRouterTests(unittest.TestCase):
    def test_single_skips_llm(self) -> None:
        emp = DigitalEmployee(employeeId="e1", name="A", methodKey="f1")
        eid, reason = route_employee_id(message="hi", employees=[emp])
        self.assertEqual(eid, "e1")
        self.assertIn("跳过", reason)

    def test_fallback_default(self) -> None:
        emps = [
            DigitalEmployee(employeeId="e1", name="A"),
            DigitalEmployee(employeeId="e2", name="B"),
        ]
        self.assertEqual(pick_fallback_employee_id(emps, default_employee_id="e2"), "e2")
        self.assertEqual(pick_fallback_employee_id(emps, default_employee_id=""), "e1")

    def test_route_parses_json(self) -> None:
        emps = [
            DigitalEmployee(
                employeeId="e1",
                name="情报",
                description="做情报汇总",
                methodKey="f1",
            ),
            DigitalEmployee(
                employeeId="e2",
                name="客服",
                description="回答产品问题",
                methodKey="f2",
            ),
        ]
        mock_resp = MagicMock()
        mock_resp.choices = [
            MagicMock(message=MagicMock(content='{"employeeId":"e2","reason":"客服"}'))
        ]
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_resp
        with patch(
            "src.flowgame.robot_channel.employee_router.OpenAI",
            return_value=mock_client,
        ), patch(
            "src.flowgame.robot_channel.employee_router.resolve_router_api_key",
            return_value="sk-test",
        ):
            eid, reason = route_employee_id(
                message="产品怎么退款",
                employees=emps,
                default_employee_id="e1",
                api_key="sk-test",
            )
        self.assertEqual(eid, "e2")
        self.assertIn("LLM", reason)

    def test_resolve_binding_for_message_routes(self) -> None:
        e1 = DigitalEmployee(employeeId="e1", name="A", description="情报", methodKey="f1")
        e2 = DigitalEmployee(employeeId="e2", name="B", description="客服", methodKey="f2")
        robot = SessionRobot(
            robotId="r1",
            employeeIds=["e1", "e2"],
            defaultEmployeeId="e1",
            routerApiKey="sk-x",
        )

        def get_emp(eid: str):
            return {"e1": e1, "e2": e2}.get(eid)

        with patch(
            "src.flowgame.digital_employee.store.get_employee",
            side_effect=get_emp,
        ), patch(
            "src.flowgame.robot_channel.employee_router.route_employee_id",
            return_value=("e2", "ok"),
        ):
            binding = resolve_binding_for_message(robot, "你好")
            self.assertEqual(binding.employeeId, "e2")
            self.assertEqual(binding.source, "routed")
            self.assertEqual(binding.methodKey, "f2")


if __name__ == "__main__":
    unittest.main()
