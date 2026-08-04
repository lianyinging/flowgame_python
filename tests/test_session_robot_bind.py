"""会话机器人 bindType / 黑板注入单元测试。"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src.flowgame.robot_channel.bind_context import (
    apply_decision_result,
    enrich_robot_variables,
    ensure_team_topic,
    flatten_team_result,
    team_reply_fallback,
)
from src.flowgame.robot_channel.models import (
    SessionRobot,
    normalize_bind_type,
)


class BindTypeModelTests(unittest.TestCase):
    def test_normalize_bind_type(self) -> None:
        self.assertEqual(normalize_bind_type(None), "flow")
        self.assertEqual(normalize_bind_type("flow"), "flow")
        self.assertEqual(normalize_bind_type("team"), "team")
        self.assertEqual(normalize_bind_type("AgentTeam"), "team")

    def test_from_dict_defaults_flow(self) -> None:
        robot = SessionRobot.from_dict(
            {
                "robotId": "r1",
                "name": "n",
                "botId": "b",
                "secret": "s",
                "methodKey": "flow_a",
            }
        )
        self.assertEqual(robot.bindType, "flow")
        self.assertTrue(robot.is_bound())
        self.assertEqual(robot.bind_label(), "flow_a")

    def test_from_dict_team(self) -> None:
        robot = SessionRobot.from_dict(
            {
                "robotId": "r1",
                "name": "n",
                "botId": "b",
                "secret": "s",
                "bindType": "team",
                "teamKey": "intel_team",
            }
        )
        self.assertEqual(robot.bindType, "team")
        self.assertTrue(robot.is_bound())
        self.assertEqual(robot.bind_label(), "intel_team")
        self.assertIn("output", [m.source for m in robot.outputMapping])

    def test_is_bound_false_when_empty(self) -> None:
        robot = SessionRobot(bindType="team", teamKey="")
        self.assertFalse(robot.is_bound())
        robot2 = SessionRobot(bindType="flow", methodKey="")
        self.assertFalse(robot2.is_bound())


class BindContextTests(unittest.TestCase):
    @patch("src.flowgame.robot_space.ensure_robot_workspace")
    def test_enrich_robot_variables(self, mock_ws) -> None:
        mock_ws.return_value = "/tmp/robot_space/r1"
        robot = SessionRobot(
            robotId="r1",
            type="wecom_aibot",
            botId="bot-x",
            secret="sec-y",
            bindType="team",
            teamKey="t1",
            methodKey="",
        )
        variables = {"message": "你好", "chatId": "chat_1"}
        enrich_robot_variables(
            robot,
            variables,
            meta={"userid": "u1", "chattype": "group"},
        )
        self.assertEqual(variables["robotId"], "r1")
        self.assertEqual(variables["robotSpace"], "/tmp/robot_space/r1")
        self.assertEqual(variables["bindType"], "team")
        self.assertEqual(variables["teamKey"], "t1")
        self.assertEqual(variables["botId"], "bot-x")
        self.assertEqual(variables["wecomBotSecret"], "sec-y")
        self.assertEqual(variables["chatId"], "chat_1")
        self.assertEqual(variables["userId"], "u1")
        self.assertNotIn("secret", variables)

    def test_flatten_scrubs_secret(self) -> None:
        result = MagicMock()
        result.to_dict.return_value = {
            "teamKey": "t1",
            "strategy": "sequential",
            "status": "success",
            "exit_reason": "done",
            "output": "## 报告",
            "blackboard": {
                "topic": "x",
                "chatId": "c1",
                "wecomBotSecret": "should-not-leak",
                "article": "## 报告",
            },
        }
        payload = flatten_team_result(result)
        self.assertNotIn("wecomBotSecret", payload)
        self.assertEqual(payload["output"], "## 报告")

    def test_ensure_team_topic_from_message(self) -> None:
        variables = {"message": "今日情报"}
        topic = ensure_team_topic(variables)
        self.assertEqual(topic, "今日情报")
        self.assertEqual(variables["topic"], "今日情报")

    def test_ensure_team_topic_requires_text(self) -> None:
        with self.assertRaises(ValueError):
            ensure_team_topic({})

    def test_flatten_team_result(self) -> None:
        result = MagicMock()
        result.to_dict.return_value = {
            "teamKey": "t1",
            "strategy": "sequential",
            "status": "success",
            "exit_reason": "done",
            "output": "## 报告",
            "blackboard": {
                "topic": "x",
                "chatId": "c1",
                "article": "## 报告",
            },
        }
        payload = flatten_team_result(result)
        self.assertEqual(payload["output"], "## 报告")
        self.assertEqual(payload["assistantMessage"], "## 报告")
        self.assertEqual(payload["chatId"], "c1")
        self.assertEqual(payload["article"], "## 报告")

    def test_team_reply_fallback(self) -> None:
        self.assertEqual(
            team_reply_fallback({"output": "  hello  "}),
            "hello",
        )
        self.assertIsNone(team_reply_fallback({}))

    def test_apply_decision_skip_with_reply(self) -> None:
        variables = {"message": "hi", "robotId": "r1"}
        outcome = apply_decision_result(
            variables,
            {
                "apiOutput": {
                    "shouldRun": False,
                    "reply": "请补充主题",
                    "reason": "缺 topic",
                }
            },
        )
        self.assertFalse(outcome["shouldRun"])
        self.assertEqual(variables["reply"], "请补充主题")
        self.assertEqual(variables["decisionReason"], "缺 topic")
        self.assertNotIn("reply", outcome)  # 回发改由 outputMapping 处理

    def test_apply_decision_skip_merges_output_field(self) -> None:
        variables = {"message": "hi"}
        outcome = apply_decision_result(
            variables,
            {
                "output": "请问您想让我写什么主题的内容呢？",
                "shouldRun": False,
                "topic": "",
            },
        )
        self.assertFalse(outcome["shouldRun"])
        self.assertEqual(
            variables["output"],
            "请问您想让我写什么主题的内容呢？",
        )

    def test_decision_skip_reply_via_output_mapping(self) -> None:
        from src.flowgame.robot_channel.mapping import apply_output_mapping
        from src.flowgame.robot_channel.models import FieldMapping

        decision_raw = {
            "output": "请问您想让我写什么主题的内容呢？",
            "shouldRun": False,
        }
        actions = apply_output_mapping(
            decision_raw,
            [FieldMapping("output", "reply_markdown")],
        )
        self.assertEqual(
            actions["reply_markdown"],
            "请问您想让我写什么主题的内容呢？",
        )

    def test_apply_decision_run_merges_topic(self) -> None:
        variables = {"message": "原始", "robotId": "r1", "botId": "b"}
        outcome = apply_decision_result(
            variables,
            {"shouldRun": True, "topic": "补齐后的主题", "extra": 1},
        )
        self.assertTrue(outcome["shouldRun"])
        self.assertEqual(variables["topic"], "补齐后的主题")
        self.assertEqual(variables["extra"], 1)
        self.assertEqual(variables["botId"], "b")


if __name__ == "__main__":
    unittest.main()
