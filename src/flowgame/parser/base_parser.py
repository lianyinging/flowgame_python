"""Base node parser utilities."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.flowgame.chain.enums import DataType, RefType
from src.flowgame.chain.parameter import Parameter


def get_data(node_object: Dict[str, Any]) -> Dict[str, Any]:
    data = node_object.get("data")
    return data if isinstance(data, dict) else {}


def parse_parameters(data: Dict[str, Any], key: str = "parameters") -> List[Parameter]:
    return parse_parameters_array(data.get(key))


def parse_parameters_array(parameters_json: Any) -> List[Parameter]:
    if not isinstance(parameters_json, list):
        return []
    parameters: List[Parameter] = []
    for item in parameters_json:
        if not isinstance(item, dict):
            continue
        parameter = Parameter(
            id=item.get("id"),
            name=item.get("name"),
            description=item.get("description"),
            data_type=DataType.of_value(item.get("dataType")) or DataType.STRING,
            ref=item.get("ref"),
            ref_type=RefType.of_value(item.get("refType")),
            required=bool(item.get("required", False)),
            default_value=item.get("defaultValue"),
            value=item.get("value"),
        )
        children = item.get("children")
        if isinstance(children, list) and children:
            parameter.add_children(parse_parameters_array(children))
        parameters.append(parameter)
    return parameters


# 与 Tinyflow 内置 httpNode 默认 outputDefs 一致
HTTP_NODE_DEFAULT_OUTPUT_DEFS: List[Dict[str, Any]] = [
    {
        "name": "headers",
        "nameDisabled": True,
        "dataType": "Object",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
    {
        "name": "body",
        "nameDisabled": True,
        "dataType": "String",
        "deleteDisabled": True,
    },
    {
        "name": "statusCode",
        "nameDisabled": True,
        "dataType": "Number",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
]


def get_http_node_default_output_defs() -> List[Dict[str, Any]]:
    """API 开始节点未配置输出时的默认结构（与 httpNode 一致）。"""
    return HTTP_NODE_DEFAULT_OUTPUT_DEFS


# 与前端 talk-node-output-defs.ts 一致
TALK_NODE_DEFAULT_OUTPUT_DEFS: List[Dict[str, Any]] = [
    {
        "name": "message",
        "nameDisabled": True,
        "dataType": "String",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
    {
        "name": "sessionId",
        "nameDisabled": True,
        "dataType": "String",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
    {
        "name": "imgBase64List",
        "nameDisabled": True,
        "dataType": "Array<String>",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
]


def get_talk_node_default_output_defs() -> List[Dict[str, Any]]:
    return TALK_NODE_DEFAULT_OUTPUT_DEFS


# 与前端 llmapi-node-output-defs.ts 一致
LLMAPI_NODE_DEFAULT_OUTPUT_DEFS: List[Dict[str, Any]] = [
    {
        "name": "output",
        "nameDisabled": True,
        "dataType": "String",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
    {
        "name": "rawResponse",
        "nameDisabled": True,
        "dataType": "Object",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
    {
        "name": "errorMessage",
        "nameDisabled": True,
        "dataType": "String",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
]


def get_llmapi_node_default_output_defs() -> List[Dict[str, Any]]:
    return LLMAPI_NODE_DEFAULT_OUTPUT_DEFS


MEMORY_WRITE_DEFAULT_OUTPUT_DEFS: List[Dict[str, Any]] = [
    {
        "name": "success",
        "nameDisabled": True,
        "dataType": "Boolean",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
    {
        "name": "redisKey",
        "nameDisabled": True,
        "dataType": "String",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
    {
        "name": "listLength",
        "nameDisabled": True,
        "dataType": "Number",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
    {
        "name": "writtenCount",
        "nameDisabled": True,
        "dataType": "Number",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
    {
        "name": "writes",
        "nameDisabled": True,
        "dataType": "Array",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
    {
        "name": "errorMessage",
        "nameDisabled": True,
        "dataType": "String",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
]


MEMORY_READ_DEFAULT_OUTPUT_DEFS: List[Dict[str, Any]] = [
    {
        "name": "items",
        "nameDisabled": True,
        "dataType": "Array",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
    {
        "name": "redisKey",
        "nameDisabled": True,
        "dataType": "String",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
    {
        "name": "count",
        "nameDisabled": True,
        "dataType": "Number",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
    {
        "name": "errorMessage",
        "nameDisabled": True,
        "dataType": "String",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
]


def get_memory_write_default_output_defs() -> List[Dict[str, Any]]:
    return MEMORY_WRITE_DEFAULT_OUTPUT_DEFS


def get_memory_read_default_output_defs() -> List[Dict[str, Any]]:
    return MEMORY_READ_DEFAULT_OUTPUT_DEFS


STATE_MACHINE_DEFAULT_OUTPUT_DEFS: List[Dict[str, Any]] = [
    {"name": "success", "nameDisabled": True, "dataType": "Boolean", "dataTypeDisabled": True, "deleteDisabled": True},
    {"name": "exists", "nameDisabled": True, "dataType": "Boolean", "dataTypeDisabled": True, "deleteDisabled": True},
    {"name": "deleted", "nameDisabled": True, "dataType": "Boolean", "dataTypeDisabled": True, "deleteDisabled": True},
    {"name": "redisKey", "nameDisabled": True, "dataType": "String", "dataTypeDisabled": True, "deleteDisabled": True},
    {"name": "state", "nameDisabled": True, "dataType": "Object", "dataTypeDisabled": True, "deleteDisabled": True},
    {"name": "previousState", "nameDisabled": True, "dataType": "Object", "dataTypeDisabled": True, "deleteDisabled": True},
    {"name": "lastState", "nameDisabled": True, "dataType": "Object", "dataTypeDisabled": True, "deleteDisabled": True},
    {"name": "status", "nameDisabled": True, "dataType": "String", "dataTypeDisabled": True, "deleteDisabled": True},
    {"name": "progress", "nameDisabled": True, "dataType": "Number", "dataTypeDisabled": True, "deleteDisabled": True},
    {"name": "message", "nameDisabled": True, "dataType": "String", "dataTypeDisabled": True, "deleteDisabled": True},
    {"name": "payload", "nameDisabled": True, "dataType": "Object", "dataTypeDisabled": True, "deleteDisabled": True},
    {"name": "ttlSeconds", "nameDisabled": True, "dataType": "Number", "dataTypeDisabled": True, "deleteDisabled": True},
    {"name": "changedFields", "nameDisabled": True, "dataType": "Array", "dataTypeDisabled": True, "deleteDisabled": True},
    {"name": "errorMessage", "nameDisabled": True, "dataType": "String", "dataTypeDisabled": True, "deleteDisabled": True},
]


def get_state_machine_default_output_defs() -> List[Dict[str, Any]]:
    return STATE_MACHINE_DEFAULT_OUTPUT_DEFS


DATABASE_NODE_DEFAULT_OUTPUT_DEFS: List[Dict[str, Any]] = [
    {
        "name": "data",
        "nameDisabled": True,
        "dataType": "Array",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
    {
        "name": "rowCount",
        "nameDisabled": True,
        "dataType": "Number",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
    {
        "name": "success",
        "nameDisabled": True,
        "dataType": "Boolean",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
    {
        "name": "errorMessage",
        "nameDisabled": True,
        "dataType": "String",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
]


def get_database_node_default_output_defs() -> List[Dict[str, Any]]:
    return DATABASE_NODE_DEFAULT_OUTPUT_DEFS


OSS_NODE_DEFAULT_OUTPUT_DEFS: List[Dict[str, Any]] = [
    {
        "name": "success",
        "nameDisabled": True,
        "dataType": "Boolean",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
    {
        "name": "url",
        "nameDisabled": True,
        "dataType": "String",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
    {
        "name": "objectKey",
        "nameDisabled": True,
        "dataType": "String",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
    {
        "name": "fileType",
        "nameDisabled": True,
        "dataType": "String",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
    {
        "name": "contentType",
        "nameDisabled": True,
        "dataType": "String",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
    {
        "name": "etag",
        "nameDisabled": True,
        "dataType": "String",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
    {
        "name": "errorMessage",
        "nameDisabled": True,
        "dataType": "String",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
]


def get_oss_node_default_output_defs() -> List[Dict[str, Any]]:
    return OSS_NODE_DEFAULT_OUTPUT_DEFS


FORK_NODE_DEFAULT_OUTPUT_DEFS: List[Dict[str, Any]] = [
    {
        "name": "forked",
        "nameDisabled": True,
        "dataType": "Boolean",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
    {
        "name": "branches",
        "nameDisabled": True,
        "dataType": "Number",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
]

JOIN_ALL_NODE_DEFAULT_OUTPUT_DEFS: List[Dict[str, Any]] = [
    {
        "name": "joined",
        "nameDisabled": True,
        "dataType": "Boolean",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
    {
        "name": "mode",
        "nameDisabled": True,
        "dataType": "String",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
    {
        "name": "branchCount",
        "nameDisabled": True,
        "dataType": "Number",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
    {
        "name": "results",
        "nameDisabled": True,
        "dataType": "Object",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
    {
        "name": "errorMessage",
        "nameDisabled": True,
        "dataType": "String",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
]

JOIN_ANY_NODE_DEFAULT_OUTPUT_DEFS: List[Dict[str, Any]] = [
    {
        "name": "joined",
        "nameDisabled": True,
        "dataType": "Boolean",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
    {
        "name": "mode",
        "nameDisabled": True,
        "dataType": "String",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
    {
        "name": "branchCount",
        "nameDisabled": True,
        "dataType": "Number",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
    {
        "name": "winnerNodeId",
        "nameDisabled": True,
        "dataType": "String",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
    {
        "name": "results",
        "nameDisabled": True,
        "dataType": "Object",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
    {
        "name": "errorMessage",
        "nameDisabled": True,
        "dataType": "String",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
]


IF_NODE_DEFAULT_OUTPUT_DEFS: List[Dict[str, Any]] = [
    {
        "name": "matched",
        "nameDisabled": True,
        "dataType": "Boolean",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
    {
        "name": "branch",
        "nameDisabled": True,
        "dataType": "String",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
]


def get_fork_node_default_output_defs() -> List[Dict[str, Any]]:
    return FORK_NODE_DEFAULT_OUTPUT_DEFS


def get_if_node_default_output_defs() -> List[Dict[str, Any]]:
    return IF_NODE_DEFAULT_OUTPUT_DEFS


SWITCH_NODE_DEFAULT_OUTPUT_DEFS: List[Dict[str, Any]] = [
    {
        "name": "matched",
        "nameDisabled": True,
        "dataType": "Boolean",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
    {
        "name": "branch",
        "nameDisabled": True,
        "dataType": "String",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
    {
        "name": "switchValue",
        "nameDisabled": True,
        "dataType": "String",
        "dataTypeDisabled": True,
        "deleteDisabled": True,
    },
]


def get_switch_node_default_output_defs() -> List[Dict[str, Any]]:
    return SWITCH_NODE_DEFAULT_OUTPUT_DEFS


def get_join_all_node_default_output_defs() -> List[Dict[str, Any]]:
    return JOIN_ALL_NODE_DEFAULT_OUTPUT_DEFS


def get_join_any_node_default_output_defs() -> List[Dict[str, Any]]:
    return JOIN_ANY_NODE_DEFAULT_OUTPUT_DEFS


def get_end_node_output_defs_from_workflow(workflow_json: str) -> List[Dict[str, Any]]:
    """从工作流 JSON 读取结束节点的 outputDefs（优先 Api接口结束）。"""
    import json

    try:
        root = json.loads(workflow_json)
    except json.JSONDecodeError:
        return []

    api_defs: List[Dict[str, Any]] = []
    end_defs: List[Dict[str, Any]] = []
    for node_object in root.get("nodes") or []:
        if not isinstance(node_object, dict):
            continue
        ntype = node_object.get("type")
        data = get_data(node_object)
        output_defs = data.get("outputDefs")
        if not isinstance(output_defs, list) or not output_defs:
            continue
        if ntype == "node_end_api":
            api_defs = output_defs
        elif ntype == "endNode":
            end_defs = output_defs
    return api_defs or end_defs


def add_output_defs(node, data: Dict[str, Any]) -> None:
    """解析 outputDefs（含 defaultValue / value，与输入 parameters 字段一致）。"""
    for parameter in parse_parameters_array(data.get("outputDefs")):
        node.add_output_def(parameter)
