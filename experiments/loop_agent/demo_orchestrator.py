"""
主 Agent 统筹子 Agent Demo（动态路由，非固定流水线）

与 demo_minimal.py 的区别：
  demo_minimal   → 顺序写死：A→B→C→Loop
  本文件         → 主 Agent 每步决定「下一步调用哪个子 Agent / 或结束」

三层工程（本文件刻意拆开，方便对照学习）：

  1) Prompt Engineering（提示工程）
     - 主 Agent / 子 Agent 的角色、目标、输出契约、Few-shot 决策示例
     - 强制 JSON 决策格式，降低乱跳概率

  2) Context Engineering（上下文工程）
     - 不为每个 Agent 塞满整个 state
     - 按 Agent 声明的 input_keys 装箱；长文本摘要/截断
     - 给主 Agent 的是「状态摘要 + 最近轨迹」，不是全文 dump

  3) Harness Engineering（运行时护栏 / 编排外壳）
     - 白名单校验 next_agent
     - max_steps / 同 Agent 连续调用上限 / 非法决策重试
     - 强制 finish 兜底、全程 trace 落盘

运行：
  cd experiments/loop_agent
  python demo_orchestrator.py --topic "麻辣小龙虾" --requirement "适合厨房新手"
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(_ROOT / ".env")
except ImportError:
    pass

from openai import OpenAI


# ===========================================================================
# 公共：LLM 客户端
# ===========================================================================


@dataclass
class LlmClient:
    client: OpenAI
    model: str

    def chat(self, system: str, user: str, temperature: float = 0.3) -> str:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
        )
        return (resp.choices[0].message.content or "").strip()


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """从模型输出中尽量抠出第一个 JSON 对象。"""
    text = (text or "").strip()
    if not text:
        return None
    # 直接是 JSON
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    # 代码块或夹杂文字
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…（已截断，原长 {len(text)} 字）"


# ===========================================================================
# 1) Prompt Engineering —— 提示词与契约
# ===========================================================================
#
# 原则：
# - 每个子 Agent 只做一件事，输出契约写死（写到哪、什么格式）
# - 主 Agent 只做「调度决策」，禁止直接写长文
# - 决策必须是可机器解析的 JSON，并给 Few-shot 样例
#


MASTER_SYSTEM_PROMPT = """
你是内容创作项目的「主控 Agent（Orchestrator）」。
你不直接写长文，只做调度：根据当前状态，决定下一步调用哪个子 Agent，或宣布完成。

## 可用子 Agent（只能从中选择）
{agent_catalog}

## 决策原则
1. 缺调研 → researcher；缺大纲 → planner；缺正文 → writer
2. 有正文但质量不明/偏低 → reviewer；审核要求修改 → refiner
3. 审核已通过且正文就绪 → publisher；成稿已有且达标 → FINISH
4. 不要无意义地重复同一 Agent；若刚跑过 reviewer 且未通过，优先 refiner
5. 目标是产出高质量文章，不是把每个 Agent 都跑一遍

## 输出契约（必须是单个 JSON，不要 Markdown 代码围栏，不要其它文字）
{{
  "thinking": "简短说明为何选这一步（1~3句）",
  "action": "CALL_AGENT 或 FINISH",
  "next_agent": "子Agent名；FINISH 时填 null",
  "focus": "给子Agent的本轮焦点指令（一句话）；FINISH 时可空",
  "done_reason": "仅 FINISH 时填写完成理由"
}}

## Few-shot
状态：只有 topic，无 research
→ {{"thinking":"还没有调研","action":"CALL_AGENT","next_agent":"researcher","focus":"围绕主题做读者与卖点调研","done_reason":""}}

状态：已有 content，review 为「需要修改」
→ {{"thinking":"审核未通过，应改稿","action":"CALL_AGENT","next_agent":"refiner","focus":"按最新审核意见逐条修改","done_reason":""}}

状态：review 为「审核通过」，尚无 article
→ {{"thinking":"质量已达标，组装成稿","action":"CALL_AGENT","next_agent":"publisher","focus":"输出正式 Markdown 成稿","done_reason":""}}
""".strip()


# 子 Agent：name / 职责 / 写哪个 state 键 / 读哪些键 / 提示模板
SUB_AGENT_SPECS: Dict[str, Dict[str, Any]] = {
    "researcher": {
        "role": "资深选题调研员",
        "mission": "只做调研简报，不写正文",
        "output_key": "research",
        "input_keys": ["topic", "requirement", "target_words"],
        "temperature": 0.4,
        "system": "你是资深选题调研员。只输出调研简报，不要写文章正文。",
        "user_template": (
            "主题：{topic}\n要求：{requirement}\n目标字数：{target_words}\n"
            "主控焦点：{focus}\n\n"
            "请输出：读者画像、5个卖点/痛点、3个切入角度、避免的陈词滥调。"
        ),
    },
    "planner": {
        "role": "内容策划主编",
        "mission": "只出大纲与标题方向",
        "output_key": "outline",
        "input_keys": ["topic", "requirement", "research"],
        "temperature": 0.4,
        "system": "你是内容策划主编。只输出大纲，不要写正文。",
        "user_template": (
            "主题：{topic}\n要求：{requirement}\n调研：\n{research}\n"
            "主控焦点：{focus}\n\n"
            "请输出：选定角度、3个候选标题、结构小节、语气。"
        ),
    },
    "writer": {
        "role": "专栏作者",
        "mission": "按大纲写完整初稿",
        "output_key": "content",
        "input_keys": ["topic", "requirement", "target_words", "research", "outline"],
        "temperature": 0.7,
        "system": "你是专栏作者。输出完整初稿正文（含小标题），不要列候选标题清单。",
        "user_template": (
            "主题：{topic}\n要求：{requirement}\n字数约 {target_words}\n"
            "调研：\n{research}\n\n大纲：\n{outline}\n"
            "主控焦点：{focus}\n\n请写完整初稿。"
        ),
    },
    "reviewer": {
        "role": "严苛审核主编",
        "mission": "打分并给出通过/修改结论",
        "output_key": "review",
        "input_keys": ["topic", "requirement", "outline", "content"],
        "temperature": 0.2,
        "system": (
            "你是严苛审核主编。第一行必须是「审核通过」或「需要修改」，"
            "然后给出各维度1-10分与最多5条可执行修改建议。"
        ),
        "user_template": (
            "主题：{topic}\n要求：{requirement}\n大纲：\n{outline}\n\n"
            "正文：\n{content}\n"
            "主控焦点：{focus}\n\n"
            "维度：开头吸引力、结构、信息密度、文风、契合度。通过标准：全部≥8。"
        ),
    },
    "refiner": {
        "role": "改稿作者",
        "mission": "按审核意见改稿",
        "output_key": "content",
        "input_keys": ["topic", "requirement", "target_words", "content", "review"],
        "temperature": 0.55,
        "system": "你是改稿作者。若已审核通过则原样输出正文；否则按意见完整改稿。",
        "user_template": (
            "主题：{topic}\n要求：{requirement}\n字数约 {target_words}\n"
            "当前正文：\n{content}\n\n审核：\n{review}\n"
            "主控焦点：{focus}\n\n输出修改后的完整正文。"
        ),
    },
    "publisher": {
        "role": "发行编辑",
        "mission": "组装最终 Markdown 成稿",
        "output_key": "article",
        "input_keys": ["topic", "outline", "content", "review"],
        "temperature": 0.4,
        "system": (
            "你是发行编辑。只输出最终 Markdown："
            "# 标题 / 导语引用块 / 正文 / --- / **写在最后**。"
        ),
        "user_template": (
            "主题：{topic}\n大纲：\n{outline}\n\n正文：\n{content}\n\n"
            "最近审核：\n{review}\n"
            "主控焦点：{focus}\n\n输出正式成稿。"
        ),
    },
}


def build_agent_catalog() -> str:
    """Prompt Engineering：给主 Agent 的工具/子Agent目录。"""
    lines = []
    for name, spec in SUB_AGENT_SPECS.items():
        lines.append(
            f"- {name}: {spec['mission']} "
            f"(读 {','.join(spec['input_keys'])} → 写 {spec['output_key']})"
        )
    return "\n".join(lines)


# ===========================================================================
# 2) Context Engineering —— 给谁看什么、看多少
# ===========================================================================
#
# 原则：
# - 子 Agent：只注入声明过的 input_keys + 主控 focus（最小充分上下文）
# - 主 Agent：看「状态卡片摘要」+「最近调度轨迹」，避免全文刷爆上下文
# - 长字段截断；可按需要做摘要（本 demo 用截断模拟摘要策略）
#


@dataclass
class ContextEngine:
    """上下文装箱器。"""

    # 主 Agent 看到的各字段最大长度
    master_field_limit: int = 500
    # 子 Agent 看到的各字段最大长度
    worker_field_limit: int = 3500
    # 主 Agent 看到的最近轨迹条数
    recent_trace_limit: int = 8

    def pack_for_worker(
        self,
        agent_name: str,
        state: Dict[str, Any],
        focus: str,
    ) -> Dict[str, str]:
        """按子 Agent 的 input_keys 装箱，缺失键给空串。"""
        spec = SUB_AGENT_SPECS[agent_name]
        packed: Dict[str, str] = {"focus": (focus or "按你的职责完成任务").strip()}
        for key in spec["input_keys"]:
            packed[key] = _clip(str(state.get(key) or ""), self.worker_field_limit)
        return packed

    def status_card(self, state: Dict[str, Any]) -> str:
        """主 Agent 用的状态卡片：有/无 + 短摘要，而不是全文。"""
        keys = [
            "topic",
            "requirement",
            "target_words",
            "research",
            "outline",
            "content",
            "review",
            "article",
        ]
        lines = []
        for key in keys:
            val = state.get(key)
            if val is None or str(val).strip() == "":
                lines.append(f"- {key}: （空）")
            else:
                preview = _clip(str(val), self.master_field_limit)
                lines.append(f"- {key}: 已有（{len(str(val))}字）\n{preview}")
        return "\n".join(lines)

    def pack_for_master(
        self,
        state: Dict[str, Any],
        trace: List[Dict[str, Any]],
        step_idx: int,
        max_steps: int,
    ) -> str:
        """主 Agent 用户消息：预算提醒 + 状态卡片 + 最近轨迹。"""
        recent = trace[-self.recent_trace_limit :]
        trace_lines = []
        for item in recent:
            trace_lines.append(
                f"- step={item.get('step')} action={item.get('action')} "
                f"agent={item.get('next_agent')} "
                f"ok={item.get('ok')} note={item.get('note')}"
            )
        return (
            f"当前步数：{step_idx}/{max_steps}\n\n"
            f"## 状态卡片\n{self.status_card(state)}\n\n"
            f"## 最近调度轨迹\n"
            + ("\n".join(trace_lines) if trace_lines else "- （尚无）")
            + "\n\n请输出下一步决策 JSON。"
        )


# ===========================================================================
# 3) Harness Engineering —— 运行时护栏与编排外壳
# ===========================================================================
#
# 原则：
# - 模型可以「建议」下一步，Harness 负责「是否允许执行」
# - 非法路由、死循环、超步数 → 拦截 / 重试 / 强制结束
# - 全程可观测：trace 写入文件，便于复盘 Prompt/Context 是否有效
#


@dataclass
class OrchestratorDecision:
    thinking: str = ""
    action: str = ""  # CALL_AGENT | FINISH
    next_agent: Optional[str] = None
    focus: str = ""
    done_reason: str = ""
    raw: str = ""
    valid: bool = False
    error: str = ""


@dataclass
class HarnessConfig:
    max_steps: int = 12
    max_decision_retries: int = 2
    max_same_agent_streak: int = 2  # 同一子 Agent 连续调用上限
    forbid_agents: Set[str] = field(default_factory=set)


class AgentHarness:
    """
    编排外壳：主 Agent 决策 → 校验 → 调子 Agent → 写 state → 循环。
    """

    def __init__(
        self,
        llm: LlmClient,
        context: ContextEngine,
        config: Optional[HarnessConfig] = None,
    ) -> None:
        self.llm = llm
        self.context = context
        self.config = config or HarnessConfig()
        self.state: Dict[str, Any] = {}
        self.trace: List[Dict[str, Any]] = []
        self._same_agent_streak = 0
        self._last_agent: Optional[str] = None

    # ----- Prompt Engineering 使用点：主 Agent 决策 -----

    def ask_master(self, step_idx: int) -> OrchestratorDecision:
        system = MASTER_SYSTEM_PROMPT.format(agent_catalog=build_agent_catalog())
        user = self.context.pack_for_master(
            self.state, self.trace, step_idx, self.config.max_steps
        )
        raw = self.llm.chat(system=system, user=user, temperature=0.2)
        return self._parse_and_validate_decision(raw)

    def _parse_and_validate_decision(self, raw: str) -> OrchestratorDecision:
        """Harness：解析 + 白名单校验。"""
        decision = OrchestratorDecision(raw=raw)
        obj = _extract_json_object(raw)
        if not obj:
            decision.error = "无法解析 JSON 决策"
            return decision

        decision.thinking = str(obj.get("thinking") or "").strip()
        decision.action = str(obj.get("action") or "").strip().upper()
        next_agent = obj.get("next_agent")
        decision.next_agent = (
            None if next_agent in (None, "null", "") else str(next_agent).strip()
        )
        decision.focus = str(obj.get("focus") or "").strip()
        decision.done_reason = str(obj.get("done_reason") or "").strip()

        if decision.action not in {"CALL_AGENT", "FINISH"}:
            decision.error = f"非法 action: {decision.action}"
            return decision

        if decision.action == "FINISH":
            decision.valid = True
            return decision

        # CALL_AGENT
        if not decision.next_agent:
            decision.error = "CALL_AGENT 但 next_agent 为空"
            return decision
        if decision.next_agent not in SUB_AGENT_SPECS:
            decision.error = f"next_agent 不在白名单: {decision.next_agent}"
            return decision
        if decision.next_agent in self.config.forbid_agents:
            decision.error = f"next_agent 被禁用: {decision.next_agent}"
            return decision

        # 连续同 Agent 限制
        if (
            decision.next_agent == self._last_agent
            and self._same_agent_streak >= self.config.max_same_agent_streak
        ):
            decision.error = (
                f"禁止连续第 {self._same_agent_streak + 1} 次调用 "
                f"{decision.next_agent}，请换其它 Agent 或 FINISH"
            )
            return decision

        decision.valid = True
        return decision

    def decide_with_retries(self, step_idx: int) -> OrchestratorDecision:
        """非法决策时把错误反馈给主 Agent 再问一次（Harness 重试）。"""
        decision = self.ask_master(step_idx)
        retries = 0
        while not decision.valid and retries < self.config.max_decision_retries:
            retries += 1
            print(f"  ⚠ 决策非法：{decision.error} → 重试 {retries}")
            repair_user = (
                self.context.pack_for_master(
                    self.state, self.trace, step_idx, self.config.max_steps
                )
                + f"\n\n上一次输出非法：{decision.error}\n"
                + f"上一次原文：\n{_clip(decision.raw, 800)}\n"
                + "请重新输出合法 JSON 决策。"
            )
            system = MASTER_SYSTEM_PROMPT.format(agent_catalog=build_agent_catalog())
            raw = self.llm.chat(system=system, user=repair_user, temperature=0.1)
            decision = self._parse_and_validate_decision(raw)
        return decision

    # ----- 子 Agent 执行 -----

    def run_sub_agent(self, agent_name: str, focus: str) -> str:
        """Context Engineering：按需装箱后调用子 Agent。"""
        spec = SUB_AGENT_SPECS[agent_name]
        packed = self.context.pack_for_worker(agent_name, self.state, focus)
        user = spec["user_template"].format_map(
            {**{k: "" for k in spec["input_keys"]}, **packed, "focus": packed["focus"]}
        )
        print(f"\n▶ 子Agent [{agent_name}]  {spec['role']}")
        print(f"  focus: {focus or '（无）'}")
        print(f"  context keys: {spec['input_keys']}")

        text = self.llm.chat(
            system=spec["system"],
            user=user,
            temperature=float(spec["temperature"]),
        )
        preview = _clip(text, 700)
        print(preview)

        self.state[spec["output_key"]] = text
        return text

    # ----- 主循环 -----

    def run(self, initial_state: Dict[str, Any]) -> Dict[str, Any]:
        self.state = dict(initial_state)
        self.trace = []
        self._same_agent_streak = 0
        self._last_agent = None

        print("\n" + "=" * 60)
        print("主 Agent 统筹模式启动（Prompt + Context + Harness）")
        print("=" * 60)

        for step_idx in range(1, self.config.max_steps + 1):
            print(f"\n{'─' * 60}\n◆ 主控决策 round {step_idx}/{self.config.max_steps}")
            decision = self.decide_with_retries(step_idx)

            if not decision.valid:
                # Harness 兜底：无法得到合法决策 → 强制结束
                note = f"决策最终非法，强制 FINISH：{decision.error}"
                print(f"  ✖ {note}")
                self.trace.append(
                    {
                        "step": step_idx,
                        "action": "FORCE_FINISH",
                        "next_agent": None,
                        "ok": False,
                        "note": note,
                        "thinking": decision.thinking,
                        "raw": decision.raw,
                    }
                )
                self.state["exit_reason"] = "invalid_decision"
                break

            print(f"  thinking: {decision.thinking}")
            print(f"  action  : {decision.action} → {decision.next_agent}")

            if decision.action == "FINISH":
                self.trace.append(
                    {
                        "step": step_idx,
                        "action": "FINISH",
                        "next_agent": None,
                        "ok": True,
                        "note": decision.done_reason or "主控宣布完成",
                        "thinking": decision.thinking,
                    }
                )
                self.state["exit_reason"] = "master_finish"
                self.state["done_reason"] = decision.done_reason
                print(f"  ✔ FINISH: {decision.done_reason}")
                break

            # 执行子 Agent
            try:
                self.run_sub_agent(decision.next_agent or "", decision.focus)
                ok, note = True, "ok"
            except Exception as exc:  # noqa: BLE001 — demo 需要吞住并记 trace
                ok, note = False, f"子Agent异常: {exc}"
                print(f"  ✖ {note}")

            # 更新连续调用计数（Harness）
            if decision.next_agent == self._last_agent:
                self._same_agent_streak += 1
            else:
                self._same_agent_streak = 1
                self._last_agent = decision.next_agent

            self.trace.append(
                {
                    "step": step_idx,
                    "action": "CALL_AGENT",
                    "next_agent": decision.next_agent,
                    "focus": decision.focus,
                    "ok": ok,
                    "note": note,
                    "thinking": decision.thinking,
                }
            )
        else:
            # for 正常耗尽 max_steps
            self.state["exit_reason"] = "max_steps"
            print(f"\n⚠ 达到 max_steps={self.config.max_steps}，Harness 强制结束")

        return self.state


# ===========================================================================
# 入口
# ===========================================================================


def _save(state: Dict[str, Any], trace: List[Dict[str, Any]], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    topic_slug = re.sub(r"\s+", "_", str(state.get("topic") or "article"))[:40]
    base = out_dir / f"{stamp}_{topic_slug}_orchestrator"

    article = str(state.get("article") or state.get("content") or "")
    md_path = Path(str(base) + ".md")
    md_path.write_text(article + "\n", encoding="utf-8")

    # 调度轨迹（Harness 可观测性）
    trace_md = [
        "# 主 Agent 调度轨迹\n",
        f"- topic: {state.get('topic')}\n",
        f"- exit_reason: {state.get('exit_reason')}\n",
        f"- done_reason: {state.get('done_reason')}\n\n",
    ]
    for item in trace:
        trace_md.append(
            f"## step {item.get('step')}: {item.get('action')} "
            f"{item.get('next_agent') or ''}\n"
            f"- thinking: {item.get('thinking')}\n"
            f"- focus: {item.get('focus')}\n"
            f"- ok: {item.get('ok')} note: {item.get('note')}\n\n"
        )
    Path(str(base) + "_trace.md").write_text("".join(trace_md), encoding="utf-8")

    payload = {"state": state, "trace": trace}
    Path(str(base) + ".json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return md_path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="主 Agent 统筹子 Agent Demo")
    p.add_argument("--topic", default="", help="文章主题")
    p.add_argument("--requirement", default="", help="额外要求")
    p.add_argument("--words", type=int, default=800, help="目标字数")
    p.add_argument("--max-steps", type=int, default=12, help="Harness 最大调度步数")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip().rstrip("/")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip()
    if not api_key or api_key == "your-deepseek-api-key":
        print("请先在仓库根目录 .env 配置 DEEPSEEK_API_KEY。")
        sys.exit(1)

    topic = (args.topic or "").strip() or input("请输入文章主题：").strip()
    if not topic:
        print("主题不能为空")
        sys.exit(1)
    requirement = (args.requirement or "").strip()
    if not requirement:
        requirement = (
            input("额外要求（可回车跳过）：").strip()
            or "结构清晰、有干货、适合普通读者"
        )

    print(f"base_url={base_url} model={model}")
    print(f"topic={topic!r} words≈{args.words} max_steps={args.max_steps}")

    llm = LlmClient(client=OpenAI(api_key=api_key, base_url=base_url), model=model)
    harness = AgentHarness(
        llm=llm,
        context=ContextEngine(),
        config=HarnessConfig(max_steps=max(3, args.max_steps)),
    )
    state = harness.run(
        {
            "topic": topic,
            "requirement": requirement,
            "target_words": str(args.words),
        }
    )
    out = _save(state, harness.trace, Path(__file__).resolve().parent / "output")

    print("\n" + "=" * 60)
    print("成稿摘要")
    print("=" * 60)
    print(_clip(str(state.get("article") or state.get("content") or ""), 1000))
    print("-" * 60)
    print(f"exit_reason = {state.get('exit_reason')}")
    print(f"saved = {out}")
    print(f"trace = {out.with_name(out.stem + '_trace.md')}")


if __name__ == "__main__":
    main()
