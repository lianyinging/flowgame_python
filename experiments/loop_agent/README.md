# loopAgent 可行性验证

本目录用于验证 **LoopAgent（直到满足条件再退出的迭代代理循环）** 能否接到 FlowGame 工作流引擎，**不改动主工程代码**。

示例来源：`/Users/lianying/Desktop/loopAgnet.py`（Google ADK：`LlmAgent` + `SequentialAgent` + `LoopAgent`）。

---

## 1. 示例在做什么

小红书创作流水线本质是：

```
SequentialAgent
  planner → writer → titler → engagement
  → LoopAgent(max=5)
       reviewer → refiner → final_checker
         └─ final_checker 调用 content_approved → escalate=True → 退出循环
```

相对现有 FlowGame 的关键点：

| ADK 概念 | 含义 | FlowGame 现状 |
|----------|------|----------------|
| `LlmAgent` | 单步 LLM + instruction + `output_key` 写 state | 已有 `llmNode` / `llmapiNode` |
| `SequentialAgent` | 按顺序跑子代理 | 画布边 + `Chain` 已支持 |
| `LoopAgent` | **while 未 escalate 且未到 max_iterations** | **没有**；现有 `loopNode` 是 for-each / 固定次数 |
| `ToolContext.actions.escalate` | 子代理主动退出循环 | **没有** |
| `state['xxx']` | 多代理共享状态 | `chain.memory` 可映射 |

结论：**模式可行**；不能把现有 `loopNode` 直接当成 LoopAgent，需要新增「条件退出的迭代循环」。

---

## 2. 可行性结论

**可行，且建议分两阶段。**

### 为什么可行

1. 引擎已是节点 `execute(chain) → dict` + `memory`，足够承载共享 state。
2. LLM 调用已有（OpenAI 兼容 / HTTP），demo 不必依赖 Google ADK。
3. 已有嵌套子图（`loopNode` 的 `parentId` + 子 chain），LoopAgent 可复用「节点内驱动子图」形态。
4. 退出条件可用：工具 escalate、审核文本关键词、或显式 `approved` 布尔输出。

### 主要风险

| 风险 | 说明 | 缓解 |
|------|------|------|
| 与 `loopNode` 语义冲突 | for-each vs until-done | 新类型 `loopAgentNode`，不要改 `loopNode` |
| Token / 费用 / 耗时 | 最多 N 轮 × 多 LLM | `maxIterations` + 超时 + 进度事件 |
| escalate 不可靠 | 模型可能不调工具 | 双重退出：工具 escalate **或** 输出字段 `approved=true` |
| 前端尚未有节点 | 后端先验证 | 本目录先跑通，再接画布 |
| 直接引 ADK | 与现有栈重叠、依赖重 | **验证期不引 ADK**；主工程继续自研 |

---

## 3. 推荐方案（三阶段）

### 阶段 A — 本目录验证（当前）

目标：证明「顺序 + 条件循环 + 共享 state + max_iterations」可跑通。

```bash
cd experiments/loop_agent
# 需已配置仓库根目录 .env 中的 DEEPSEEK_*，或 export DEEPSEEK_API_KEY=...
python demo_minimal.py
```

`demo_minimal.py` 用最少代码复现 ADK 核心语义（不依赖 `google.adk`）：

- `LlmStep`：一次 LLM，结果写入 `state[output_key]`
- `Sequential`：顺序执行
- `LoopUntil`：循环执行子步骤，直到 `escalate` 或达到 `max_iterations`

多 Agent 写文章流水线：

```
researcher → planner → writer → stylist
  → LoopUntil(reviewer → refiner → checker)
  → publisher（输出 Markdown 成稿）
```

```bash
python demo_minimal.py --topic "麻辣小龙虾" --requirement "适合厨房新手" --words 800
```

成稿会保存到 `experiments/loop_agent/output/`。

### 阶段 B — 接到 FlowGame 后端（验证通过后）

新增节点类型建议：`loopAgentNode`（名称可再定）。

**节点行为（伪代码）：**

```text
for i in 1..maxIterations:
  执行子图（reviewer → refiner → checker）
  若子图 memory 中 escalate / approved == true: break
  将子图产出写回父 memory（供下一轮引用）
输出：最终 content + iterations + exit_reason
```

**画布结构建议：**

```text
[Start] → …业务节点…
       → [loopAgentNode]          ← 容器节点
            ├─ reviewer (llmapi)
            ├─ refiner  (llmapi)
            └─ checker  (llmapi / code：写 approved 或 escalate)
       → [End]
```

实现落点（与现有一致）：

1. `chain/nodes.py` — `LoopAgentNode`
2. `parser/chain_parser.py` — `"loopAgentNode": self._parse_loop_agent`
3. 复用 `_parse_graph(..., parent_node=...)` 解析子图
4. `/execute/stream` 透传嵌套进度（可选但建议）

**与 `loopNode` 分工：**

| | `loopNode` | `loopAgentNode` |
|--|------------|-----------------|
| 迭代依据 | 列表 / 固定次数 | 退出条件 + max |
| 典型用途 | 批处理、对每条数据跑子流 | 审核-优化、ReAct、自纠错 |
| 退出 | 次数用尽 | escalate / approved / max |

### 阶段 C — 前端节点（后端契约稳定后）

- 容器节点：配置 `maxIterations`、退出字段名
- 子节点仍用现有 LLM / Code / HTTP
- 试运行展示「第几轮 / 为何退出」

---

## 4. 不建议的路径

1. **整仓迁 Google ADK / LangChain**：与 Tinyflow 画布双编排冲突，成本高。
2. **改造现有 `loopNode` 加 escalate**：破坏 for-each 语义，前端兼容差。
3. **验证阶段就上完整小红书 7 Agent**：调用多、贵、难排错；先用本目录最小 demo。

---

## 5. 验收标准（本目录）

- [ ] `demo_minimal.py` 能跑通至少 1 次「未通过 → 再优化 → 通过退出」
- [ ] 达到 `max_iterations` 时能强制结束并给出原因
- [ ] `state` 在轮次间可读写（审核意见 → 改写输入）
- [ ] 不依赖 `google.adk`，仅用项目已有 OpenAI 兼容调用方式

通过后再开阶段 B 的正式节点设计。

---

## 6. 主 Agent 动态调度 Demo

文件：`demo_orchestrator.py`

与 `demo_minimal.py`（固定流水线）不同：由**主控 Agent**每步决定下一个子 Agent。

| 层 | 做什么 | 代码位置 |
|----|--------|----------|
| Prompt Engineering | 角色/契约/Few-shot/JSON 决策格式 | `MASTER_SYSTEM_PROMPT`、`SUB_AGENT_SPECS` |
| Context Engineering | 按需装箱、状态卡片、截断、轨迹窗口 | `ContextEngine` |
| Harness Engineering | 白名单、重试、同 Agent 连调限制、max_steps、trace | `AgentHarness` |

```bash
python demo_orchestrator.py --topic "麻辣小龙虾" --requirement "适合厨房新手" --max-steps 12
```

输出：`output/*_orchestrator.md` + `*_trace.md` + `.json`。

---

## 7. 任意主题资讯抓取 Demo

文件：`demo_ai_news.py`（文件名沿用，**主题不限 AI**）

多 Agent：`scout`（Google News/RSS + 搜索）→ `fetcher` → `curator` → `writer`。

```bash
python demo_ai_news.py --topic "新能源汽车"
python demo_ai_news.py --topic "World Cup" --max-articles 8
python demo_ai_news.py --topic "AI Agent" --skip-search
```

不传 `--topic` 时会交互询问。输出：`output/*_{主题}_news.md`。
