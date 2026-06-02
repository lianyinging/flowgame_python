<p style="text-align: center">
  <a href="https://flowgame.mgdeep.com" target="_blank">
    <img
      src="https://image.cscmgg.com/wechatMiniprogramImages/adminImage/bannerImage/20260601/blstxodlnxg66p.png"
      alt="FlowGame logo"
      width="300"
    />
  </a>
</p>

<p style="text-align: center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="python" /></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-0.100%2B-009688" alt="FastAPI" /></a>
  <a href="#license"><img src="https://img.shields.io/badge/license-MIT-green" alt="license" /></a>
</p>

[简体中文](./README.md) | English

**flowgame_python** is the **Python backend** for the [FlowGame frontend](https://github.com/lianyinging/flowgame). It parses [Tinyflow](https://github.com/tinyflow-ai/tinyflow) workflow JSON, executes node logic, and provides Redis flow storage, Qdrant knowledge bases, and Embedding. The frontend `@flowgame/vue` handles editing; this repo handles **trial runs, external API execution, persistence, and vector search**.

**Execution support for frontend custom nodes**:

| Node type | Description |
|-----------|-------------|
| `node_start_api` | Start API entry — parses HTTP input into chain memory |
| `llmapiNode` | LLM API calls with per-node key, endpoint, and model |
| `knowledgeNodePlus` | Knowledge retrieval+ via Qdrant Collection |
| `memoryWriteNode` / `memoryReadNode` | Memory write / read for cross-turn context |
| `htmlTemplateNode` | HTML template rendering |

Also supports built-in Tinyflow nodes (branches, loops, HTTP, code nodes, etc.).

## Core Capabilities

- **Workflow execution**: sync `POST /execute` and NDJSON streaming `POST /execute/stream`
- **Redis flow storage**: flow list, load/save workflow JSON by `methodKey`
- **Qdrant knowledge base**: collection management, document ingest, vector search (RAG)
- **Pluggable Embedding**: HTTP vector service or local BGE model
- **Standalone deploy**: `python run.py` or Docker Compose (with frontend `deploy/`)

---

## Quick Start

### Requirements

| Dependency | Notes |
|------------|-------|
| Python | **3.10+** |
| Redis | Flow save / list (default `6379`) |
| Qdrant | Vector search (default `6333`) |
| Embedding | Set `EMBEDDING_API_URL`, or use local `model/BAAI/bge-small-zh-v1.5` |

### 1. Install & configure

```bash
git clone https://github.com/lianyinging/flowgame_python.git
cd flowgame_python
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

### 2. Start the server

```bash
python run.py
```

Default: **http://127.0.0.1:8008** (`FLOWGAME_PORT=8008` in `.env`).

Or with uvicorn:

```bash
export PYTHONPATH=.
uvicorn src.flowgame.app:app --host 0.0.0.0 --port 8008 --reload
```

### 3. Verify

| URL | Description |
|-----|-------------|
| http://127.0.0.1:8008/health | Health check |
| http://127.0.0.1:8008/docs | Swagger API docs |
| API prefix | `/api/v1/flowGame` |

---

## Frontend Integration

1. Start this service on port **8008**
2. In [flowgame](https://github.com/lianyinging/flowgame) or your Vue app, proxy `/api` to the backend:

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

3. Call `configureFlowGameClient({ baseURL: '/api' })` on the frontend.

| Service | Default URL |
|---------|-------------|
| Frontend editor | http://127.0.0.1:8009 |
| This API | http://127.0.0.1:8008 |

---

## Main APIs

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/flowGame/execute` | Sync workflow execution |
| POST | `/api/v1/flowGame/execute/stream` | NDJSON streaming execution |
| GET/POST | `/api/v1/flowGame/redis/*` | Redis flow read/write |
| GET/POST | `/api/v1/flowGame/qdrant/*` | Qdrant collections / search |

---

## Environment Variables

See [.env.example](.env.example). Key settings: `FLOWGAME_PORT`, `REDIS_*`, `QDRANT_*`, `EMBEDDING_API_URL`.

**llmapiNode** credentials are configured in workflow JSON node parameters, not typically in `.env`.

---

## Embedding

1. `EMBEDDING_API_URL` — HTTP service
2. Local BGE at `model/BAAI/bge-small-zh-v1.5`
3. Fallback download from HuggingFace

Status: `GET /api/v1/flowGame/qdrant/embedding/status`

---

## Project Structure

```
flowgame_python/
├── src/flowgame/     # FastAPI app, parser, chain nodes, redis, qdrant
├── run.py
├── requirements.txt
├── Dockerfile
└── docs/logo.png
```

| Repo | Role |
|------|------|
| [flowgame](https://github.com/lianyinging/flowgame) | Frontend monorepo |
| **flowgame_python** | This backend |

---

## Docker Deployment

Clone alongside the frontend repo, then from `flowgame/deploy`:

```bash
docker compose up -d --build
```

See frontend **[Docker部署.md](https://github.com/lianyinging/flowgame/blob/master/Docker部署.md)**.

---

## FAQ

| Issue | Fix |
|-------|-----|
| Trial run fails | Ensure backend is up; proxy port matches (**8008**) |
| Save / flow list errors | Start Redis; check `REDIS_*` in `.env` |
| Empty knowledge search | Start Qdrant; verify Embedding and ingested docs |
| Slow Embedding init | Use `EMBEDDING_API_URL` in production |

---

<a id="license"></a>

## License

MIT (see LICENSE in repo root if present).
