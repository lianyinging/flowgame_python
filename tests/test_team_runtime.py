"""Team Runtime 单元测试（mock LLM，不打真实 API）。"""
from __future__ import annotations

import json
import unittest
from typing import Any, Dict, List
from unittest.mock import patch

from src.flowgame.team.models import AgentTeamDef, AgentTeamHarness, AgentTeamMember, FlowAgentConfig
from src.flowgame.team.runtime import TeamRuntime


class FakeLlm:
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []
        self._n = 0

    def chat(self, messages, temperature=0.8, top_p=0.8, model=None):
        self.calls.append({"messages": messages, "temperature": temperature})
        system = messages[0]["content"] if messages else ""
        # 主控
        if "主控 Agent" in system or "Orchestrator" in system:
            self._n += 1
            if self._n == 1:
                return {
                    "content": json.dumps(
                        {
                            "thinking": "先调研",
                            "action": "CALL_AGENT",
                            "next_agent": "researcher",
                            "focus": "调研卖点",
                            "done_reason": "",
                        },
                        ensure_ascii=False,
                    )
                }
            if self._n == 2:
                return {
                    "content": json.dumps(
                        {
                            "thinking": "写大纲",
                            "action": "CALL_AGENT",
                            "next_agent": "planner",
                            "focus": "出大纲",
                            "done_reason": "",
                        },
                        ensure_ascii=False,
                    )
                }
            return {
                "content": json.dumps(
                    {
                        "thinking": "够了",
                        "action": "FINISH",
                        "next_agent": None,
                        "focus": "",
                        "done_reason": "demo done",
                    },
                    ensure_ascii=False,
                )
            }
        # 子 Agent
        return {"content": f"fake-output-for-{temperature}"}


class TeamRuntimeTests(unittest.TestCase):
    def test_supervisor_run_with_builtin_roles(self):
        team = AgentTeamDef(
            teamKey="team_test",
            name="test",
            strategy="supervisor",
            supervisorAgentKey="orchestrator_v1",
            members=[
                AgentTeamMember(agentKey="researcher", alias="researcher"),
                AgentTeamMember(agentKey="planner", alias="planner"),
                AgentTeamMember(agentKey="writer", alias="writer"),
            ],
            harness=AgentTeamHarness(
                maxSteps=6,
                maxSameAgentStreak=2,
                maxDecisionRetries=1,
                allowedAgents=["researcher", "planner", "writer"],
            ),
            outputPrimaryKey="outline",
            blackboardDefaults={"target_words": "500"},
        )
        agents = {
            "orchestrator_v1": FlowAgentConfig(
                agentKey="orchestrator_v1", methodKey="agent_content_orchestrator"
            ),
            "researcher": FlowAgentConfig(agentKey="researcher", methodKey="agent_content_researcher"),
            "planner": FlowAgentConfig(agentKey="planner", methodKey="agent_content_planner"),
            "writer": FlowAgentConfig(agentKey="writer", methodKey="agent_content_writer"),
        }
        runtime = TeamRuntime(team, agents)
        fake = FakeLlm()

        with patch.object(runtime, "_get_llm", return_value=fake):
            with patch.object(runtime, "_try_execute_flow", return_value=None):
                result = runtime.run({"topic": "麻辣小龙虾", "requirement": "新手友好"})

        self.assertEqual(result.status, "success")
        self.assertEqual(result.exit_reason, "master_finish")
        self.assertTrue(result.blackboard.get("research"))
        self.assertTrue(result.blackboard.get("outline"))
        actions = [t.get("action") for t in result.trace]
        self.assertIn("CALL_AGENT", actions)
        self.assertIn("FINISH", actions)

    def test_sequential_run(self):
        team = AgentTeamDef(
            teamKey="team_seq",
            name="seq",
            strategy="sequential",
            members=[
                AgentTeamMember(agentKey="researcher", alias="researcher"),
                AgentTeamMember(agentKey="planner", alias="planner"),
            ],
            harness=AgentTeamHarness(allowedAgents=["researcher", "planner"]),
            outputPrimaryKey="outline",
        )
        agents = {
            "researcher": FlowAgentConfig(agentKey="researcher", methodKey="x"),
            "planner": FlowAgentConfig(agentKey="planner", methodKey="y"),
        }
        runtime = TeamRuntime(team, agents)
        fake = FakeLlm()
        with patch.object(runtime, "_get_llm", return_value=fake):
            with patch.object(runtime, "_try_execute_flow", return_value=None):
                result = runtime.run({"topic": "测试"})
        self.assertEqual(result.status, "success")
        self.assertEqual(len(result.trace), 2)

    def test_extract_slim_end_output_writes_menu_content(self):
        """Agent 流程关闭过程详情时，顶层 menuContent 必须写回黑板。"""
        team = AgentTeamDef(
            teamKey="team_writer",
            name="w",
            strategy="sequential",
            members=[AgentTeamMember(agentKey="writer", alias="writer")],
            harness=AgentTeamHarness(allowedAgents=["writer"]),
            outputPrimaryKey="menuContent",
        )
        agents = {
            "writer": FlowAgentConfig(
                agentKey="writer",
                methodKey="内容编写-Agent",
                outputKey="menuContent",
            ),
        }
        runtime = TeamRuntime(team, agents)
        runtime.state = {
            "menuContent": {
                "小节A": "",
                "小节B": "",
            },
            "currentSearch": "小节A",
        }
        slim_result = {
            "menuContent": {
                "小节A": "第一节正文",
                "小节B": "",
            },
            "documentNull": True,
        }
        with patch.object(runtime, "_try_execute_flow", return_value=slim_result):
            runtime.invoke_worker("writer", focus="")

        self.assertEqual(runtime.state["menuContent"]["小节A"], "第一节正文")
        self.assertEqual(runtime.state["menuContent"]["小节B"], "")
        self.assertTrue(runtime.state.get("documentNull"))

    def test_extract_flow_outputs_prefers_end_node_then_slim(self):
        runtime = TeamRuntime(
            AgentTeamDef(teamKey="t", name="t", strategy="sequential"),
            {},
        )
        # 完整模式
        full = {
            "endNodeOutput": {"documents": [{"url": "https://a"}]},
            "apiOutput": {"body": {"documents": "should-not-use"}},
        }
        self.assertEqual(
            runtime._extract_flow_outputs(full)["documents"][0]["url"],
            "https://a",
        )
        # 精简模式（无 endNodeOutput / nodeExecutions）
        slim = {"menuContent": {"k": "v"}, "menuStatus": {"k": True}}
        out = runtime._extract_flow_outputs(slim)
        self.assertEqual(out["menuContent"]["k"], "v")
        self.assertTrue(out["menuStatus"]["k"])


if __name__ == "__main__":
    unittest.main()
