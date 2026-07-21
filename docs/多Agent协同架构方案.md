# FlowGame 多 Agent 协同：生产级架构方案

> 状态：方案设计（基于现网 FlowGame + `experiments/loop_agent` 可行性验证）  
> 日期：2026-07-19  
> 目标：在**不推翻现有单流程编排能力**的前提下，建设可商用的多 Agent 协同体系。

---

## 1. 背景与目标

### 1.1 现状结论

| 能力 | 现状 |
|------|------|
| 单流程编排 | 已具备：画布节点 + 边 → Tinyflow JSON → `Chain` 执行 |
| 单流程执行 | 同步 `/execute`、流式 `/execute/stream`（NDJSON 进度） |
| 流程存储 | Redis：`flow_list:{methodKey}` |
| LLM / 知识库 / 记忆 | `llmapiNode`、`knowledgeNodePlus`、`memoryRead/Write` 等 |
| 循环 | `loopNode` = **for-each / 固定次数**，不是 until-done |
| 多 Agent 协同 | **生产未具备**；仅在 `experiments/loop_agent` 验证模式 |

### 1.2 产品命题（与你的初步想法对齐）

> **每一个已配置的 Flow（`methodKey`）≈ 一个可复用的 Agent（单职责能力单元）。**  
> 在此之上增加 **Agent Team（多智能体团队）** 层，负责：如何组合、如何调度、如何共享上下文、如何退出与计费。

也就是说：

- **不推翻**现有「画布配一个流程」的产品心智；
- **新增**「多流程如何协同」的一等公民能力；
- Demo 验证过的三种模式，上升为正式产品能力，而不是继续堆实验脚本。

### 1.3 建设目标（商用口径）

1. **可编排**：用户能在前端配置「Agent 团队 + 协作策略」，而不仅是单 DAG。  
2. **可运行**：主控调度、条件循环、工具调用、子 Agent 调用均有后端契约。  
3. **可观测**：每一步 Agent / 节点 / 工具可追踪，支持试运行与审计。  
4. **可隔离**：多租户前缀、密钥、配额、审计日志可落地。  
5. **可计费**：按调用次数、Token、工具调用、时长计量。  
6. **可演进**：先固定协同，再动态主控；不一次上 LangChain/ADK 全家桶。

### 1.4 非目标（本期明确不做）

- 不把整个引擎替换为 LangChain / Google ADK / LangGraph。  
- 不把现有 `loopNode` 改成 until-done（避免破坏已有批处理语义）。  
- 不在一期做完全自主的开放世界 Agent（无护栏无限上网/无限工具）。

---

## 2. 可行性分析

### 2.1 总体结论：**可行，且建议「分层演进」**

现有 FlowGame 已经具备多 Agent 的**原子能力**（单 Agent = 单流程），缺的是**协同层（Orchestration / Team Runtime）**。  
实验目录已证明三类模式可跑通：

| 模式 | Demo | 商用映射 |
|------|------|----------|
| 固定流水线 + 质量循环 | `demo_minimal.py` | `Team` 固定顺序 + `loopAgent` 容器 |
| 主 Agent 动态路由 | `demo_orchestrator.py` | `SupervisorAgent` / `router` 策略 |
| 工具型协同（搜+抓+写） | `demo_ai_news.py` | Agent + Tool 注册表 |

因此：**技术路径清晰，工程风险主要在产品边界、状态模型、护栏与计费，而不在「能不能做」。**

### 2.2 为什么可行（支撑点）

1. **单流程执行引擎成熟**：解析、边驱动、并行 fork、流式进度已有。  
2. **流程已可复用**：`methodKey` 持久化，天然适合「Agent = 已发布流程」。  
3. **嵌套子图已有先例**：`loopNode` 的 `parentId` 模式可复用为「团队内子图 / 容器节点」。  
4. **共享记忆通道已有雏形**：`chain.memory` + Redis memory/state，可扩展为 Team Blackboard。  
5. **不依赖重框架**：自研协同层更贴合画布产品，商用可控。

### 2.3 主要风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| 与 `loopNode` 语义混淆 | 产品/前端配置混乱 | 新类型：`loopAgentNode` / `teamNode`，严禁改写 `loopNode` |
| 动态调度不可控（死循环、乱跳） | 成本爆炸、结果不可复现 | Harness：白名单、maxSteps、同 Agent 连调限制、强制 FINISH |
| 上下文膨胀 | Token 贵、超时 | Context Engineering：按 Agent 声明装箱、摘要、截断 |
| 工具/网页抓取不稳定 | 商用 SLA 差 | 工具抽象 + 降级 + 缓存 + 域名白名单 |
| 多租户串数据 | 合规事故 | 强制 `tenantId` / Redis prefix / 密钥隔离 |
| 一次性做太大 | 延期 | 三阶段交付（见第 8 节） |

### 2.4 与「引入 LangChain / ADK」的取舍

| 方案 | 优点 | 缺点 | 建议 |
|------|------|------|------|
| 整仓迁 LangChain/ADK | 生态多 | 与 Tinyflow 画布双编排，迁移成本极高 | **不建议** |
| 局部用其组件 | 加速某类 Agent | 边界模糊 | 仅工具层可选 |
| **自研 Team Runtime + 复用现有 Chain** | 与产品一致、可控 | 需自建协同语义 | **推荐** |

---

## 3. 核心概念模型

### 3.1 概念分层

```
┌─────────────────────────────────────────────────────────┐
│  Team（多智能体团队）                                      │
│  - 协作策略：Sequential / LoopUntil / Supervisor          │
│  - Blackboard（共享状态）                                  │
│  - Harness（步数、白名单、预算、审计）                        │
├─────────────────────────────────────────────────────────┤
│  Agent（= 已发布 Flow / methodKey，单职责）                 │
│  - 输入契约 / 输出契约                                      │
│  - 可被 Team 调用，也可单独 /execute                        │
├─────────────────────────────────────────────────────────┤
│  Node（画布原子节点：llmapi / http / knowledge / code…）    │
├─────────────────────────────────────────────────────────┤
│  Tool（可选：web_search / fetch_url / 内部 API…）           │
└─────────────────────────────────────────────────────────┘
```

### 3.2 关键定义

#### Agent（智能体）

- **定义**：一个**已发布**、可独立执行的 Flow（`methodKey` + 版本）。  
- **职责**：只做一类事（调研 / 写作 / 审核 / 改稿 / 抓取…）。  
- **契约**：
  - `input_schema`：需要哪些字段（从 Blackboard / 请求变量取）
  - `output_schema`：写回哪些字段
  - `timeout_ms` / `retry` / `cost_class`

> 说明：画布上「配置单流程」的能力继续保留；发布后即可注册为 Agent。

#### Team（智能体团队）

- **定义**：一组 Agent + 一种协作策略 + 共享 Blackboard + 护栏配置。  
- **存储**：独立于单流程，例如 `team:{teamKey}`。  
- **执行入口**：`POST /team/execute`（可与现有 execute 并存）。

#### Blackboard（共享黑板）

- Team 运行期间的共享状态（类似 demo 里的 `state`）。  
- 与单流程 `chain.memory` 的关系：
  - 调用子 Agent 时：按契约从 Blackboard **投影**为该 Flow 的 `variables`
  - 子 Agent 结束后：按契约把输出 **写回** Blackboard
- 持久化：可选 Redis（便于断点续跑 / 审计），默认运行期内存 + 最终落库。

#### Collaboration Strategy（协作策略）

一期建议只支持三种（已验证）：

| 策略 ID | 行为 | 对应 Demo |
|---------|------|-----------|
| `sequential` | 按配置顺序调用 Agent | `demo_minimal` 前半段 |
| `loop_until` | 循环执行一组 Agent，直到 `approved/escalate` 或 `maxIterations` | `demo_minimal` 质量循环 |
| `supervisor` | 主控 Agent 每步决定下一个 Agent 或 FINISH | `demo_orchestrator` |

后期可扩展：`parallel_map`、`debate`、`handoff` 等，但不要一期全做。

#### Tool（工具）

- 与 Agent 区别：Tool 是**短函数能力**（搜网页、抓 URL、查库），通常不配完整画布。  
- Agent 内部仍可用现有节点实现工具；Team 层也可直接暴露 Tool 给 Supervisor。  
- 商用建议：Tool 必须注册、鉴权、限流、审计。

---

## 4. 目标架构（生产）

### 4.1 逻辑架构

```
                    ┌──────────────┐
                    │  前端编辑器   │
                    │ Flow / Team  │
                    └──────┬───────┘
                           │ JSON 配置
                    ┌──────▼───────┐
                    │  API Gateway  │  鉴权 / 租户 / 配额
                    └──────┬───────┘
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
    Flow Runtime     Team Runtime     Tool Runtime
    (现有 Chain)     (新增协同层)      (新增/渐进)
           │               │               │
           └───────────────┼───────────────┘
                           │
                   ┌───────┴───────┐
                   ▼               ▼
              Redis/Qdrant     Trace/Metering
```

### 4.2 Team Runtime 内部流水线

```
请求 (teamKey, variables)
  → 加载 Team 定义 + 成员 Agent 元数据
  → 初始化 Blackboard
  → 按 strategy 进入调度循环
        ├─ sequential：按列表 invoke Agent
        ├─ loop_until：子序列循环 + 退出条件
        └─ supervisor：主控决策 → 校验（Harness）→ invoke
  → 每次 invoke：
        Blackboard 投影 → 调用现有 Flow 执行器 → 写回 Blackboard
        发射 trace 事件（可对接现有 stream）
  → 结束：汇总输出 + 计量落账
```

### 4.3 与现有执行器的集成原则（关键）

**子 Agent 调用 = 调用现有 `execute(workflowJson | methodKey)`，不要重写一套节点引擎。**

好处：

- 已有节点（LLM/知识库/HTTP/记忆）全部复用  
- 前端继续用同一套节点库配置 Agent  
- Team 层只做「调度与状态」，边界清晰  

约束：

- Team 流式进度需要能**嵌套上报**「当前 Agent + 其内部节点」  
- 子 Agent 超时/失败策略由 Team Harness 统一处理  

### 4.4 建议新增的核心模块（后端）

| 模块 | 职责 |
|------|------|
| `team/models.py` | Team / Member / Strategy / Blackboard schema |
| `team/registry.py` | Agent 注册（从 methodKey 发布） |
| `team/runtime.py` | 协同执行主循环 |
| `team/strategies/*` | sequential / loop_until / supervisor |
| `team/harness.py` | 白名单、步数、预算、重试、强制结束 |
| `team/context.py` | 上下文装箱 / 摘要 / 投影 |
| `team/router_api.py` | `/team/*` API |
| `observability/*` | trace、token、耗时 |
| `billing/*`（可二期） | 用量事件 |

前端（flowgame 仓）对应：

- Agent 发布面板（Flow → Agent）  
- Team 画布 / 配置页（成员、策略、黑板字段、护栏）  
- 试运行：展示「第几个 Agent / 第几轮 / 为何退出」  

---

## 5. 三种协同模式的产品化设计

### 5.1 Sequential Team（固定流水线）

**适用**：内容生产、审批流、ETL 式 AI 流水线。  

```
researcher → planner → writer → stylist → publisher
```

配置要点：

- 有序列表 `members[]`  
- 每步：`input_map` / `output_map`（Blackboard 字段映射）  
- 任一步失败：`fail_fast` 或 `continue_on_error`

### 5.2 LoopUntil Team（质量/自纠错循环）

**适用**：审核-改稿、测试-修复、直到达标。  

```
loop:
  reviewer → refiner → checker
until approved or maxIterations
```

退出条件（建议双重）：

1. Blackboard 字段 `approved == true`  
2. 或 checker 输出约定标记 / escalate  

**注意**：与现有 `loopNode`（for-each）并存，UI 文案必须区分：

- `loopNode`：对列表每一项跑子流程  
- `loopAgent` / `loop_until`：条件未满足就继续跑  

### 5.3 Supervisor Team（主控动态调度）

**适用**：目标明确但路径不固定；需要主控决定「下一步找谁」。  

```
while steps < maxSteps:
  master.decide(next_agent | FINISH)
  harness.validate(decision)
  invoke(next_agent)
```

生产护栏（必须有）：

- `allowed_agents` 白名单  
- `max_steps`  
- `max_same_agent_streak`  
- 非法决策重试 N 次后强制 FINISH  
- 单次 Team 预算（Token / 金额 / 工具次数）  

主控本身也可以是一个 Flow（`methodKey=supervisor_xxx`），输出严格 JSON 决策；  
**Harness 负责校验，不信任模型「自觉」。**

---

## 6. 数据模型（建议）

### 6.1 Agent 元数据（发布自 Flow）

```json
{
  "agentKey": "writer_v1",
  "methodKey": "flow_writer_001",
  "name": "专栏写手",
  "description": "根据大纲写正文",
  "version": "1.0.0",
  "inputSchema": {
    "topic": "string",
    "outline": "string",
    "requirement": "string"
  },
  "outputSchema": {
    "content": "string"
  },
  "timeoutMs": 120000,
  "tags": ["writing"]
}
```

### 6.2 Team 定义

```json
{
  "teamKey": "content_factory",
  "name": "内容工厂",
  "strategy": "supervisor",
  "members": [
    {"agentKey": "researcher_v1", "alias": "researcher"},
    {"agentKey": "writer_v1", "alias": "writer"},
    {"agentKey": "reviewer_v1", "alias": "reviewer"},
    {"agentKey": "refiner_v1", "alias": "refiner"},
    {"agentKey": "publisher_v1", "alias": "publisher"}
  ],
  "supervisorAgentKey": "orchestrator_v1",
  "blackboardDefaults": {
    "topic": "",
    "requirement": ""
  },
  "harness": {
    "maxSteps": 12,
    "maxSameAgentStreak": 2,
    "maxDecisionRetries": 2,
    "maxTokenBudget": 200000,
    "allowedAgents": ["researcher", "writer", "reviewer", "refiner", "publisher"]
  },
  "output": {
    "primaryKey": "article"
  }
}
```

### 6.3 运行实例（Run）

```json
{
  "runId": "run_xxx",
  "teamKey": "content_factory",
  "tenantId": "t1",
  "status": "running|succeeded|failed|cancelled",
  "blackboard": {},
  "trace": [
    {
      "step": 1,
      "type": "agent_call",
      "agentKey": "researcher_v1",
      "startedAt": "...",
      "endedAt": "...",
      "tokenUsage": {},
      "ok": true
    }
  ],
  "exitReason": "master_finish|max_steps|error",
  "metrics": {}
}
```

存储建议：

- 定义：Redis 或 DB（商用建议 **DB 为主、Redis 缓存**）  
- Run / Trace：DB + 对象存储（长文本）  
- 热路径 Blackboard：Redis  

---

## 7. API 设计（草案）

前缀建议：`/api/v1/flowGame`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/agents/publish` | 从 `methodKey` 发布/更新 Agent |
| GET | `/agents` | 列表 |
| GET | `/agents/{agentKey}` | 详情 |
| POST | `/teams` | 创建 Team |
| PUT | `/teams/{teamKey}` | 更新 |
| GET | `/teams/{teamKey}` | 详情 |
| POST | `/teams/{teamKey}/execute` | 同步执行 Team |
| POST | `/teams/{teamKey}/execute/stream` | NDJSON 流式执行 |
| GET | `/teams/runs/{runId}` | 查询运行与 trace |

流式事件建议在现有节点事件之上扩展：

```text
team_started
agent_started      { agentKey, step, alias }
agent_finished     { agentKey, step, ok, durationMs }
supervisor_decision{ action, nextAgent, thinking }
team_finished      { exitReason }
team_error
```

内部仍可复用现有 `node_started/node_finished`（挂在某个 agent 作用域下）。

---

## 8. Prompt / Context / Harness（生产级要求）

实验里三层工程必须产品化，而不是只存在 demo：

### 8.1 Prompt Engineering

- Agent 级：系统角色、输入输出契约、禁止事项  
- Supervisor 级：决策 JSON schema + Few-shot + 可用 Agent 目录  
- 版本化：Prompt 变更可回滚（与 Agent version 绑定）

### 8.2 Context Engineering

- **最小充分上下文**：只注入 Agent `inputSchema` 声明字段  
- 长文本：摘要 / 截断 / 分层（标题+摘要进主控，全文进写手）  
- Supervisor 看「状态卡片 + 最近轨迹」，禁止每次 dump 全文 Blackboard  

### 8.3 Harness Engineering（商用生命线）

| 护栏 | 说明 |
|------|------|
| 白名单 | 只能调度已配置成员 |
| maxSteps / maxIterations | 防死循环 |
| 预算 | Token / 金额 / 工具次数 |
| 决策校验 | JSON schema + 重试 + 强制结束 |
| 超时 | Agent / Tool / Team 分层超时 |
| 幂等 | `runId` 防重复扣费 |
| 人工接管（可选） | 关键步骤人工确认 |

---

## 9. 前端落地：独立 Team 配置怎么实现

> 前端仓库路径（本机）：`/Users/lianying/Desktop/ai工作流/flowgame`  
> 结论先说：**Team 不用现有 Tinyflow（`@tinyflow-ai/ui`）流程画布配置；在 `apps/editor` 内新增「Team 工作室」页面，采用「Arco 表单 + 可排序成员列表 + 字段映射抽屉」落地；一期不上第二套节点画布。**

### 9.0 现有前端基线（以真实仓库为准）

| 项 | 实际现状 |
|----|----------|
| 仓库 | `flowgame`（pnpm Monorepo） |
| 主应用 | `apps/editor`（包名 `flowgame-editor`，`pnpm dev` 入口） |
| 包 | `@flowgame/core`（API/节点注册）、`@flowgame/vue`（`FlowEditor` 等） |
| 框架 | **Vue 3 + Vite + TypeScript + vue-router** |
| UI | **Arco Design Vue（`@arco-design/web-vue`）** |
| 流程画布 | **`@tinyflow-ai/ui` + `@flowgame/vue`**（单 Agent/Flow 编排） |
| 请求 | `axios` + `apps/editor/src/request/flowgame.ts`；`@flowgame/core` 的 `configureFlowGameClient` |
| 已有能力组件 | `ProForm` / `ProTable` / `ProDrawer`（`apps/editor/src/components/ProComponent`） |
| 现状路由 | 以流程编辑器为主（`apps/editor/src/views/flow-editor`） |

### 9.1 选型结论（拍板）

| 维度 | 选型 | 理由 |
|------|------|------|
| 落地位置 | **`apps/editor` 新增页面**（不新开前端仓库） | 与流程列表、知识库、试运行同一应用，登录/代理/样式统一 |
| 框架 / 构建 | **保持 Vue 3 + Vite + TS + vue-router** | 零迁移 |
| UI | **Arco Design Vue**（`a-form` / `a-table` / `a-drawer` / `a-tabs` / `a-steps`） | 编辑器已全面使用；复用 `ProForm`/`ProDrawer` |
| 状态 | **一期用 `ref`/`reactive` + composable（`hooks/`）**；Team 草稿复杂后再按需加 Pinia | 与当前 `useSelection` / `useLoading` 风格一致，避免为 Team 单独引生态 |
| Team 主编排形态 | **配置式 UI（非 Tinyflow DAG）** | Team = 成员/策略/映射/护栏，不是节点连线 |
| 成员排序 | **`sortablejs` + `vuedraggable@next`（Vue 3）** | sequential / loop 顺序刚需；Arco 无内置排序列表 |
| API | 扩展 `@flowgame/core` 客户端方法 + `apps/editor/src/api/team.ts`（或 `request/`） | 与现有 `/api` 代理、Redis 前缀头一致 |
| 轻量预览（二期可选） | 只读「成员卡片时间线 / 简易箭头」即可；**不必上 Vue Flow** | 画布引擎已是 Tinyflow，再引入 Vue Flow 两套图引擎成本高 |
| 明确不用 | 在 Tinyflow 画布上拖 Team 节点 | 与黑板映射、supervisor 动态调度不匹配 |
| 明确不用一期 | LogicFlow / X6 / 新 Monorepo 应用 | 工期与维护成本过高 |

**一句话：在现有 `flowgame/apps/editor` 上加页面；技术栈不变（Vue3 + Arco + Tinyflow 只服务单 Agent）；Team 用表单工作室配置。**

### 9.2 信息架构与路由

在 `apps/editor` 增加导航（侧栏或顶栏，文案可调）：

```
工作流
  └─ 流程编辑器          ← 已有 flow-editor，配置单 Agent（Flow）

智能体
  ├─ Agent 中心          ← 新增：从 Flow 发布 / 管理契约
  └─ Team 工作室         ← 新增：独立 Team 配置 + 试运行
```

建议路由（挂到 `apps/editor/src/router/index.ts`）：

| 路由 | 页面组件（建议路径） |
|------|----------------------|
| 现有流程页 | `views/flow-editor/index.vue` |
| `/agents` | `views/agent/AgentList.vue` |
| `/agents/:agentKey` | `views/agent/AgentDetail.vue` |
| `/teams` | `views/team/TeamList.vue` |
| `/teams/:teamKey/edit` | `views/team/TeamEditor.vue`（**主战场**） |
| `/teams/:teamKey/runs/:runId` | `views/team/TeamRunDetail.vue` |

流程编辑器内增加入口：「发布为 Agent」（对话框），发布成功后可「去组建 Team」。

### 9.3 Team 配置页交互（落地线框）

一期推荐 **Arco `a-tabs` 单页**，降低开发量：

```
┌──────────────────────────────────────────────────────────┐
│ Team 名称 / teamKey          [保存] [试运行]              │
├──────────────────────────────────────────────────────────┤
│ Tab: 基本信息 | 成员与映射 | 策略与护栏 | 试运行           │
├──────────────────────────────────────────────────────────┤
│  【成员与映射】                                           │
│  ┌────────────────────────────────────────────────────┐  │
│  │ ≡ researcher  →  [选择已发布Agent ▼]  [映射] [删]   │  │
│  │ ≡ writer      →  [选择已发布Agent ▼]  [映射] [删]   │  │
│  │ ≡ reviewer    →  [选择已发布Agent ▼]  [映射] [删]   │  │
│  │ [+ 添加成员]                                        │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  「映射」用现有 ProDrawer / a-drawer：                     │
│  Blackboard.topic      → Agent.input.topic               │
│  Agent.output.research → Blackboard.research             │
│  （下拉只展示该 Agent 的 inputSchema / outputSchema）      │
└──────────────────────────────────────────────────────────┘
```

**策略 Tab：**

- `sequential`：成员列表顺序即执行顺序（拖拽排序）  
- `loop_until`：配置循环成员、`maxIterations`、`exitField`（如 `approved`）  
- `supervisor`（二期）：主控 Agent + 可调度白名单  

**试运行 Tab：**

- 用 `ProForm`/`a-form` 填 Blackboard 初始值  
- `fetch`/`axios` 调 `POST /api/v1/flowGame/teams/{teamKey}/execute/stream`  
- 时间线（可用 Arco `a-timeline`）展示 agent 级事件  
- 侧栏 Blackboard 快照  

### 9.4 前端模块拆分（按真实仓库）

**推荐主要改 `apps/editor`（产品壳）；契约类型可沉到 `@flowgame/core` 以便复用。**

```text
flowgame/
├── apps/editor/src/
│   ├── views/
│   │   ├── flow-editor/          # 已有：单 Agent 画布
│   │   ├── agent/                # 新增
│   │   │   ├── AgentList.vue
│   │   │   ├── AgentDetail.vue
│   │   │   └── AgentPublishDialog.vue
│   │   └── team/                 # 新增
│   │       ├── TeamList.vue
│   │       ├── TeamEditor.vue
│   │       ├── TeamRunDetail.vue
│   │       └── components/
│   │           ├── TeamBasicForm.vue
│   │           ├── MemberSortList.vue
│   │           ├── MemberMapDrawer.vue
│   │           ├── StrategyForm.vue
│   │           ├── HarnessForm.vue
│   │           ├── TeamRunPanel.vue
│   │           └── BlackboardPreview.vue
│   ├── api/
│   │   ├── team.ts               # Team CRUD + execute stream
│   │   └── agent.ts              # Agent publish / list
│   ├── hooks/
│   │   └── useTeamEditor.ts      # 草稿、校验、dirty
│   └── router/index.ts           # 挂载新路由
└── packages/core/src/
    └── team/                     # 可选：Team/Agent TS 类型与 client 方法
        ├── types.ts
        └── client.ts
```

`@flowgame/vue` **一期不必大改**：继续专注 `FlowEditor`；Team UI 放在 editor 应用层更合适（与「配置壳」一致）。若未来要把 Team 编辑器也 npm 出去，再抽成 `@flowgame/vue` 子模块。

### 9.5 数据流（前端 ↔ 后端）

```
flow-editor 保存 Flow（现有 Redis methodKey）
    → AgentPublishDialog「发布为 Agent」
    → POST /api/v1/flowGame/agents/publish
    → Agent 出现在 Team 成员下拉

TeamEditor（useTeamEditor 维护 TeamDraft）
    → 保存 PUT /api/v1/flowGame/teams/{teamKey}
    → 试运行 POST .../teams/{teamKey}/execute/stream
         → NDJSON：team_* / agent_* 
         → TeamRunPanel / BlackboardPreview
```

**保存前校验（editor 必做）：**

1. 成员 `alias` 唯一  
2. 每个成员已选 `agentKey`  
3. `inputMap` 覆盖 Agent `inputSchema` 必填项  
4. `outputMap` 目标字段已在 Blackboard 定义中  
5. `loop_until` 退出字段合法  
6. 后端再用同一套 schema 校验  

### 9.6 为什么一期不用「Team 画布」

| 方案 | 优点 | 缺点 | 决策 |
|------|------|------|------|
| A. 复用 Tinyflow 画布配 Team | 视觉统一 | 黑板映射/动态调度难表达；和单 Agent 混谈 | ❌ |
| B. 再引 Vue Flow / X6 | 好看 | 与现有 `@tinyflow-ai/ui` 双图引擎；工期长 | ❌ 一期不做 |
| **C. Arco 表单工作室 + 拖拽排序** | 快、与 Team JSON 1:1、贴合现有 Pro* 组件 | 大团队预览弱 | ✅ **一期落地** |

### 9.7 一期前端交付清单（可排期）

| 序号 | 交付物 | 位置 | 优先级 |
|------|--------|------|--------|
| F1 | Agent 发布对话框 | `apps/editor` + 流程页入口 | P0 |
| F2 | Agent 列表 / 详情 | `views/agent` | P0 |
| F3 | Team 列表 + 新建 | `views/team` | P0 |
| F4 | TeamEditor：成员拖拽、策略、映射抽屉、护栏 | `views/team` + Arco/Pro* | P0 |
| F5 | 试运行面板（stream + timeline） | `TeamRunPanel.vue` | P0 |
| F6 | 保存前校验 | `useTeamEditor.ts` | P0 |
| F7 | core 类型与 API 封装 | `packages/core`（可选但推荐） | P0 |
| F8 | Supervisor 表单 | 跟后端阶段 2 | P1 |
| F9 | 只读成员关系预览 | 二期 | P2 |

### 9.8 集成注意点（针对本仓库）

1. **代理**：继续 Vite 把 `/api` 转到 `flowgame_python`（8008），Team API 走同一前缀 `/api/v1/flowGame`。  
2. **客户端**：优先扩展 `@flowgame/core` 的 request 封装，避免 editor 里再复制一份 axios 细节。  
3. **画布边界**：`@tinyflow-ai/ui` / `FlowEditor` **只服务单 Agent**；Team JSON 独立存储、独立路由。  
4. **组件复用**：映射抽屉优先 `ProDrawer` + `ProForm`，列表优先 `ProTable` / Arco Table。  
5. **样板间**：内置 1 个「通用顺序 Team」模板（业务字段空），避免用户以为只能做文案。  

### 9.9 交互原则（产品）

- 用户心智：**先在流程编辑器配 Agent并发布，再在 Team 工作室组装**  
- Team 不是第二张 Tinyflow 大图；复杂逻辑仍在单 Agent 画布内  
- 试运行要能回答：当前 Agent、黑板内容、（二期）主控为何选人  
- 字段映射是一等公民：Agent IO 可各不相同  

---


## 10. 分期落地路线图

### 阶段 0 — 已完成（实验）

- [x] Sequential + LoopUntil 语义验证（`demo_minimal`）  
- [x] Supervisor 动态调度验证（`demo_orchestrator`）  
- [x] 工具型协同验证（`demo_ai_news`）  
- [x] Prompt / Context / Harness 分层意识建立  

### 阶段 1 — MVP（可内测商用雏形）建议 4~6 周

**范围**

1. Agent 发布（Flow → Agent 元数据）  
2. Team：仅 `sequential` + `loop_until`  
3. Blackboard 映射 + `/teams/*/execute` + stream  
4. 基础 trace（agent 级）  
5. 租户前缀沿用现有 Redis prefix  

**验收**

- 用现有「写文章」拆成 4~6 个 Agent，组 Team 跑通  
- 质量循环可 escalate 退出  
- 试运行可见每步 Agent  

### 阶段 2 — Supervisor + 工具（可对外商用）建议 +4~6 周

1. `supervisor` 策略 + Harness 全套护栏  
2. Tool 注册（web_search / fetch_url 先做 2 个）  
3. Token/次数计量事件（对接账单可后置）  
4. Run 持久化与回放  

**验收**

- 主控动态调度稳定，非法决策可自愈/强制结束  
- 网页检索类 Team 可配置主题产出 MD  

### 阶段 3 — 硬化（规模化商用）

1. DB 化定义与审计、细粒度权限  
2. 配额 / 账单 / 告警  
3. 评测集（同一 Team 回归）  
4. 多区域、高可用、队列化执行（长任务）  

---

## 11. 商用化清单（上线门禁）

| 类别 | 必须具备 |
|------|----------|
| 安全 | 租户隔离、密钥不落日志、工具域名白名单 |
| 稳定 | 超时、重试、熔断、maxSteps |
| 可观测 | runId、agent trace、错误码 |
| 成本 | Token/工具计量、预算熔断 |
| 合规 | 抓取/搜索合规提示、内容审计钩子 |
| 体验 | 流式进度、失败可理解、配置校验 |

---

## 12. 推荐落地形态（给你拍板用）

### 12.1 产品形态一句话

> **FlowGame = Agent 工厂（单流程） + Team 编排（多 Agent 协同运行时）。**

### 12.2 技术形态一句话

> **Agent 继续用现有 Chain 执行；新增 Team Runtime 只负责调度、黑板、护栏与计量。**

### 12.3 一期策略选择建议

| 若你的首要场景是… | 一期优先 |
|------------------|----------|
| 内容生产 / 固定 SOP | `sequential` + `loop_until` |
| 开放任务、路径不固定 | 一期仍先做固定协同，二期再上 `supervisor` |
| 强依赖联网检索 | 同步做 Tool 抽象（不要写死在某个 Agent 里） |

**个人建议（结合你已有 demo）：**  
先上 **Agent 发布 + Sequential/LoopUntil Team**（最贴现有画布、风险最低），  
把 Supervisor 作为二期「高级模式」开放——主控很强，但护栏与评测要求更高。

---

## 13. 与实验 Demo 的对应关系

| 实验文件 | 验证点 | 生产归属 |
|----------|--------|----------|
| `demo_minimal.py` | 单职责 Agent + 顺序 + 条件循环 + escalate | Team strategy: sequential / loop_until |
| `demo_orchestrator.py` | 主控路由 + Prompt/Context/Harness | Team strategy: supervisor |
| `demo_ai_news.py` | 搜索/抓取工具 + 多 Agent 流水线 | Tool Runtime + Sequential Team |

原则：**Demo 只证明模式，生产实现走 Team Runtime，不再维护脚本式编排作为主路径。**

---

## 14. 下一步行动（建议顺序）

1. **评审本方案**：确认一期策略范围（是否包含 Supervisor / Tool）。  
2. **冻结契约**：Agent 元数据、Team JSON、Blackboard 映射、流式事件。  
3. **后端 MVP**：`/agents/publish` + `/teams` + sequential/loop_until 执行。  
4. **前端 MVP**：Agent 发布 + Team 配置 + 试运行轨迹。  
5. **样板间**：把「多 Agent 写文章」从 demo 迁成正式 Team 模板。  
6. **再开 Supervisor / 联网 Tool**。

---

## 15. 附录：关键决策问答

**Q1：每个流程都是 Agent 吗？**  
A：建议「**发布后**才是 Agent」。草稿 Flow 仍是流程；发布产生 `agentKey` + 契约，才能进 Team。

**Q2：要不要把多 Agent 画成一张超大 DAG？**  
A：可以表达顺序，但动态调度 / 条件循环会很痛苦。建议 **Team 层表达协同，Agent 内表达单职责复杂逻辑**。

**Q3：loopNode 还要吗？**  
A：要。它继续服务批处理；until-done 用新能力，二者不要合并。

**Q4：MCP 要不要一期上？**  
A：能力上适合做 Tool 协议；一期可先内部 Tool 接口，二期再 MCP 化对外。

**Q5：是否必须上向量库才能做多 Agent？**  
A：否。多 Agent 核心是调度与状态；知识库是 Agent 可选能力。

---

## 16. 总结

- **可行性：高。** 现有 FlowGame 已是合格的 Agent 执行底座；缺口在协同层。  
- **正确抽象：Agent = 已发布 Flow；Team = 协同运行时。**  
- **实施策略：复用 Chain，新增 Team Runtime；分三期，先固定协同再动态主控。**  
- **商用关键：Harness、租户隔离、计量、可观测，缺一不可。**

---

*文档版本：v1.0*  
*关联实验：`experiments/loop_agent/`*  
*关联引擎：`src/flowgame/`*
