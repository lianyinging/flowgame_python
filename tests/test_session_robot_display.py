"""会话机器人展示状态 / 迁移逻辑。"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from src.flowgame.robot_channel.models import (
    SessionRobot,
    default_execute_timeout_sec,
    parse_execute_timeout_sec,
)


class DisplayStatusTests(unittest.TestCase):
    def test_migrate_old_running_status(self):
        robot = SessionRobot.from_dict(
            {
                "robotId": "r1",
                "name": "t",
                "botId": "b",
                "secret": "s",
                "status": "running",
            }
        )
        self.assertEqual(robot.desiredStatus, "running")
        # 旧进程内 running 迁移后 runtime 置 stopped，等 Worker 拉起
        self.assertEqual(robot.runtimeStatus, "stopped")

    def test_display_offline_when_worker_down(self):
        robot = SessionRobot(
            robotId="r1",
            desiredStatus="running",
            runtimeStatus="running",
            runtimeHeartbeatAt=datetime.now(timezone.utc).isoformat(),
        )
        status, msg = robot.display_status(worker_online=False)
        self.assertEqual(status, "offline")
        self.assertIn("未在线", msg)

    def test_display_running(self):
        robot = SessionRobot(
            robotId="r1",
            desiredStatus="running",
            runtimeStatus="running",
            runtimeHeartbeatAt=datetime.now(timezone.utc).isoformat(),
        )
        status, _ = robot.display_status(worker_online=True)
        self.assertEqual(status, "running")

    def test_display_stale_heartbeat(self):
        old = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
        robot = SessionRobot(
            robotId="r1",
            desiredStatus="running",
            runtimeStatus="running",
            runtimeHeartbeatAt=old,
        )
        status, msg = robot.display_status(worker_online=True, stale_sec=30)
        self.assertEqual(status, "offline")
        self.assertIn("心跳", msg)


class ExecuteTimeoutTests(unittest.TestCase):
    def test_parse_empty_as_none(self):
        self.assertIsNone(parse_execute_timeout_sec(None))
        self.assertIsNone(parse_execute_timeout_sec(""))
        self.assertIsNone(parse_execute_timeout_sec("  "))
        self.assertIsNone(parse_execute_timeout_sec(0))
        self.assertIsNone(parse_execute_timeout_sec(-1))

    def test_parse_positive(self):
        self.assertEqual(parse_execute_timeout_sec(300), 300)
        self.assertEqual(parse_execute_timeout_sec("180"), 180)
        self.assertEqual(parse_execute_timeout_sec(90.9), 90)

    def test_from_dict_roundtrip(self):
        robot = SessionRobot.from_dict(
            {
                "robotId": "r1",
                "name": "t",
                "botId": "b",
                "secret": "s",
                "executeTimeoutSec": 300,
            }
        )
        self.assertEqual(robot.executeTimeoutSec, 300)
        self.assertEqual(robot.to_dict(mask_secret=False)["executeTimeoutSec"], 300)

        empty = SessionRobot.from_dict(
            {"robotId": "r2", "name": "t", "botId": "b", "secret": "s"}
        )
        self.assertIsNone(empty.executeTimeoutSec)

    def test_default_env(self):
        self.assertGreaterEqual(default_execute_timeout_sec(), 1)


if __name__ == "__main__":
    unittest.main()
