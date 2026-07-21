"""Unit tests for node_end_api includeExecutionDetails switch."""
from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock

from src.flowgame.chain.enums import ChainStatus
from src.flowgame.chain.nodes import EndApiNode, EndNode
from src.flowgame.service import FlowGameExecuteService


class EndApiNodeOutputModeTest(unittest.TestCase):
    def _workflow(self, *, include_details: bool, output_defs=None, end_type="node_end_api") -> str:
        data = {
            "includeExecutionDetails": "true" if include_details else "false",
        }
        if output_defs is not None:
            data["outputDefs"] = output_defs
        return json.dumps(
            {
                "nodes": [
                    {"id": "s1", "type": "node_start_api", "data": {}},
                    {"id": "e1", "type": end_type, "data": data},
                ],
                "edges": [],
            }
        )

    def test_builtin_end_always_includes_details(self):
        chain = MagicMock()
        end = EndNode()
        chain.nodes = [end]
        chain.execute_result = {"fallback": 1}
        chain.status = ChainStatus.FINISHED_NORMAL
        chain.message = None
        chain.execution_records = [
            {
                "nodeId": "n1",
                "nodeName": "图像生成",
                "nodeType": "imageGenNode",
                "status": "success",
                "durationMs": 10,
                "output": {"url": "https://x"},
                "error": None,
            }
        ]
        svc = FlowGameExecuteService()
        resp = svc._collect_chain_response(
            chain, self._workflow(include_details=False, end_type="endNode")
        )
        self.assertIn("nodeExecutions", resp)

    def test_end_api_custom_only(self):
        chain = MagicMock()
        end = EndApiNode()
        end.include_execution_details = False
        chain.nodes = [end]
        chain.execute_result = {"fallback": "should-not-appear"}
        chain.status = ChainStatus.FINISHED_NORMAL
        chain.message = None
        chain.execution_records = [
            {
                "nodeId": "n1",
                "nodeName": "图像生成",
                "nodeType": "imageGenNode",
                "status": "success",
                "durationMs": 10,
                "output": {"url": "https://x"},
                "error": None,
            }
        ]
        chain.get = MagicMock(
            side_effect=lambda ref: "https://custom" if ref == "img.url" else None
        )
        workflow = self._workflow(
            include_details=False,
            output_defs=[
                {
                    "id": "o1",
                    "name": "url",
                    "dataType": "String",
                    "refType": "ref",
                    "ref": "img.url",
                }
            ],
        )
        svc = FlowGameExecuteService()
        resp = svc._collect_chain_response(chain, workflow)
        self.assertEqual(resp, {"url": "https://custom"})
        self.assertNotIn("nodeExecutions", resp)

    def test_stream_force_full_details(self):
        chain = MagicMock()
        end = EndApiNode()
        end.include_execution_details = False
        chain.nodes = [end]
        chain.execute_result = {"url": "https://custom"}
        chain.status = ChainStatus.FINISHED_NORMAL
        chain.message = None
        chain.execution_records = [
            {
                "nodeId": "n1",
                "nodeName": "图像生成",
                "nodeType": "imageGenNode",
                "status": "success",
                "durationMs": 10,
                "output": {"url": "https://x"},
                "error": None,
            }
        ]
        chain.get = MagicMock(
            side_effect=lambda ref: "https://custom" if ref == "img.url" else None
        )
        workflow = self._workflow(
            include_details=False,
            output_defs=[
                {
                    "id": "o1",
                    "name": "url",
                    "dataType": "String",
                    "refType": "ref",
                    "ref": "img.url",
                }
            ],
        )
        svc = FlowGameExecuteService()
        resp = svc._collect_chain_response(chain, workflow, force_full_details=True)
        self.assertIn("nodeExecutions", resp)


if __name__ == "__main__":
    unittest.main()
