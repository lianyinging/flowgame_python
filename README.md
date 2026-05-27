# FlowGame Python（独立后端）

从 `smartAi` 抽离的 FlowGame 工作流执行、Redis 工作流存储、Qdrant 知识库 API。

## 环境要求

- Python 3.10+
- Redis、Qdrant（按需；未启动时部分接口会报错）
- Embedding：配置 `EMBEDDING_API_URL` 使用 HTTP；**未配置时**自动使用项目内 `model/BAAI/bge-small-zh-v1.5`（需 `pip install sentence-transformers`，首次可从 smartAi 复制模型目录）

## 快速启动

```bash
cd /path/to/flowgame_python
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # 按需修改
python run.py
```

或使用 uvicorn：

```bash
export PYTHONPATH=.
uvicorn src.flowgame.app:app --host 0.0.0.0 --port 8001 --reload
```

- 健康检查：<http://127.0.0.1:8001/health>
- API 文档：<http://127.0.0.1:8001/docs>
- 接口前缀：`/api/v1/flowGame`

## 主要接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/flowGame/execute` | 同步执行工作流 |
| POST | `/api/v1/flowGame/execute/stream` | NDJSON 流式执行（试运行进度） |
| GET/POST | `/api/v1/flowGame/redis/*` | 工作流 Redis 读写 |
| GET/POST | `/api/v1/flowGame/qdrant/*` | 知识库 Collection / 检索 |

## Embedding（向量）

优先级：

1. **`EMBEDDING_API_URL`** — HTTP 服务（POST `{"texts":["..."]}`）
2. **本地 BGE** — `model/BAAI/bge-small-zh-v1.5`（默认路径，可用 `EMBEDDING_MODEL_PATH` 覆盖）
3. 若本地不存在，回退从 HuggingFace 下载 `BAAI/bge-small-zh-v1.5`

复制模型（与原 smartAi 一致）：

```bash
mkdir -p model/BAAI
rsync -a /path/to/smartAi/model/BAAI/bge-small-zh-v1.5/ model/BAAI/bge-small-zh-v1.5/
```

状态接口：`GET /api/v1/flowGame/qdrant/embedding/status`

## 与前端联调

独立前端 `flowgame` 的 Vite 已将 `/api` 代理到 `http://127.0.0.1:8001`，先启动本服务再 `pnpm dev` 即可。
