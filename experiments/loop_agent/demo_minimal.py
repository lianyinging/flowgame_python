"""
多 Agent 协同写文章 Demo（不依赖 google.adk）

本文件分两层：
  1) 最小运行时：LlmStep / Sequential / LoopUntil + 共享 state
  2) 业务流水线：调研 → 策划 → 写作 → 润色 → 质量循环 → 成稿

对应 Google ADK 概念（仅语义对齐，不引依赖）：
  LlmAgent       → LlmStep
  SequentialAgent → Sequential
  LoopAgent      → LoopUntil（条件退出 + max_iterations）
  escalate       → StepResult.escalate / should_escalate 回调
  session.state  → Runtime.state

每步默认开启「思考过程」：
  模型先输出【思考过程】，再输出【最终输出】；
  控制台分开展示；state 只把最终输出交给下游，思考写入 {key}_thinking。

流程：
  Sequential
    researcher  → 调研要点 / 读者画像     → state['research']
    planner     → 大纲与论点             → state['outline']
    writer      → 初稿正文               → state['draft']
    stylist     → 文风润色               → state['content']
    LoopUntil(max=N)
      reviewer  → 多维打分 + 修改意见     → state['review']
      refiner   → 按意见改稿             → state['content']
      checker   → 达标则 escalate 退出
    publisher   → 组装标题/导语/正文     → state['article']

运行：
  cd experiments/loop_agent
  python demo_minimal.py
  python demo_minimal.py --topic "麻辣小龙虾" --requirement "适合厨房新手" --words 800
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
from typing import Any, Callable, Dict, List, Optional

# 仓库根目录（experiments/loop_agent 的上两级），用于加载 .env 与后续扩展
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(_ROOT / ".env")
except ImportError:
    pass

from openai import OpenAI

# 强制模型分两段输出：思考过程（给人看）+ 最终输出（给下游 Agent）
_OUTPUT_FORMAT_HINT = """
请严格按下面两个区块输出（标题行必须原样出现）：

【思考过程】
（在此写你的推理：如何理解输入、可选方案、取舍理由、风险与自检；3~8 条要点即可）

【最终输出】
（在此只放本步交付给下游的结果正文；不要再写思考过程）
""".strip()


def parse_thinking_and_answer(raw: str) -> tuple[str, str]:
    """
    从模型原文拆出「思考过程」与「最终输出」。

    兼容标题略有差异；若完全没有分隔符，则整段视为最终输出。
    """
    text = (raw or "").strip()
    if not text:
        return "", ""

    # 优先匹配标准标题
    m = re.search(
        r"【\s*思考过程\s*】\s*(.*?)\s*【\s*最终输出\s*】\s*(.*)\s*\Z",
        text,
        flags=re.DOTALL,
    )
    if m:
        return m.group(1).strip(), m.group(2).strip()

    # 兼容英文或简化标题
    m = re.search(
        r"(?:【\s*思考\s*】|<thinking>)\s*(.*?)\s*(?:【\s*输出\s*】|【\s*最终输出\s*】|</thinking>)\s*(.*)\s*\Z",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if m:
        return m.group(1).strip(), m.group(2).strip()

    # 只有「最终输出」标题
    m = re.search(r"【\s*最终输出\s*】\s*(.*)\s*\Z", text, flags=re.DOTALL)
    if m:
        thinking = text[: m.start()].strip()
        thinking = re.sub(r"^【\s*思考过程\s*】\s*", "", thinking).strip()
        return thinking, m.group(1).strip()

    return "", text


# ===========================================================================
# 一、最小运行时（验证 LoopAgent 可行性的核心，与具体「写文章」业务无关）
# ===========================================================================


@dataclass
class StepResult:
    """单步执行结果。"""

    output: Any = None
    thinking: str = ""  # 本步思考过程（不进入下游业务字段）
    # True 表示请求退出外层 LoopUntil（对应 ADK 的 escalate）
    escalate: bool = False


@dataclass
class LlmStep:
    """
    单 Agent 步骤：调用一次 LLM，把结果写入 state[output_key]。

    instruction 支持用 {topic}、{content} 等占位符引用 Runtime.state。
    should_escalate：可选回调，根据模型输出 / state 决定是否退出循环。
    with_thinking：为 True 时要求模型先写思考过程，再写最终输出。
    """

    name: str
    role: str  # 写入 system prompt，约束角色行为
    instruction: str
    output_key: str  # 本步产出写入 state 的键名
    temperature: float = 0.5
    with_thinking: bool = True
    should_escalate: Optional[Callable[[str, Dict[str, Any]], bool]] = None


@dataclass
class Sequential:
    """顺序执行子节点，类似 ADK SequentialAgent。"""

    name: str
    steps: List[Any]


@dataclass
class LoopUntil:
    """
    条件循环，类似 ADK LoopAgent。

    每轮依次执行 steps；任一子步骤 escalate=True 则提前结束；
    否则跑满 max_iterations 后强制结束（exit_reason=max_iterations）。
    """

    name: str
    steps: List[Any]
    max_iterations: int = 4


@dataclass
class Runtime:
    """
    执行引擎：持有 LLM 客户端、共享 state、执行历史。

    state 在各 Agent 之间传递中间产物（调研、大纲、正文、审核意见等）。
    思考过程单独存为 state[f'{output_key}_thinking']，避免污染下游正文。
    """

    client: OpenAI
    model: str
    state: Dict[str, Any] = field(default_factory=dict)
    history: List[Dict[str, Any]] = field(default_factory=list)
    preview_chars: int = 800  # 控制台打印时截断长度，避免刷屏
    enable_thinking: bool = True  # 全局开关，可被 CLI --no-thinking 关闭

    def chat(self, system: str, user: str, temperature: float = 0.5) -> str:
        """调用 OpenAI 兼容 Chat Completions（DeepSeek 等）。"""
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
        )
        return (resp.choices[0].message.content or "").strip()

    def run(self, node: Any) -> StepResult:
        """按节点类型分发执行（组合模式入口）。"""
        if isinstance(node, LlmStep):
            return self._run_llm(node)
        if isinstance(node, Sequential):
            return self._run_sequential(node)
        if isinstance(node, LoopUntil):
            return self._run_loop(node)
        raise TypeError(f"unknown node: {type(node)}")

    def _format(self, template: str) -> str:
        """
        用 state 填充 instruction 中的 {key}。
        缺失的 key 原样保留为 {key}，避免 KeyError 中断整条流水线。
        """

        class _Safe(dict):
            def __missing__(self, key: str) -> str:
                return "{" + key + "}"

        safe_state = {k: ("" if v is None else v) for k, v in self.state.items()}
        return template.format_map(_Safe(**safe_state))

    def _preview(self, text: str) -> str:
        """控制台预览：过长则截断并标注总字数。"""
        text = text.strip()
        if len(text) <= self.preview_chars:
            return text
        return text[: self.preview_chars] + f"\n…（已截断，共 {len(text)} 字）"

    def _print_thinking_block(self, thinking: str, answer: str) -> None:
        """控制台分栏展示：思考过程 → 最终输出。"""
        print("\n  ┌─ 思考过程 ─────────────────────────────")
        if thinking:
            for line in self._preview(thinking).splitlines():
                print(f"  │ {line}")
        else:
            print("  │ （模型未按格式输出思考过程，已将全文视为最终输出）")
        print("  ├─ 最终输出 ─────────────────────────────")
        for line in self._preview(answer).splitlines():
            print(f"  │ {line}")
        print("  └──────────────────────────────────────")

    def _run_llm(self, step: LlmStep) -> StepResult:
        """执行单个 LlmStep：拼 prompt → 调模型 → 拆思考/输出 → 写 state → 可选 escalate。"""
        use_thinking = self.enable_thinking and step.with_thinking
        prompt = self._format(step.instruction)
        if use_thinking:
            prompt = f"{prompt}\n\n{_OUTPUT_FORMAT_HINT}"

        print(f"\n▶ [{step.name}]  {step.role}")

        if use_thinking:
            system = (
                f"你是「{step.role}」。完成任务时必须先思考再交付结果。"
                f"必须包含【思考过程】与【最终输出】两个区块；"
                f"下游只会使用【最终输出】中的内容。"
            )
        else:
            system = (
                f"你是「{step.role}」。严格完成本步骤任务，"
                f"只输出本步要求的内容，不要客套开场或解释过程。"
            )

        raw = self.chat(system=system, user=prompt, temperature=step.temperature)

        if use_thinking:
            thinking, answer = parse_thinking_and_answer(raw)
            self._print_thinking_block(thinking, answer)
        else:
            thinking, answer = "", raw
            print(self._preview(answer))

        # 业务字段只放最终输出；思考单独落盘，避免污染下游正文
        self.state[step.output_key] = answer
        thinking_key = f"{step.output_key}_thinking"
        if thinking:
            self.state[thinking_key] = thinking
        elif thinking_key in self.state:
            # 本轮无思考时清掉旧值，避免循环内残留上一轮思考
            self.state.pop(thinking_key, None)

        escalate = False
        if step.should_escalate:
            # escalate 判断基于最终输出（及 state），不看思考过程
            escalate = bool(step.should_escalate(answer, self.state))

        self.history.append(
            {
                "step": step.name,
                "role": step.role,
                "output_key": step.output_key,
                "thinking": thinking,
                "output": answer,
                "chars": len(answer),
                "thinking_chars": len(thinking),
                "escalate": escalate,
                "iteration": self.state.get("iteration"),
            }
        )
        return StepResult(output=answer, thinking=thinking, escalate=escalate)

    def _run_sequential(self, seq: Sequential) -> StepResult:
        """
        顺序跑完所有子步骤。

        注意：外层 Sequential 不会因子步骤 escalate 而中断整条流水线；
        escalate 只用于 LoopUntil 内部提前退出（见 _run_loop）。
        """
        print(f"\n{'=' * 56}\n=== Sequential: {seq.name} ===\n{'=' * 56}")
        last = StepResult()
        for child in seq.steps:
            last = self.run(child)
        return last

    def _run_loop(self, loop: LoopUntil) -> StepResult:
        """
        until-done 循环：
          for i in 1..max_iterations:
            跑完一轮子步骤；若 escalate → 退出
          否则 exit_reason = max_iterations
        """
        print(
            f"\n{'=' * 56}\n"
            f"=== LoopUntil: {loop.name} (max={loop.max_iterations}) ===\n"
            f"{'=' * 56}"
        )
        last = StepResult()
        for i in range(1, loop.max_iterations + 1):
            self.state["iteration"] = i
            print(f"\n── 优化轮次 {i}/{loop.max_iterations} ──")
            for child in loop.steps:
                last = self.run(child)
                if last.escalate:
                    self.state["exit_reason"] = "escalate"
                    print(f"\n✔ 循环因 escalate 退出（第 {i} 轮）")
                    return last

        # 模型始终不达标时的兜底，避免死循环
        self.state["exit_reason"] = "max_iterations"
        print(f"\n⚠ 达到 max_iterations={loop.max_iterations}，强制结束")
        return last


# ===========================================================================
# 二、业务：多 Agent 写文章流水线
# ===========================================================================


def _review_approved(review_text: str) -> bool:
    """
    判断审核是否通过（用于 escalate）。

    约定 reviewer 第一行输出「审核通过」或「需要修改」；
    同时兼容模型把结论写在文末的情况。
    """
    if not review_text:
        return False
    first = review_text.strip().splitlines()[0]
    if "审核通过" in first:
        return True
    return bool(re.search(r"(整体结论|结论)[:：]\s*审核通过", review_text))


def build_article_pipeline(max_iterations: int = 4) -> Sequential:
    """
    组装「写文章」Agent 图。

    state 数据流（关键键）：
      topic / requirement / target_words  ← 用户输入
      research  ← researcher   （另有 research_thinking）
      outline   ← planner
      draft     ← writer
      content   ← stylist，之后由 refiner 在循环内覆盖
      review    ← reviewer（每轮）
      article   ← publisher（最终 Markdown 成稿）
      各业务键另有对应的 {key}_thinking 保存思考过程
    """

    # ----- 阶段 1：调研 -----
    researcher = LlmStep(
        name="researcher",
        role="资深选题调研员",
        output_key="research",
        temperature=0.4,  # 偏低：要点要稳，少发挥
        instruction=(
            "主题：{topic}\n用户要求：{requirement}\n目标篇幅：{target_words} 字左右\n\n"
            "请输出调研简报，必须包含：\n"
            "1. 读者画像（是谁、关心什么、怕什么）\n"
            "2. 5 个核心事实 / 卖点 / 痛点（可合理推断，标注「推断」）\n"
            "3. 3 个差异化切入角度\n"
            "4. 建议避免的陈词滥调\n"
            "用简洁条目，不要写成正文。"
        ),
    )

    # ----- 阶段 2：策划大纲 -----
    planner = LlmStep(
        name="planner",
        role="内容策划主编",
        output_key="outline",
        temperature=0.4,
        instruction=(
            "主题：{topic}\n用户要求：{requirement}\n\n调研简报：\n{research}\n\n"
            "请给出完整写作大纲，必须包含：\n"
            "【选定角度】一句话\n"
            "【标题方向】3 个候选标题\n"
            "【结构】引言 → 3~5 个小节标题 + 每节要点 → 结尾行动号召\n"
            "【语气】例如专业但口语 / 故事感 / 教程感\n"
            "不要写正文。"
        ),
    )

    # ----- 阶段 3：写初稿 -----
    writer = LlmStep(
        name="writer",
        role="资深专栏作者",
        output_key="draft",
        temperature=0.7,  # 偏高：鼓励表达与例子
        instruction=(
            "主题：{topic}\n用户要求：{requirement}\n目标篇幅：约 {target_words} 字\n\n"
            "调研：\n{research}\n\n大纲：\n{outline}\n\n"
            "请按大纲写出完整初稿正文（含小标题）。\n"
            "要求：有具体例子或步骤，避免空话；不要输出标题候选列表，直接写文章。"
        ),
    )

    # ----- 阶段 4：润色（产出进入 content，供循环内审核/改稿）-----
    stylist = LlmStep(
        name="stylist",
        role="文风润色编辑",
        output_key="content",
        temperature=0.5,
        instruction=(
            "大纲：\n{outline}\n\n初稿：\n{draft}\n\n"
            "请润色初稿：\n"
            "- 保持事实与结构，不擅自删掉关键信息\n"
            "- 段落更顺、节奏更好、开头更抓人\n"
            "- 字数仍约 {target_words} 字\n"
            "只输出润色后的完整正文。"
        ),
    )

    # ----- 阶段 5：质量循环内的三个 Agent -----
    reviewer = LlmStep(
        name="reviewer",
        role="严苛内容审核主编",
        output_key="review",
        temperature=0.2,  # 低：评分与结论尽量稳定
        instruction=(
            "主题：{topic}\n要求：{requirement}\n大纲：\n{outline}\n\n"
            "待审正文：\n{content}\n\n"
            "请从以下维度打分（1-10），并给修改建议：\n"
            "1. 标题与开头吸引力\n"
            "2. 结构清晰度\n"
            "3. 信息密度与实用性\n"
            "4. 文风与可读性\n"
            "5. 与用户要求的契合度\n\n"
            "在【最终输出】中必须遵守：\n"
            "第一行只能是以下之一：\n"
            "- 审核通过\n"
            "- 需要修改\n"
            "然后列出各维度分数。\n"
            "若「需要修改」，再给出最多 5 条具体、可执行的修改建议（指出段落/问题/怎么改）。\n"
            "通过标准：所有维度 ≥ 8，且无明显事实空洞或跑题。\n"
            "评分推理写在【思考过程】里，不要写进【最终输出】的第一行之前。"
        ),
    )

    # 注意：refiner 同样写 content，覆盖上一轮正文，形成「改稿 → 再审」闭环
    refiner = LlmStep(
        name="refiner",
        role="改稿优化作者",
        output_key="content",
        temperature=0.55,
        instruction=(
            "主题：{topic}\n用户要求：{requirement}\n\n"
            "当前正文：\n{content}\n\n审核意见：\n{review}\n\n"
            "如果审核意见第一行是「审核通过」，原样输出当前正文。\n"
            "否则按审核意见逐条修改，保持约 {target_words} 字，输出完整修改后正文。"
        ),
    )

    def check_escalate(_text: str, state: Dict[str, Any]) -> bool:
        """
        终检回调：以 review 是否「审核通过」为准触发 escalate。

        这里不依赖 checker 模型原文（避免模型乱答导致退不出循环），
        与 ADK 里调用 content_approved 工具的效果一致。
        """
        approved = _review_approved(str(state.get("review") or ""))
        if approved:
            print("  ✨ [checker] escalate=True（审核通过，退出优化循环）")
        else:
            print("  … [checker] 尚未达标，继续下一轮")
        return approved

    checker = LlmStep(
        name="checker",
        role="发布终审员",
        output_key="check",
        temperature=0.0,
        instruction=(
            "审核意见：\n{review}\n\n"
            "若第一行或整体结论为「审核通过」，只回复：APPROVED\n"
            "否则只回复：CONTINUE"
        ),
        should_escalate=check_escalate,
    )

    # ----- 阶段 6：发行成稿（循环结束后执行）-----
    publisher = LlmStep(
        name="publisher",
        role="终稿发行编辑",
        output_key="article",
        temperature=0.4,
        instruction=(
            "主题：{topic}\n大纲：\n{outline}\n\n终稿正文：\n{content}\n\n"
            "请输出最终成稿，严格使用以下 Markdown 结构：\n\n"
            "# （正式标题，只选一个，要吸睛）\n\n"
            "> 导语：2~3 句，概括价值\n\n"
            "（正文，可保留小标题）\n\n"
            "---\n\n"
            "**写在最后**：一句行动号召或互动引导\n\n"
            "不要输出评分、过程说明或候选标题列表。"
        ),
    )

    # 质量循环：审核 → 改稿 → 终检（escalate 则跳出）
    optimization = LoopUntil(
        name="quality_loop",
        max_iterations=max_iterations,
        steps=[reviewer, refiner, checker],
    )

    # 完整流水线：前半顺序生产，中间循环提质，最后组装成稿
    return Sequential(
        name="multi_agent_article",
        steps=[researcher, planner, writer, stylist, optimization, publisher],
    )


# ===========================================================================
# 三、落盘与入口
# ===========================================================================


def _save_outputs(rt: Runtime, out_dir: Path) -> Path:
    """
    保存成稿与完整中间态，便于复盘每轮 Agent 产出。

    - *.md：最终成稿
    - *.json：业务字段 + 各步 thinking + history
    - *_thinking.md：按时间线汇总全部思考过程
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    topic_slug = re.sub(r"\s+", "_", str(rt.state.get("topic") or "article"))[:40]
    md_path = out_dir / f"{stamp}_{topic_slug}.md"
    json_path = out_dir / f"{stamp}_{topic_slug}.json"
    thinking_path = out_dir / f"{stamp}_{topic_slug}_thinking.md"

    article = str(rt.state.get("article") or rt.state.get("content") or "")
    md_path.write_text(article + "\n", encoding="utf-8")

    # 时间线：把每步思考过程写成可读 Markdown
    thinking_lines = [
        f"# 多 Agent 思考过程\n",
        f"- 主题：{rt.state.get('topic')}\n",
        f"- 要求：{rt.state.get('requirement')}\n",
        f"- 退出原因：{rt.state.get('exit_reason')}\n",
        f"- 优化轮次：{rt.state.get('iteration')}\n",
    ]
    for i, item in enumerate(rt.history, 1):
        thinking_lines.append(f"\n## {i}. [{item.get('step')}] {item.get('role') or ''}\n")
        if item.get("iteration"):
            thinking_lines.append(f"- 循环轮次：{item['iteration']}\n")
        thinking_lines.append("\n### 思考过程\n\n")
        thinking_lines.append((item.get("thinking") or "（无）") + "\n")
        thinking_lines.append("\n### 最终输出（摘要）\n\n")
        out = str(item.get("output") or "")
        thinking_lines.append((out[:1200] + ("…" if len(out) > 1200 else "")) + "\n")
    thinking_path.write_text("".join(thinking_lines), encoding="utf-8")

    payload = {
        "topic": rt.state.get("topic"),
        "requirement": rt.state.get("requirement"),
        "target_words": rt.state.get("target_words"),
        "exit_reason": rt.state.get("exit_reason"),
        "iteration": rt.state.get("iteration"),
        "research": rt.state.get("research"),
        "research_thinking": rt.state.get("research_thinking"),
        "outline": rt.state.get("outline"),
        "outline_thinking": rt.state.get("outline_thinking"),
        "draft": rt.state.get("draft"),
        "draft_thinking": rt.state.get("draft_thinking"),
        "content": rt.state.get("content"),
        "content_thinking": rt.state.get("content_thinking"),
        "review": rt.state.get("review"),
        "review_thinking": rt.state.get("review_thinking"),
        "article": rt.state.get("article"),
        "article_thinking": rt.state.get("article_thinking"),
        "history": rt.history,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return md_path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="多 Agent 协同写文章 Demo")
    p.add_argument("--topic", default="", help="文章主题")
    p.add_argument("--requirement", default="", help="额外写作要求")
    p.add_argument("--words", type=int, default=800, help="目标字数，默认 800")
    p.add_argument("--max-iter", type=int, default=4, help="质量优化循环最大轮次")
    p.add_argument(
        "--no-thinking",
        action="store_true",
        help="关闭思考过程（更快、更省 token；默认开启）",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    # OpenAI SDK 的 base_url 必须是 API 根，不要带 /chat/completions
    # 正确：https://api.deepseek.com  或  https://api.deepseek.com/v1
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip().rstrip("/")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip()

    if not api_key or api_key == "your-deepseek-api-key":
        print("请先在仓库根目录 .env 配置 DEEPSEEK_API_KEY 后再运行。")
        sys.exit(1)

    # 主题 / 要求：命令行优先，否则交互输入
    topic = (args.topic or "").strip()
    if not topic:
        topic = input("请输入文章主题：").strip()
    if not topic:
        print("主题不能为空。")
        sys.exit(1)

    requirement = (args.requirement or "").strip()
    if not requirement:
        requirement = input("额外要求（可回车跳过）：").strip() or "结构清晰、有干货、适合普通读者"

    enable_thinking = not args.no_thinking
    print(f"使用 base_url={base_url}  model={model}")
    print(
        f"主题={topic!r}  字数≈{args.words}  最大优化轮次={args.max_iter}  "
        f"思考过程={'开' if enable_thinking else '关'}"
    )

    # 初始 state：后续 Agent 通过 instruction 里的 {topic} 等占位符读取
    rt = Runtime(
        client=OpenAI(api_key=api_key, base_url=base_url),
        model=model,
        enable_thinking=enable_thinking,
        state={
            "topic": topic,
            "requirement": requirement,
            "target_words": str(args.words),
        },
    )

    graph = build_article_pipeline(max_iterations=max(1, args.max_iter))
    rt.run(graph)

    out_path = _save_outputs(rt, Path(__file__).resolve().parent / "output")

    print("\n" + "=" * 56)
    print("📕 最终成稿（摘要）")
    print("=" * 56)
    print(rt._preview(str(rt.state.get("article") or "")))
    print("\n" + "-" * 56)
    print(f"exit_reason = {rt.state.get('exit_reason')}")
    print(f"optimization rounds = {rt.state.get('iteration')}")
    print(f"saved markdown = {out_path}")
    print(f"saved json     = {out_path.with_suffix('.json')}")
    print(f"saved thinking = {out_path.with_name(out_path.stem + '_thinking.md')}")


if __name__ == "__main__":
    main()
