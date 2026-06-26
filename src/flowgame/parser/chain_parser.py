"""Parse Tinyflow frontend JSON into executable Chain."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from src.flowgame.chain.chain import Chain
from src.flowgame.chain.condition import JavascriptStringCondition
from src.flowgame.chain.edge import ChainEdge
from src.flowgame.chain.nodes import (
    CodeNode,
    DatabaseNode,
    EndNode,
    ForkNode,
    HttpNode,
    JoinAllNode,
    JoinAnyNode,
    KnowledgeNode,
    KnowledgeNodePlus,
    LlmApiNode,
    LlmNode,
    LoopNode,
    MemoryReadNode,
    MemoryWriteNode,
    OssNode,
    SearchEngineNode,
    StartApiNode,
    StartTalkNode,
    StartNode,
    TemplateNode,
)
from src.flowgame.parser.base_parser import (
    add_output_defs,
    get_data,
    get_http_node_default_output_defs,
    get_talk_node_default_output_defs,
    get_llmapi_node_default_output_defs,
    get_database_node_default_output_defs,
    get_fork_node_default_output_defs,
    get_oss_node_default_output_defs,
    get_join_all_node_default_output_defs,
    get_join_any_node_default_output_defs,
    get_memory_read_default_output_defs,
    get_memory_write_default_output_defs,
    parse_parameters,
    parse_parameters_array,
)
from src.flowgame.tinyflow_config import TinyflowRuntime


def _parse_positive_int(value: Any, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


class ChainParser:
    def __init__(self) -> None:
        self._parsers = {
            "startNode": self._parse_start,
            "node_start_api": self._parse_start_api,
            "node_start_talk": self._parse_start_talk,
            "codeNode": self._parse_code,
            "httpNode": self._parse_http,
            "knowledgeNode": self._parse_knowledge,
            "knowledgeNodePlus": self._parse_knowledge_plus,
            "loopNode": self._parse_loop,
            "searchEngineNode": self._parse_search_engine,
            "templateNode": self._parse_template,
            "htmlTemplateNode": self._parse_template,
            "endNode": self._parse_end,
            "llmNode": self._parse_llm,
            "llmapiNode": self._parse_llmapi,
            "memoryWriteNode": self._parse_memory_write,
            "memoryReadNode": self._parse_memory_read,
            "databaseNode": self._parse_database,
            "ossNode": self._parse_oss,
            "forkNode": self._parse_fork,
            "joinAllNode": self._parse_join_all,
            "joinAnyNode": self._parse_join_any,
        }

    def parse(self, runtime: TinyflowRuntime) -> Chain:
        root = json.loads(runtime.data)
        nodes = root.get("nodes") or []
        edges = root.get("edges") or []
        return self._parse_graph(runtime, nodes, edges, None)

    def _parse_graph(
        self,
        runtime: TinyflowRuntime,
        nodes: List[Any],
        edges: List[Any],
        parent_node: Optional[Dict[str, Any]],
    ) -> Chain:
        chain = Chain()
        parent_id = parent_node.get("id") if parent_node else None

        for node_object in nodes:
            if not isinstance(node_object, dict):
                continue
            node_parent = node_object.get("parentId")
            if parent_id is None:
                if node_parent:
                    continue
            elif node_parent != parent_id:
                continue

            parsed = self._parse_node(runtime, node_object)
            if parsed is None:
                continue

            parsed.id = node_object.get("id")
            parsed.name = node_object.get("label")
            parsed.description = node_object.get("description")
            parsed.node_type = node_object.get("type")

            data = get_data(node_object)
            if data:
                condition_string = data.get("condition")
                if condition_string and str(condition_string).strip():
                    parsed.condition = JavascriptStringCondition(str(condition_string))
                if "async" in data:
                    parsed.async_exec = bool(data.get("async"))
                if data.get("title"):
                    parsed.name = data.get("title")
                if data.get("description"):
                    parsed.description = data.get("description")

            chain.add_node(parsed)

        for edge_object in edges:
            if not isinstance(edge_object, dict):
                continue
            edge_data = edge_object.get("data") or {}
            parent_node_id = edge_data.get("parentNodeId")

            if parent_id is None:
                if parent_node_id:
                    continue
            else:
                if parent_node_id != parent_id:
                    continue
                if parent_id == edge_object.get("source"):
                    continue

            edge = self._parse_edge(edge_object)
            if edge:
                chain.add_edge(edge)

        chain.init_join_barriers()
        return chain

    def _parse_node(self, runtime: TinyflowRuntime, node_object: Dict[str, Any]):
        node_type = node_object.get("type")
        if not node_type:
            return None
        parser = self._parsers.get(node_type)
        return parser(runtime, node_object) if parser else None

    def _parse_edge(self, edge_object: Dict[str, Any]) -> Optional[ChainEdge]:
        edge = ChainEdge(
            id=edge_object.get("id"),
            source=edge_object.get("source"),
            target=edge_object.get("target"),
        )
        data = edge_object.get("data")
        if isinstance(data, dict):
            condition_string = data.get("condition")
            if condition_string and str(condition_string).strip():
                edge.condition = JavascriptStringCondition(str(condition_string))
        return edge

    def _parse_start(self, runtime: TinyflowRuntime, node_object: Dict[str, Any]):
        node = StartNode()
        data = get_data(node_object)
        node.set_parameters(parse_parameters(data))
        return node

    def _parse_start_api(self, runtime: TinyflowRuntime, node_object: Dict[str, Any]):
        node = StartApiNode()
        data = get_data(node_object)
        node.method_key = (data.get("methodKey") or "").strip() or None
        node.external_url = data.get("externalUrl")
        request_type = data.get("requestType") or "post"
        node.request_type = str(request_type).lower()
        node.api_description = data.get("apiDescription")
        node.set_parameters(parse_parameters(data))
        add_output_defs(node, data)
        if not node.output_defs:
            node.output_defs = parse_parameters_array(get_http_node_default_output_defs())
        return node

    def _parse_start_talk(self, runtime: TinyflowRuntime, node_object: Dict[str, Any]):
        from src.flowgame.workflow_talk_rules import resolve_talk_template

        node = StartTalkNode()
        data = get_data(node_object)
        node.method_key = (data.get("methodKey") or "").strip() or None
        node.talk_template = resolve_talk_template(data.get("talkTemplate"))
        node.talk_title = data.get("talkTitle")
        node.welcome_message = data.get("welcomeMessage")
        node.set_parameters(parse_parameters(data))
        add_output_defs(node, data)
        if not node.output_defs:
            node.output_defs = parse_parameters_array(get_talk_node_default_output_defs())
        return node

    def _parse_end(self, runtime: TinyflowRuntime, node_object: Dict[str, Any]):
        node = EndNode()
        data = get_data(node_object)
        node.end_message = data.get("message")
        add_output_defs(node, data)
        return node

    def _parse_llm(self, runtime: TinyflowRuntime, node_object: Dict[str, Any]):
        node = LlmNode()
        data = get_data(node_object)
        node.user_prompt = data.get("userPrompt")
        node.system_prompt = data.get("systemPrompt")
        node.out_type = data.get("outType") or "text"
        node.top_k = int(data.get("topK", 10))
        node.top_p = float(data.get("topP", 0.8))
        node.temperature = float(data.get("temperature", 0.8))
        node.llm = runtime.get_llm_provider().get_llm(data.get("llmId"))
        node.set_parameters(parse_parameters(data))
        add_output_defs(node, data)
        return node

    def _parse_llmapi(self, runtime: TinyflowRuntime, node_object: Dict[str, Any]):
        node = LlmApiNode()
        data = get_data(node_object)
        node.model_api_url = data.get("modelApiUrl")
        node.api_key = data.get("apiKey")
        node.model_name = (data.get("modelName") or "gpt-4o-mini").strip() or "gpt-4o-mini"
        node.auth_type = (data.get("authType") or "bearer").strip().lower()
        node.auth_header_name = (data.get("authHeaderName") or "Authorization").strip()
        node.request_timeout_ms = _parse_positive_int(data.get("requestTimeoutMs"), 60000)
        node.system_prompt = data.get("systemPrompt")
        node.user_prompt = data.get("userPrompt")
        node.temperature = float(data.get("temperature", 0.7))
        node.max_tokens = _parse_positive_int(data.get("maxTokens"), 2048)
        node.response_format = (data.get("responseFormat") or "text").strip().lower()
        node.extra_headers_json = data.get("extraHeaders")
        node.extra_body_json = data.get("extraBody")
        node.set_parameters(parse_parameters(data))
        add_output_defs(node, data)
        if not node.output_defs:
            node.output_defs = parse_parameters_array(get_llmapi_node_default_output_defs())
        return node

    def _parse_code(self, runtime: TinyflowRuntime, node_object: Dict[str, Any]):
        data = get_data(node_object)
        engine = (data.get("engine") or "qlexpress").lower()
        if engine in ("js", "javascript"):
            node = CodeNode("js")
        elif engine == "groovy":
            node = CodeNode("js")
        else:
            node = CodeNode("js")
        node.code = data.get("code")
        node.set_parameters(parse_parameters(data))
        add_output_defs(node, data)
        return node

    def _parse_http(self, runtime: TinyflowRuntime, node_object: Dict[str, Any]):
        node = HttpNode()
        data = get_data(node_object)
        node.url = data.get("url")
        node.method = data.get("method")
        node.body_json = data.get("bodyJson")
        node.raw_body = data.get("rawBody")
        node.body_type = data.get("bodyType")
        node.headers = parse_parameters(data, "headers")
        node.form_data = parse_parameters(data, "formData")
        node.form_urlencoded = parse_parameters(data, "formUrlencoded")
        node.set_parameters(parse_parameters(data))
        add_output_defs(node, data)
        return node

    def _parse_template(self, runtime: TinyflowRuntime, node_object: Dict[str, Any]):
        node = TemplateNode()
        data = get_data(node_object)
        node.template = data.get("template")
        node.set_parameters(parse_parameters(data))
        add_output_defs(node, data)
        return node

    def _parse_memory_write(self, runtime: TinyflowRuntime, node_object: Dict[str, Any]):
        node = MemoryWriteNode()
        data = get_data(node_object)
        node.max_list_size = _parse_positive_int(data.get("maxListSize"), 0)
        node.expire_seconds = _parse_positive_int(data.get("expireSeconds"), 0)
        node.set_parameters(parse_parameters(data))
        add_output_defs(node, data)
        if not node.output_defs:
            node.output_defs = parse_parameters_array(get_memory_write_default_output_defs())
        return node

    def _parse_memory_read(self, runtime: TinyflowRuntime, node_object: Dict[str, Any]):
        node = MemoryReadNode()
        data = get_data(node_object)
        node.read_limit = _parse_positive_int(data.get("readLimit"), 50)
        node.set_parameters(parse_parameters(data))
        add_output_defs(node, data)
        if not node.output_defs:
            node.output_defs = parse_parameters_array(get_memory_read_default_output_defs())
        return node

    def _parse_database(self, runtime: TinyflowRuntime, node_object: Dict[str, Any]):
        node = DatabaseNode()
        data = get_data(node_object)
        node.db_type = (data.get("dbType") or "mysql").strip().lower()
        node.sql_template = data.get("sqlTemplate")
        node.set_parameters(parse_parameters(data))
        add_output_defs(node, data)
        if not node.output_defs:
            node.output_defs = parse_parameters_array(get_database_node_default_output_defs())
        return node

    def _parse_oss(self, runtime: TinyflowRuntime, node_object: Dict[str, Any]):
        node = OssNode()
        data = get_data(node_object)
        node.file_type = (data.get("fileType") or "txt").strip().lower()
        node.object_key_template = data.get("objectKeyTemplate") or "uploads/{{methodKey}}/{{timestamp}}"
        node.bucket = (data.get("bucket") or "").strip() or None
        node.set_parameters(parse_parameters(data))
        add_output_defs(node, data)
        if not node.output_defs:
            node.output_defs = parse_parameters_array(get_oss_node_default_output_defs())
        return node

    def _parse_fork(self, runtime: TinyflowRuntime, node_object: Dict[str, Any]):
        node = ForkNode()
        data = get_data(node_object)
        add_output_defs(node, data)
        if not node.output_defs:
            node.output_defs = parse_parameters_array(get_fork_node_default_output_defs())
        return node

    def _parse_join_all(self, runtime: TinyflowRuntime, node_object: Dict[str, Any]):
        node = JoinAllNode()
        data = get_data(node_object)
        add_output_defs(node, data)
        if not node.output_defs:
            node.output_defs = parse_parameters_array(get_join_all_node_default_output_defs())
        return node

    def _parse_join_any(self, runtime: TinyflowRuntime, node_object: Dict[str, Any]):
        node = JoinAnyNode()
        data = get_data(node_object)
        add_output_defs(node, data)
        if not node.output_defs:
            node.output_defs = parse_parameters_array(get_join_any_node_default_output_defs())
        return node

    def _parse_knowledge(self, runtime: TinyflowRuntime, node_object: Dict[str, Any]):
        node = KnowledgeNode()
        data = get_data(node_object)
        node.knowledge_id = data.get("knowledgeId")
        node.limit = data.get("limit")
        node.keyword = data.get("keyword")
        node.knowledge = runtime.get_knowledge_provider().get_knowledge(data.get("knowledgeId"))
        node.set_parameters(parse_parameters(data))
        add_output_defs(node, data)
        return node

    def _parse_knowledge_plus(self, runtime: TinyflowRuntime, node_object: Dict[str, Any]):
        node = KnowledgeNodePlus()
        data = get_data(node_object)
        collection = (
            data.get("collectionName")
            or data.get("knowledgeId")
            or data.get("knowledgeCollection")
        )
        node.collection_name = str(collection).strip() if collection else None
        node.knowledge_id = node.collection_name
        node.limit = data.get("limit")
        node.keyword = data.get("keyword")
        node.set_parameters(parse_parameters(data))
        add_output_defs(node, data)
        return node

    def _parse_search_engine(self, runtime: TinyflowRuntime, node_object: Dict[str, Any]):
        node = SearchEngineNode()
        data = get_data(node_object)
        node.keyword = data.get("keyword")
        node.limit = data.get("limit")
        node.engine = data.get("engine")
        if runtime.search_engine_provider:
            node.search_engine = runtime.search_engine_provider.get_search_engine(
                data.get("engine")
            )
        node.set_parameters(parse_parameters(data))
        add_output_defs(node, data)
        return node

    def _parse_loop(self, runtime: TinyflowRuntime, node_object: Dict[str, Any]):
        node = LoopNode()
        data = get_data(node_object)
        loop_params = parse_parameters(data, "loopVar")
        if loop_params:
            node.loop_var = loop_params[0]
        root = json.loads(runtime.data)
        node.loop_chain = self._parse_graph(
            runtime, root.get("nodes") or [], root.get("edges") or [], node_object
        )
        node.set_parameters(parse_parameters(data))
        add_output_defs(node, data)
        return node
