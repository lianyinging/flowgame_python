<p align="center">
  <a href="https://flowgame.mgdeep.com" target="_blank">
    <img
      src="https://image.cscmgg.com/wechatMiniprogramImages/adminImage/bannerImage/20260601/blstxodlnxg66p.png"
      alt="FlowGame logo"
      width="300"
    />
  </a>
</p>

<p align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="python" /></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-0.100%2B-009688" alt="FastAPI" /></a>
  <a href="#许可"><img src="https://img.shields.io/badge/license-Apache--2.0-blue" alt="license" /></a>
</p>

简体中文 | [English](./README.en-US.md)

**flowgame_python** 是 [FlowGame 前端](https://github.com/lianyinging/flowgame) 的配套 **Python 后端**：解析 [Tinyflow](https://github.com/tinyflow-ai/tinyflow) 工作流 JSON，执行画布上的节点逻辑，并提供 Redis 流程存储、Qdrant 知识库与 Embedding 能力。前端 `@flowgame/vue` 负责编排与展示，本仓库负责**试运行、对外 API 执行、持久化与向量检索**。

**与前端新增节点对应的执行支持**：

| 节点 type | 说明 |
|-----------|------|
| `node_start_api` | Start API 入口，解析 HTTP 入参并写入链路 memory |
| `llmapiNode` | 模型调用，按节点配置的 API Key / 接口 / 模型请求大模型 |
| `knowledgeNodePlus` | 知识库检索+，对接 Qdrant Collection |
| `memoryWriteNode` / `memoryReadNode` | 记忆写入 / 读取，跨节点会话上下文 |
| `htmlTemplateNode` | HTML 模板渲染输出 |
| `ossNode` | 对象存储上传（content + fileType：image/html/txt/json 等） |

同时兼容 Tinyflow 内置节点（条件分支、循环、HTTP、代码节点等）。

## 核心能力

- **工作流执行**：同步 `POST /execute` 与 NDJSON 流式 `POST /execute/stream`（编辑器试运行进度）
- **Redis 流程存储**：流程列表、按 `methodKey` 加载与保存工作流 JSON
- **Qdrant 知识库**：Collection 管理、文档入库、向量检索（RAG）
- **Embedding 可插拔**：HTTP 向量服务或本地 BGE 模型
- **独立部署**：本地 `python run.py`、Docker Compose（与前端仓库 `deploy/` 联动）

---

## 快速开始

### 环境要求

| 依赖 | 说明 |
|------|------|
| Python | **3.10+** |
| Redis | 流程保存 / 列表（默认 `6379`） |
| Qdrant | 知识库向量检索（默认 `6333`） |
| Embedding | 配置 `EMBEDDING_API_URL`，或使用本地 `model/BAAI/bge-small-zh-v1.5` |

### 1. 安装与配置

```bash
git clone https://github.com/lianyinging/flowgame_python.git
cd flowgame_python
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # 生产/默认环境
cp .env.dev.example .env.dev       # 可选：开发/测试环境
```

### 2. 启动服务

```bash
# 生产/默认（加载 .env）
python run.py

# 开发/测试（加载 .env.dev，默认端口 8009）
APP_ENV=dev python run.py
```

默认监听 **http://127.0.0.1:8008**（由 `.env` 中 `FLOWGAME_PORT=8008` 控制）；`APP_ENV=dev` 时加载 `.env.dev`。

或使用 uvicorn：

```bash
export PYTHONPATH=.
uvicorn src.flowgame.app:app --host 0.0.0.0 --port 8008 --reload
```

### 3. 验证

| 地址 | 说明 |
|------|------|
| http://127.0.0.1:8008/health | 健康检查 |
| http://127.0.0.1:8008/docs | Swagger API 文档 |
| 接口前缀 | `/api/v1/flowGame` |

---

## 与前端联调

1. 启动本服务（端口 **8008**）
2. 在前端 [flowgame](https://github.com/lianyinging/flowgame) 或自有 Vue 项目中，Vite 将 `/api` 代理到后端：

```typescript
// vite.config.ts
import { defineConfig } from 'vite'

export default defineConfig({
  server: {
    proxy: {
      '/api': { target: 'http://127.0.0.1:8008', changeOrigin: true },
    },
  },
})
```

3. 前端 `configureFlowGameClient({ baseURL: '/api' })` 后即可保存流程、试运行、管理知识库。

| 服务 | 默认地址 |
|------|----------|
| 前端编辑器 | http://127.0.0.1:8009 |
| 本后端 API | http://127.0.0.1:8008 |

---

## 主要接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/flowGame/execute` | 同步执行工作流 |
| POST | `/api/v1/flowGame/execute/stream` | NDJSON 流式执行（试运行进度） |
| GET/POST | `/api/v1/flowGame/redis/*` | 工作流 Redis 读写、流程列表 |
| GET/POST | `/api/v1/flowGame/qdrant/*` | 知识库 Collection / 文档 / 检索 |

**外部调用示例**（按 `methodKey` 执行已保存流程）：

```http
POST /api/v1/flowGame/execute
Content-Type: application/json

{
  "methodKey": "my_flow",
  "variables": { "question": "你好" }
}
```

**管理端调试**（直接传画布 JSON）：

```json
{
  "workflow": { "nodes": [], "edges": [] },
  "variables": {}
}
```

---

## 环境变量

见 [.env.example](.env.example)（生产）与 [.env.dev.example](.env.dev.example)（开发/测试），常用项：

| 变量 | 默认 | 说明 |
|------|------|------|
| `FLOWGAME_HOST` | `0.0.0.0` | 监听地址 |
| `FLOWGAME_PORT` | `8008` | 服务端口 |
| `REDIS_HOST` / `REDIS_PORT` | `127.0.0.1` / `6379` | 流程存储 |
| `FLOWGAME_REDIS_KEY_PREFIX` | （空，默认 `flow_game:`） | 多项目共用 Redis 时的键命名空间 |
| `FLOWGAME_QDRANT_KB_PREFIX` | （空，默认 `flowgame_`） | 多项目共用 Qdrant 时的 Collection 前缀 |
| `QDRANT_HOST` / `QDRANT_PORT` | `127.0.0.1` / `6333` | 向量库 |
| `EMBEDDING_API_URL` | 空 | 外部 Embedding HTTP 服务 |
| `DEEPSEEK_*` | — | 可选；历史 Tinyflow `llmNode` 服务端环境变量 |

> **模型调用（llmapiNode）** 的 API Key、接口地址、模型名在**流程 JSON 节点参数**中配置，一般无需在 `.env` 填写 Key。

---

## Embedding（向量）

优先级：

1. **`EMBEDDING_API_URL`** — HTTP 服务（POST `{"texts":["..."]}`，返回向量数组）
2. **本地 BGE** — `model/BAAI/bge-small-zh-v1.5`（可用 `EMBEDDING_MODEL_PATH` 覆盖）
3. 本地不存在时，从 HuggingFace 下载 `BAAI/bge-small-zh-v1.5`

复制已有模型目录：

```bash
mkdir -p model/BAAI
rsync -a /path/to/existing/bge-small-zh-v1.5/ model/BAAI/bge-small-zh-v1.5/
```

状态接口：`GET /api/v1/flowGame/qdrant/embedding/status`

---

## 项目结构

```
flowgame_python/
├── src/flowgame/
│   ├── app.py              # FastAPI 入口
│   ├── router.py           # 执行 / 流式接口
│   ├── service.py          # 工作流执行编排
│   ├── parser/             # Tinyflow JSON → 执行链
│   ├── chain/              # 节点运行时（LLM、知识库、记忆等）
│   ├── redis/              # 流程 Redis API
│   ├── qdrant/             # 知识库与 Embedding
│   └── memory_context.py   # 记忆读写上下文
├── run.py                  # 推荐启动脚本
├── requirements.txt
├── Dockerfile              # 生产镜像（APP_ENV=prod，加载 .env）
├── Dockerfile_test         # 测试镜像（APP_ENV=dev，加载 .env.dev）
├── logo.png
├── .env.example
└── .env.dev.example
```

**相关仓库**

| 仓库 | 说明 |
|------|------|
| [flowgame](https://github.com/lianyinging/flowgame) | 前端 Monorepo（`@flowgame/core`、`@flowgame/vue`） |
| **flowgame_python**（本仓库） | Python 执行器与数据 API |

---

## Docker 部署

**单独构建本仓库镜像：**

```bash
# 生产（镜像内默认使用 .env.example；敏感项请在阿里云运行时环境变量覆盖）
docker build -f Dockerfile -t flowgame .
docker run -p 8008:8008 flowgame

# 测试（镜像内默认使用 .env.dev.example；敏感项请在运行时环境变量覆盖）
docker build -f Dockerfile_test -t flowgame-test .
docker run -p 8009:8009 flowgame-test
```

与前端 **并列克隆** 后，在前端仓库执行：

```bash
# 父目录示例
/opt/flowgame/
├── flowgame/
└── flowgame_python/

cd flowgame/deploy
cp .env.example .env
docker compose up -d --build
```

浏览器访问 **http://\<服务器IP\>:8009**，Nginx 将 `/api` 转发到本服务。详细步骤见前端仓库 **[Docker部署.md](https://github.com/lianyinging/flowgame/blob/master/Docker部署.md)**。

---

## 常见问题

| 现象 | 处理 |
|------|------|
| 前端试运行失败 | 确认本服务已启动，端口与 Vite 代理一致（默认 **8008**） |
| 保存 / 流程列表报错 | 启动 Redis，检查 `.env` 中 `REDIS_*` |
| 知识库检索无结果 | 启动 Qdrant；确认 Collection 已入库且 Embedding 可用 |
| Embedding 初始化慢 | 生产环境建议配置 `EMBEDDING_API_URL`，避免容器内下载大模型 |
| 端口不一致 | 统一使用 `FLOWGAME_PORT=8008`，与前端代理、Docker Compose 保持一致 |

---

<a id="许可"></a>

## 许可

Apache License 2.0（详见仓库根目录 [LICENSE](LICENSE)）。
