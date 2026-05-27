"""Api接口开始 节点工作流约束（与前端 workflow-start-api-rules 一致）。"""
from __future__ import annotations

import json
START_API_NODE_TYPE = "node_start_api"
START_NODE_TYPE = "startNode"


def validate_start_api_workflow(workflow_json: str) -> None:
    try:
        root = json.loads(workflow_json)
    except json.JSONDecodeError as exc:
        raise ValueError("工作流定义必须是合法的 JSON") from exc

    nodes = root.get("nodes") or []
    edges = root.get("edges") or []
    start_api = [n for n in nodes if isinstance(n, dict) and n.get("type") == START_API_NODE_TYPE]

    if len(start_api) > 1:
        raise ValueError("流程中只能有一个「Api接口开始」节点")

    if not start_api:
        return

    api_id = start_api[0].get("id")
    if api_id and any(isinstance(e, dict) and e.get("target") == api_id for e in edges):
        raise ValueError("「Api接口开始」只能作为流程起点，不能连接上游节点")

    if any(isinstance(n, dict) and n.get("type") == START_NODE_TYPE for n in nodes):
        raise ValueError("请勿同时使用「开始节点」与「Api接口开始」")
