# Ask AI

CamThink AI 知识助手 — 自建 RAG 系统。

## 快速开始

1. 复制 `.env.example` 为 `.env`,填入 API Key
2. 启动服务:`docker compose -f deploy/dev/docker-compose.yml up -d postgres weaviate`
3. 同步知识库:`python scripts/sync.py`
4. 启动后端:`python -m backend.main`
5. 构建并测试 Widget:`cd widget && npm install && npm run build`
