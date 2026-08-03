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
                marker = path1 / rs.ROBOT_WORKSPACE_MARKER
                self.assertTrue(marker.is_file())
                import json

                meta = json.loads(marker.read_text(encoding="utf-8"))
                self.assertEqual(meta["kind"], "session_robot_workspace")
                self.assertEqual(meta["robotId"], "abc123")
                self.assertEqual(meta["channel"], "qiyeweixing")

    def test_upgrade_legacy_plain_marker_to_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.object(rs, "get_robot_space_root", return_value=root):
                workspace = root / "qiyeweixing" / "legacy1"
                workspace.mkdir(parents=True)
                marker = workspace / rs.ROBOT_WORKSPACE_MARKER
                marker.write_text("robotId=legacy1\nchannel=qiyeweixing\n", encoding="utf-8")
                path = rs.ensure_robot_workspace("legacy1", "wecom_aibot")
                import json

                meta = json.loads((path / rs.ROBOT_WORKSPACE_MARKER).read_text(encoding="utf-8"))
                self.assertEqual(meta["kind"], "session_robot_workspace")
                self.assertEqual(meta["robotId"], "legacy1")

    def test_ensure_creates_channel_if_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.object(rs, "get_robot_space_root", return_value=root):
                path = rs.ensure_robot_workspace("r1", "wecom_aibot")
                self.assertTrue((root / "qiyeweixing").is_dir())
                self.assertTrue(path.is_dir())


if __name__ == "__main__":
    unittest.main()
