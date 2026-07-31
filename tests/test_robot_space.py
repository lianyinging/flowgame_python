"""robot_space 工作目录。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.flowgame import robot_space as rs


class RobotSpaceTests(unittest.TestCase):
    def test_channel_mapping(self):
        self.assertEqual(rs.resolve_channel_name("wecom_aibot"), "qiyeweixing")

    def test_ensure_creates_robot_id_under_channel(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.object(rs, "get_robot_space_root", return_value=root):
                channel = root / "qiyeweixing"
                channel.mkdir()
                path1 = rs.ensure_robot_workspace("abc123", "wecom_aibot")
                self.assertTrue(path1.is_dir())
                self.assertEqual(path1, (channel / "abc123").resolve())
                # 渠道已存在，再次 ensure 不报错且路径稳定
                path2 = rs.ensure_robot_workspace("abc123", "wecom_aibot")
                self.assertEqual(path1, path2)
                self.assertTrue(channel.is_dir())

    def test_ensure_creates_channel_if_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.object(rs, "get_robot_space_root", return_value=root):
                path = rs.ensure_robot_workspace("r1", "wecom_aibot")
                self.assertTrue((root / "qiyeweixing").is_dir())
                self.assertTrue(path.is_dir())


if __name__ == "__main__":
    unittest.main()
