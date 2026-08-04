"""出站队列单元测试（Mock Redis）。"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src.flowgame.robot_channel.outbound import (
    enqueue_outbound,
    wait_outbound_result,
)
from src.flowgame.robot_channel.qiyeweixing.wecom.aibot import (
    _resolve_via,
    send_markdown,
)


class OutboundViaTests(unittest.TestCase):
    def test_resolve_via(self) -> None:
        self.assertEqual(_resolve_via(None), "auto")
        self.assertEqual(_resolve_via("worker"), "worker")
        self.assertEqual(_resolve_via("direct"), "direct")
        self.assertEqual(_resolve_via("queue"), "worker")

    @patch("src.flowgame.robot_channel.outbound._redis")
    def test_enqueue_outbound(self, mock_redis) -> None:
        client = MagicMock()
        mock_redis.return_value = client
        req = enqueue_outbound(
            "robot1",
            msgtype="markdown",
            content="hi",
            chatid="chat_x",
        )
        self.assertTrue(req.startswith("ob_"))
        client.rpush.assert_called_once()
        client.expire.assert_called()

    @patch("src.flowgame.robot_channel.qiyeweixing.wecom.aibot._try_send_via_worker")
    @patch("src.flowgame.robot_channel.qiyeweixing.wecom.aibot.run_async")
    @patch("src.flowgame.robot_channel.qiyeweixing.wecom.aibot.resolve_bot_creds")
    @patch.dict("os.environ", {"FLOWGAME_ROBOT_ID": "r1"}, clear=False)
    def test_send_markdown_auto_uses_worker(
        self, mock_creds, mock_run, mock_worker
    ) -> None:
        mock_worker.return_value = {"ok": True, "via": "worker", "chatid": "c1"}
        out = send_markdown("hello", chatid="c1", via="auto")
        self.assertTrue(out["ok"])
        self.assertEqual(out["via"], "worker")
        mock_run.assert_not_called()

    @patch("src.flowgame.robot_channel.qiyeweixing.wecom.aibot._try_send_via_worker")
    @patch("src.flowgame.robot_channel.qiyeweixing.wecom.aibot.run_async")
    @patch("src.flowgame.robot_channel.qiyeweixing.wecom.aibot.resolve_bot_creds")
    def test_send_markdown_direct(self, mock_creds, mock_run, mock_worker) -> None:
        mock_creds.return_value = ("b", "s")
        mock_run.return_value = {"ok": True}
        out = send_markdown("hello", chatid="c1", via="direct")
        self.assertEqual(out.get("via"), "direct")
        mock_worker.assert_not_called()
        mock_run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
