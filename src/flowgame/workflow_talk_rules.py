"""对话开始 节点工作流约束（与前端 workflow-talk-rules 一致）。"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

START_TALK_NODE_TYPE = "node_start_talk"
END_NODE_TYPE = "endNode"
ASSISTANT_MESSAGE_OUTPUT_NAME = "assistantMessage"
TALK_TEMPLATES = frozenset({"default", "minimal"})


def find_start_talk_data(workflow_json: str) -> Optional[Dict[str, Any]]:
    try:
        root = json.loads(workflow_json)
    except json.JSONDecodeError:
        return None
    for node_object in root.get("nodes") or []:
        if isinstance(node_object, dict) and node_object.get("type") == START_TALK_NODE_TYPE:
            from src.flowgame.parser.base_parser import get_data

            return get_data(node_object)
    return None


def _get_end_node_output_defs(root: Dict[str, Any]) -> List[Dict[str, Any]]:
    for node_object in root.get("nodes") or []:
        if not isinstance(node_object, dict):
            continue
        if node_object.get("type") != END_NODE_TYPE:
            continue
        from src.flowgame.parser.base_parser import get_data

        data = get_data(node_object)
        output_defs = data.get("outputDefs")
        if isinstance(output_defs, list):
            return output_defs
    return []


def _has_assistant_message_output(root: Dict[str, Any]) -> bool:
    for item in _get_end_node_output_defs(root):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if name != ASSISTANT_MESSAGE_OUTPUT_NAME:
            continue
        data_type = str(item.get("dataType") or "Object").strip()
        if data_type in ("Object", ""):
            return True
    return False


def validate_talk_start_workflow(workflow_json: str) -> None:
    try:
        root = json.loads(workflow_json)
    except json.JSONDecodeError as exc:
        raise ValueError("工作流定义必须是合法的 JSON") from exc

    nodes = root.get("nodes") or []
    edges = root.get("edges") or []
    talk_nodes = [
        n for n in nodes if isinstance(n, dict) and n.get("type") == START_TALK_NODE_TYPE
    ]

    if len(talk_nodes) > 1:
        raise ValueError("流程中只能有一个「对话开始」节点")

    if not talk_nodes:
        return

    talk_id = talk_nodes[0].get("id")
    if talk_id and any(isinstance(e, dict) and e.get("target") == talk_id for e in edges):
        raise ValueError("「对话开始」只能作为流程起点，不能连接上游节点")

    if not _has_assistant_message_output(root):
        raise ValueError(
            "配置了「对话开始」时，结束节点必须包含 Object 类型的 assistantMessage 输出"
        )


def validate_talk_start_workflow_for_page(workflow_json: str) -> None:
    """GET /talk 要求流程已配置对话开始节点。"""
    validate_talk_start_workflow(workflow_json)
    if not find_start_talk_data(workflow_json):
        raise ValueError("流程未配置「对话开始」节点")


def resolve_talk_template(raw: Any) -> str:
    template = str(raw or "default").strip().lower() or "default"
    if template not in TALK_TEMPLATES:
        return "default"
    return template


def validate_assistant_message(value: Any) -> Dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("assistantMessage 必须为对象")
    role = value.get("role")
    content = value.get("content")
    if str(role or "").strip() != "assistant":
        raise ValueError('assistantMessage.role 必须为 "assistant"')
    if not isinstance(content, str) or not content.strip():
        raise ValueError("assistantMessage.content 必须为非空字符串")
    return {"role": "assistant", "content": content.strip()}
