# Ask AI

CamThink AI 知识助手 — 自建 RAG 系统。对 CamThink 产品(NE101/301/503 相机、NeoMind、AIToolStack)、WooCommerce 商城、支持知识库做检索增强问答。3 类意图:`commercial` / `product` / `support`(+ `off_topic`,售前并入产品)。

## Quick Reference

```bash
# 依赖(Python)
uv sync --extra dev

# 启动依赖服务(dev)
docker compose -f deploy/docker-compose.yml up -d postgres weaviate

# 启动后端
uv run python -m backend.main            # http://localhost:8000

# 数据源同步(cron 入口)
uv run python scripts/sync.py             # 同步全部 enabled 源(增量优先)
uv run python scripts/sync.py --source github-ne301   # 仅单源
uv run python scripts/sync.py --dry-run   # 只列举,不灌库
uv run python scripts/sync.py --reindex    # ⚠️ 删整个 collection 后全量重灌,见下方约束

# Admin 前端(http://localhost:5174)
cd admin && npm install && npm run dev
cd admin && npm run build                 # 产物到 admin/dist(被打进 Docker 镜像)

# Widget 前端(http://localhost:5173)
cd widget && npm install && npm run dev
cd widget && npm run build

# 测试
uv run pytest tests/ -q                   # 后端(详见 Testing 节)
cd admin && npm run test                  # admin 单元(vitest)
cd widget && npm run test                 # widget 单元(vitest)

# Lint / Format
ruff check . && ruff format --check .     # lint + 格式
black --check . && isort --check .        # 格式(line-length=100)

# 创建 admin 用户
uv run python scripts/create_admin_user.py
```

## Project Structure

```
ask-ai/
├── backend/                    # Python 3.12 FastAPI RAG 后端
│   ├── main.py                 # App 入口 + lifespan(接线全栈组件)
│   ├── config.py               # Settings(immutable dataclass)+ YAML ${VAR} 展开
│   ├── api/
│   │   ├── routes.py           # /api/ask(SSE) /api/feedback /api/click /api/upload
│   │   ├── schemas.py           # Pydantic 请求模型
│   │   └── admin/              # 管理后台 REST API(11 个子模块)
│   ├── pipeline/               # RAG 管线
│   │   ├── rag.py              # RAGOrchestrator(编排 intent→rewrite→search→rerank→generate)
│   │   ├── intent.py            # 意图分类(commercial/product/support/off_topic)
│   │   ├── query_rewrite.py    # 查询改写
│   │   ├── chunk.py / chunk_code.py  # 文本分块 / tree-sitter AST 代码分块
│   │   ├── ingest.py           # IngestionPipeline(fetch→chunk→embed→写 Weaviate+Postgres)
│   │   └── pruner.py           # LLM 上下文裁剪(可选,按 routing 启用)
│   ├── connectors/             # 数据源连接器(插件式,@ConnectorRegistry.register)
│   │   ├── github.py           # git clone+fetch+reset,API SHA 感知
│   │   ├── local_git.py        # 本地 git 仓库增量
│   │   ├── filesystem.py       # 本地文件系统(必须 mac 同步)
│   │   ├── woocommerce.py      # WooCommerce REST API v3(camthink.ai 商城)
│   │   ├── registry.py         # SourceConfig + ConnectorRegistry
│   │   └── exclusion.py        # exclude 黑名单策略
│   ├── retrieval/              # 检索
│   │   ├── search.py           # HybridSearcher(BM25 + 向量)
│   │   ├── rerank.py           # RerankPipeline(bge-reranker-v2-m3)
│   │   └── rrf.py              # Reciprocal Rank Fusion(降级可选)
│   ├── embedder/bge.py         # BGE-m3 embedder + reranker
│   ├── llm/                    # LLM provider 插件(@LLMRegistry.register)+ LLMRouter
│   ├── auth/                   # JWT + crypto(API key AES 加解密)+ dependencies
│   ├── db/                     # SQLAlchemy models + async session
│   ├── services/               # config_loader / clustering / override_matcher / intent_tagger / attachments
│   └── utils/                  # budget(熔断)/ language / pii(脱敏)
├── admin/                      # React 19 + TS 管理后台 SPA(Vite + Tailwind + shadcn/Radix)
│   └── src/{pages,components,hooks,lib}/
├── widget/                     # React 19 + TS 可嵌入聊天组件(Vite)
│   └── src/{components,hooks,utils}/
├── config/                     # YAML 配置(${VAR} 自动展开环境变量)
│   ├── system_prompt.yaml      # system prompt + intent_styles
│   ├── data_sources.yaml       # 数据源定义(首次启动 seed 到 DB)
│   └── llm_providers.yaml      # LLM 供应商 + routing(首次启动 seed 到 DB)
├── scripts/
│   ├── sync.py                 # 数据源同步 cron 入口
│   ├── create_admin_user.py
│   ├── migrate_*.py             # 迁移脚本(yaml_to_db / intent_tag / symbol_props 等)
│   └── e2e_*.py                 # 端到端测试(20q / intent / real_review)
├── tests/                      # pytest(与 backend/ 镜像目录结构)
├── deploy/
│   ├── docker-compose.yml      # dev(postgres + weaviate + backend)
│   └── tesla-t4/               # 生产 GPU 全栈(backend + sync worker + sync-cron)
├── docs/superpowers/{specs,plans,handoff}/  # 设计文档 / 实施计划 / 交接
├── models/                     # BGE-m3 + reranker 权重(gitignore,挂载不打进镜像)
├── Dockerfile                  # 多阶段 GPU 镜像(CUDA 12.8 / cu128 torch)
├── pyproject.toml              # Python 3.12 / black:100 / ruff:py312
└── uv.lock
```

## Architecture

### 数据流(同步)
`scripts/sync.py`(cron)→ 从 Postgres `data_sources` 表读 enabled 配置 → `ConnectorRegistry.create(cfg)` → `fetch_changes`(增量,24h 窗口)/ `fetch_all`(首次)→ `IngestionPipeline.ingest_all`(chunk + embed)→ 写 Weaviate collection + Postgres `documents` 表 → `fetch_deleted` → 删除 → 写 `SyncLog`。

> Connector 与 IngestionPipeline 是同步实现(Weaviate v4 SDK 同步),在 async `run_sync` 中阻塞式调用。cron 任务无并发需求,但**不应**放入 web 请求路径。

### 数据流(问答)
`POST /api/ask` → `mask_pii` → `BudgetLimiter.check_and_reserve`(预扣 token)→ 附件归属校验 → `RAGOrchestrator.stream_answer`(intent → query_rewrite → hybrid search → rerank → LLM 流式生成)→ SSE 事件序列 `sources → token(s) → done` → 写 Postgres `conversations` 表。

### 组件接线(lifespan)
`backend/main.py` 的 `lifespan` 启动时按序接线:Postgres(init_db + seed admin/customization/LLM config)→ Weaviate → BGEEmbedder/BGEReranker → LLMRouter(DB 优先,YAML 兜底)→ HybridSearcher → RerankPipeline → Pruner(可选)→ OverrideMatcher → RAGOrchestrator → ClusteringService → BudgetLimiter → GITHUB_TOKEN 校验。关闭时每步独立 guard 释放。

### LLM 配置(双源)
LLM 供应商 + routing 优先从 Postgres DB 读取(`LLMProviderModel` / `LLMRouting` 表,API key AES 加密存),DB 为空时回退 `config/llm_providers.yaml`。首次启动 YAML 配置 seed 到 DB。管理界面 `admin/LLMProviders.tsx` 维护。

### 管理后台
`backend/api/admin/` 提供 11 个 REST 子模块(auth/customizations/users/answer_overrides/llm_providers/data_sources/sync_logs/analytics/conversations/attachments)。`admin/dist` 构建产物被打进 Docker 镜像,由 `main.py` 的 `SPAStaticFiles` 在 `/admin` 路径托管(深链回退 index.html)。

## Configuration

- **环境变量**:`.env`(从 `.env.example` 复制)。`backend/config.py` 的 `load_settings()` 读取。
- **YAML**:`config/*.yaml`,加载时 `_expand_env` 递归展开 `${VAR}` 占位符。
- **prod 安全校验**:`APP_MODE=prod` 时 `_validate_prod_secrets` 强制 `ENCRYPTION_KEY` ≥32 字节且 `JWT_SECRET` 非默认值,否则启动失败。
- **数据源配置**:持久化在 Postgres `data_sources` 表(管理界面维护),`config/data_sources.yaml` 仅作首次 seed 参考。

## Development Setup

1. 复制 `.env.example` → `.env`,填入 `DEEPSEEK_API_KEY`、`GITHUB_TOKEN` 等
2. `uv sync --extra dev` 装 Python 依赖
3. `docker compose -f deploy/docker-compose.yml up -d postgres weaviate` 起依赖服务
4. `uv run python scripts/sync.py` 首次同步知识库(需先在 mac 本地备好 filesystem 源的 Knowledge 仓库)
5. `uv run python -m backend.main` 启动后端(:8000)
6. `cd admin && npm install && npm run dev`(:5174)/ `cd widget && npm install && npm run dev`(:5173)

## Testing

```bash
# 后端全量(需先起 postgres,且必设 TEST_DATABASE_URL,见下方约束)
TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test \
  uv run pytest tests/ -q

# 按标记
uv run pytest -m unit          # 仅单元
uv run pytest -m integration   # 集成(需外部服务)
uv run pytest -m slow          # 慢速

# 覆盖率
uv run pytest --cov=backend --cov-report=term-missing

# 前端
cd admin && npm run test
cd widget && npm run test

# E2E
uv run python scripts/e2e_20q.py
uv run python scripts/e2e_intent_en.py
```

CI(`.github/workflows/build-image.yml`)跑:test → build widget+admin → build GPU 镜像 → push GHCR(`ghcr.io/harryhua-ai/ask-ai:<tag>`)。CI 跳过 `tests/api/admin`、`tests/scripts/test_sync_db.py`、`tests/embedder`、`tests/e2e`(依赖运行时 seed / HF 模型 / 活服务)。

## Deployment

- **dev**:`deploy/docker-compose.yml`(postgres + weaviate + backend)
- **prod**:`deploy/tesla-t4/` — 全栈 GPU(backend uvicorn + sync worker + sync-cron 每小时增量)。同一镜像,compose 用 command 覆盖区分 backend/sync。corpus 与 models 挂载(不打进镜像)。更新:`docker compose pull && docker compose up -d`(`deploy/tesla-t4/update.sh`)。
- **GPU 约束**:CUDA 12.8 / cu128 torch(tesla-t4 driver 575 / CUDA 12.9 兼容)。`EMBEDDER_BATCH_SIZE=16`(GPU 共享生产服务约束)。

## Critical Constraints(踩坑必读)

- **⚠️ `--reindex` 删整个 collection**:`scripts/sync.py --reindex` 删除**全部** Weaviate collection 后只重灌当前数据源,非单源增量。曾误删 560k chunk。单源增量**绝不用** `--reindex`。仅 schema 变更 / 符号字段回填时手动触发(期间服务不可用)。
- **⚠️ 测试库隔离**:必设 `TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test`。`tests/conftest.py` 的 `drop_all` 在未隔离时会清空开发库。CI 已对齐 `ask_ai_test`。
- **filesystem 源必须在 mac 同步**:Knowledge 仓库在 mac 本地;tesla-t4 reindex 漏灌 filesystem → support 案例缺失导致拒答。mac 跑同步后 tesla-t4 才有完整向量。
- **prod 密钥**:`APP_MODE=prod` 必须显式设 `ENCRYPTION_KEY`(≥32 字节,API key 加解密)与 `JWT_SECRET`(非默认值),否则启动失败。
- **API key 加解密兼容**:DB 中 api_key 用 AES 加密;`ENCRYPTION_KEY` 轮换前旧数据可能是明文,`_build_llm_state` 解密失败时按明文兼容继续(仅 warn,不中断)。
- **同步/异步边界**:Connector 与 IngestionPipeline 是同步实现,仅 `init_db` / `session_factory()` / `engine.dispose()` 用 async。见 `scripts/sync.py` 模块 docstring。

## Conventions

- **语言**:对话、回复、代码注释用中文简体(规则要求)。docstring 用中文。
- **不可变**:`Settings` 用 `@dataclass(frozen=True)`;前端用 spread 不可变更新。
- **插件注册**:Connector / LLM provider 用 `@Registry.register` 装饰器,`main.py` / `sync.py` 显式 `import` 触发注册。
- **错误隔离**:单数据源同步失败不中断批次(写 SyncLog status=failed);SSE 流式生成中途异常降级返回友好提示。
- **格式**:Python `black` + `isort` + `ruff`,line-length=100,target=py312。前端 Prettier + tsc。
- **文档**:设计文档入 `docs/superpowers/specs/`,实施计划入 `docs/superpowers/plans/`,交接入 `docs/superpowers/handoff/`。
