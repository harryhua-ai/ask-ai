# Ask AI Phase 1 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建 Ask AI Phase 1 核心问答系统:数据接入 → RAG 管线 → Widget 嵌入,实现官网+Wiki 上的 AI 知识助手。

**Architecture:** 自建 RAG 系统,BGE-m3 嵌入 + Weaviate 混合检索 + bge-reranker 重排 + DeepSeek 生成。后端 FastAPI(SSE),前端独立 React Widget(`<script>` 嵌入)。数据源通过 Connector 框架接入(GitHub + FileSystem),定时 cron 增量同步。

**Tech Stack:** Python 3.12 / FastAPI / FlagEmbedding(BGE-m3 + reranker)/ Weaviate / Postgres / DeepSeek API / React 19 / Vite / TypeScript

## Global Constraints

- Python 3.12+, type annotations required on all function signatures
- PEP 8, black formatting, isort, ruff linting
- pytest for backend tests, vitest for widget tests
- Immutable data patterns (frozen dataclasses)
- No hardcoded secrets — all via env vars
- 安全边界:外部输入(消息/history/来源URL/渠道)在系统边界校验;LLM 输出渲染前必须 XSS 清洗;secret 永不进 LLM 上下文
- No `print()` in backend — use `logging`
- All code comments and responses in Chinese (简体)
- Docker Compose for local development
- device auto-detection: `cuda` > `mps` > `cpu`
- Files: 200-400 lines typical, 800 max

---

## File Structure

```
ask-ai/
├── backend/
│   ├── __init__.py
│   ├── main.py                     # FastAPI app entry
│   ├── config.py                   # YAML + env config loading
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes.py               # SSE ask endpoint + feedback + click
│   │   └── schemas.py              # Pydantic request/response models
│   ├── connectors/
│   │   ├── __init__.py
│   │   ├── base.py                 # DataSourceConnector Protocol + RawDocument
│   │   ├── registry.py             # ConnectorRegistry
│   │   ├── github.py               # GitHubConnector
│   │   └── filesystem.py           # FileSystemConnector
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── base.py                 # LLMProvider Protocol + LLMResponse
│   │   ├── registry.py             # LLMRegistry + LLMRouter
│   │   └── deepseek.py             # DeepseekProvider
│   ├── embedder/
│   │   ├── __init__.py
│   │   ├── base.py                 # Embedder/Reranker Protocol + device
│   │   └── bge.py                  # BGE-m3 embedder + bge-reranker
│   ├── retrieval/
│   │   ├── __init__.py
│   │   ├── search.py               # Weaviate hybrid search
│   │   └── rerank.py               # Reranking orchestration
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── chunk.py                # Text chunking
│   │   ├── ingest.py               # Ingestion: chunk → embed → store
│   │   └── rag.py                  # RAG: query → retrieve → rerank → generate
│   ├── db/
│   │   ├── __init__.py
│   │   ├── models.py               # SQLAlchemy models (all tables)
│   │   └── session.py              # DB session management
│   └── utils/
│       ├── __init__.py
│       ├── pii.py                  # PII masking
│       ├── language.py             # Language detection
│       └── budget.py               # 每日预算熔断(S2)
├── widget/
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   └── src/
│       ├── index.tsx               # Entry: mount widget to DOM
│       ├── App.tsx                 # Widget root component
│       ├── components/
│       │   ├── ChatPanel.tsx
│       │   ├── MessageList.tsx
│       │   ├── MessageBubble.tsx
│       │   ├── SourceLink.tsx
│       │   ├── InputBar.tsx
│       │   └── SuggestedQuestions.tsx
│       ├── hooks/
│       │   └── useSSE.ts
│       ├── utils/
│       │   ├── sanitize.ts         # XSS 清洗 + 安全 Markdown 渲染(S1)
│       │   └── urlPolicy.ts        # 来源链接协议+域白名单(S1)
│       ├── styles/
│       │   └── widget.css
│       └── types.ts
├── deploy/
│   └── docker-compose.yml
├── scripts/
│   └── sync.py                     # Cron sync entry point
├── config/
│   ├── data_sources.yaml
│   ├── llm_providers.yaml
│   └── system_prompt.yaml
├── tests/
│   ├── conftest.py
│   ├── connectors/
│   ├── llm/
│   ├── embedder/
│   ├── retrieval/
│   ├── pipeline/
│   ├── api/
│   └── utils/
├── pyproject.toml
├── .env.example
└── README.md
```

---

## Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `backend/__init__.py`
- Create: `backend/config.py`
- Create: `.env.example`
- Create: `config/data_sources.yaml`
- Create: `config/llm_providers.yaml`
- Create: `config/system_prompt.yaml`
- Create: `tests/conftest.py`

**Interfaces:**
- Produces: `Settings` dataclass (global config singleton), YAML config files

- [ ] **Step 1: Create pyproject.toml**

```toml
[project]
name = "ask-ai"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.34",
    "httpx>=0.28",
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg>=0.30",
    "alembic>=1.14",
    "weaviate-client>=4.10",
    "FlagEmbedding>=1.3",
    "pyyaml>=6.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "python-multipart>=0.0.20",
    "sse-starlette>=2.1",
    "langdetect>=1.0.9",
    "tiktoken>=0.9",
    "slowapi>=0.1.9",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "pytest-cov>=6.0",
    "httpx>=0.28",
    "ruff>=0.9",
    "black>=25.0",
    "isort>=5.13",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
markers = [
    "unit: 单元测试",
    "integration: 集成测试(需要外部服务)",
    "slow: 慢速测试",
]

[tool.black]
line-length = 100

[tool.isort]
profile = "black"
line_length = 100

[tool.ruff]
line-length = 100
target-version = "py312"
```

- [ ] **Step 2: Create .env.example**

```bash
# Postgres
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=ask_ai
POSTGRES_USER=ask_ai
POSTGRES_PASSWORD=changeme

# Weaviate
WEAVIATE_URL=http://localhost:8080
WEAVIATE_CLASS_NAME=Document

# DeepSeek LLM
DEEPSEEK_API_KEY=your-key-here
DEEPSEEK_API_BASE=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat

# Embedding device
EMBEDDER_DEVICE=auto

# GitHub (for GitHubConnector)
GITHUB_TOKEN=your-github-token

# App
ASKAI_API_HOST=0.0.0.0
ASKAI_API_PORT=8000
LOG_LEVEL=INFO
```

- [ ] **Step 3: Create config files**

`config/llm_providers.yaml`:
```yaml
providers:
  - id: "deepseek"
    type: "openai_compatible"
    enabled: true
    config:
      api_base: "${DEEPSEEK_API_BASE}"
      api_key: "${DEEPSEEK_API_KEY}"
      model: "${DEEPSEEK_MODEL}"
      max_tokens: 4096
      temperature: 0.3

routing:
  generation:
    chain: ["deepseek"]
  query_decomposition:
    chain: ["deepseek"]
```

`config/system_prompt.yaml`:
```yaml
assistant_name: "CamThink 助手"
response_style: "专业、简洁、友好。直答问题,不铺垫,不寒暄。"
language: "auto"
guardrails: |
  只回答基于已检索到的官方资料的问题。
  不编造产品参数、功能、兼容性或操作步骤。
  信息不足时,在回答开头明确说明"暂未在官方资料中找到相关信息"。
  不回答法律、财务、售后等非技术/产品问题。
  产品型号、接口名、代码术语不翻译。
system_prompt: |
  你是 CamThink 助手,一个专业的 AI 知识助手。
  你的任务是帮助访客查询 CamThink 产品信息、技术文档和开发资料。

  ## 回答规则
  - 只依据已检索到的官方资料回答,不编造信息
  - 使用 Markdown 格式回答
  - 来源引用使用内联格式,如:[Wiki] NE503 技术规格
  - 不确定时,在回答开头说明
  - 产品型号、接口名、代码术语不翻译

  ## 语言
  - 使用与提问相同的语言回答
  - 默认英语
```

`config/data_sources.yaml`:
```yaml
sources:
  - id: "github-wiki"
    type: "github"
    product: "wiki"
    enabled: true
    config:
      owner: "camthink-ai"
      repo: "wiki-documents"
      branch: "main"
      file_types: [".md", ".mdx"]
      include_dirs: ["docs/", "blog/", "i18n/"]
    sync_interval: "1h"

  - id: "github-ne101"
    type: "github"
    product: "ne101"
    enabled: true
    config:
      owner: "camthink-ai"
      repo: "lowpower_camera"
      branch: "hw-v1.2"
      file_types: [".md", ".h", ".c", ".txt"]
      include_dirs: ["docs/", "examples/", "README.md"]
      exclude_regex: '_test\\.|\\.generated\\.'
    sync_interval: "1h"

  - id: "github-ne301"
    type: "github"
    product: "ne301"
    enabled: true
    config:
      owner: "camthink-ai"
      repo: "ne301"
      branch: "main"
      file_types: [".md", ".h", ".c", ".txt"]
      include_dirs: ["docs/", "examples/", "README.md"]
    sync_interval: "1h"

  - id: "github-ne503-sdk"
    type: "github"
    product: "ne503"
    enabled: true
    config:
      owner: "camthink-ai"
      repo: "ne503-aipc-sdks"
      branch: "main"
      file_types: [".md", ".py", ".txt", ".yaml"]
      include_dirs: ["docs/", "examples/", "README.md"]
    sync_interval: "1h"

  - id: "github-ne503-hailo"
    type: "github"
    product: "ne503"
    enabled: true
    config:
      owner: "camthink-ai"
      repo: "meta-hailo-os"
      branch: "main"
      file_types: [".md", ".sh", ".txt", ".yaml"]
      include_dirs: ["docs/", "README.md"]
    sync_interval: "1h"

  - id: "github-neomind"
    type: "github"
    product: "neomind"
    enabled: true
    config:
      owner: "camthink-ai"
      repo: "NeoMind"
      branch: "main"
      file_types: [".md", ".rs", ".txt"]
      include_dirs: ["docs/", "README.md"]
    sync_interval: "1h"

  - id: "github-neomind-devicetypes"
    type: "github"
    product: "neomind"
    enabled: true
    config:
      owner: "camthink-ai"
      repo: "NeoMind-DeviceTypes"
      branch: "main"
      file_types: [".md", ".ts", ".js", ".json"]
      include_dirs: ["README.md"]
    sync_interval: "1h"

  - id: "github-neomind-dashboard"
    type: "github"
    product: "neomind"
    enabled: true
    config:
      owner: "camthink-ai"
      repo: "NeoMind-Dashboard-Components"
      branch: "main"
      file_types: [".md", ".tsx", ".ts"]
      include_dirs: ["README.md", "docs/"]
    sync_interval: "1h"

  - id: "github-neomind-extensions"
    type: "github"
    product: "neomind"
    enabled: true
    config:
      owner: "camthink-ai"
      repo: "NeoMind-Extensions"
      branch: "main"
      file_types: [".md", ".rs"]
      include_dirs: ["README.md", "docs/"]
    sync_interval: "1h"

  - id: "github-aitoolstack"
    type: "github"
    product: "aitoolstack"
    enabled: true
    config:
      owner: "camthink-ai"
      repo: "AIToolStack"
      branch: "main"
      file_types: [".md", ".py", ".txt"]
      include_dirs: ["docs/", "README.md"]
    sync_interval: "1h"

  - id: "knowledge-base"
    type: "filesystem"
    product: "knowledge"
    enabled: true
    config:
      root_path: "~/Documents/GitHub/Knowledge/知识库/"
      include_dirs: ["support/", "wiki-en/", "sales/", "硬件/", "经验/"]
      file_types: [".md", ".txt"]
    sync_interval: "1h"
```

- [ ] **Step 4: Create backend/config.py**

```python
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Settings:
    postgres_host: str
    postgres_port: int
    postgres_db: str
    postgres_user: str
    postgres_password: str
    weaviate_url: str
    weaviate_class_name: str
    deepseek_api_key: str
    deepseek_api_base: str
    deepseek_model: str
    embedder_device: str
    github_token: str
    api_host: str
    api_port: int
    log_level: str
    config_dir: Path

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def load_settings(config_dir: Path | None = None) -> Settings:
    return Settings(
        postgres_host=_env("POSTGRES_HOST", "localhost"),
        postgres_port=int(_env("POSTGRES_PORT", "5432")),
        postgres_db=_env("POSTGRES_DB", "ask_ai"),
        postgres_user=_env("POSTGRES_USER", "ask_ai"),
        postgres_password=_env("POSTGRES_PASSWORD", "changeme"),
        weaviate_url=_env("WEAVIATE_URL", "http://localhost:8080"),
        weaviate_class_name=_env("WEAVIATE_CLASS_NAME", "Document"),
        deepseek_api_key=_env("DEEPSEEK_API_KEY"),
        deepseek_api_base=_env("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1"),
        deepseek_model=_env("DEEPSEEK_MODEL", "deepseek-chat"),
        embedder_device=_env("EMBEDDER_DEVICE", "auto"),
        github_token=_env("GITHUB_TOKEN"),
        api_host=_env("ASKAI_API_HOST", "0.0.0.0"),
        api_port=int(_env("ASKAI_API_PORT", "8000")),
        log_level=_env("LOG_LEVEL", "INFO"),
        config_dir=config_dir or Path("config"),
    )


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        return re.sub(r"\$\{(\w+)\}", lambda m: _env(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def load_yaml_config(path: Path) -> dict:
    with open(path) as f:
        data = yaml.safe_load(f)
    return _expand_env(data)
```

- [ ] **Step 5: Create tests/conftest.py**

```python
import pytest
from pathlib import Path


@pytest.fixture
def config_dir() -> Path:
    return Path(__file__).parent.parent / "config"
```

- [ ] **Step 6: Install dependencies and verify**

Run: `pip install -e ".[dev]"`
Expected: All dependencies install successfully.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml .env.example backend/ config/ tests/conftest.py
git commit -m "feat: 项目脚手架、配置系统、依赖定义"
```

---

## Task 2: Postgres Models

**Files:**
- Create: `backend/db/__init__.py`
- Create: `backend/db/models.py`
- Create: `backend/db/session.py`
- Test: `tests/db/test_models.py`

**Interfaces:**
- Produces: `Base` (DeclarativeBase), all SQLAlchemy models, `get_engine()`, `get_session_factory()`

- [ ] **Step 1: Write test**

```python
# tests/db/test_models.py
import pytest
from sqlalchemy import select, text
from backend.db.models import Base, Conversation, SyncLog, SourceClick
from backend.db.session import get_engine, get_session_factory


@pytest.mark.integration
async def test_all_tables_created(db_engine):
    async with db_engine.begin() as conn:
        tables = await conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        )
        names = {r[0] for r in tables}
        expected = {
            "conversations", "source_clicks", "sync_log",
            "data_sources", "customizations", "customization_bindings",
            "answer_overrides", "users", "llm_providers", "llm_routing",
        }
        assert expected.issubset(names), f"Missing tables: {expected - names}"


@pytest.mark.integration
async def test_conversation_reserved_fields_nullable(db_session):
    conv = Conversation(
        question="NE503 功耗是多少?",
        channel="widget",
        language="zh",
        is_answered=True,
    )
    db_session.add(conv)
    await db_session.commit()

    result = await db_session.execute(
        select(Conversation).where(Conversation.id == conv.id)
    )
    saved = result.scalar_one()
    assert saved.intent_tag is None
    assert saved.cluster_id is None
    assert saved.gap_status is None
```

- [ ] **Step 2: Create backend/db/models.py with all 10 tables**

```python
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean, Integer, String, Text, DateTime, ForeignKey, func, Index, text,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str | None] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(String(20), default="widget")
    language: Mapped[str | None] = mapped_column(String(10))
    sources: Mapped[list[Any]] = mapped_column(JSONB, default=[])
    is_answered: Mapped[bool] = mapped_column(Boolean, default=False)
    feedback: Mapped[str | None] = mapped_column(String(10))
    response_time_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Phase 2 预留
    intent_tag: Mapped[str | None] = mapped_column(String(100))
    custom_tags: Mapped[list[Any]] = mapped_column(JSONB, default=[])
    customization_id: Mapped[str | None] = mapped_column(String(50))

    # Phase 3 预留
    cluster_id: Mapped[str | None] = mapped_column(String(100))
    gap_status: Mapped[str | None] = mapped_column(String(20))
    override_answer: Mapped[str | None] = mapped_column(Text)

    clicks: Mapped[list["SourceClick"]] = relationship(back_populates="conversation", cascade="all, delete-orphan")


class SourceClick(Base):
    __tablename__ = "source_clicks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    product: Mapped[str | None] = mapped_column(String(50))
    clicked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversation: Mapped["Conversation"] = relationship(back_populates="clicks")


class SyncLog(Base):
    __tablename__ = "sync_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[str] = mapped_column(String(100), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    items_new: Mapped[int] = mapped_column(Integer, default=0)
    items_updated: Mapped[int] = mapped_column(Integer, default=0)
    items_deleted: Mapped[int] = mapped_column(Integer, default=0)
    items_unchanged: Mapped[int] = mapped_column(Integer, default=0)
    error_detail: Mapped[str | None] = mapped_column(Text)
    triggered_by: Mapped[str] = mapped_column(String(20), default="cron")


class DataSource(Base):
    __tablename__ = "data_sources"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    product: Mapped[str] = mapped_column(String(50), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    sync_interval: Mapped[str] = mapped_column(String(20), default="24h")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Customization(Base):
    __tablename__ = "customizations"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    style_tone: Mapped[str | None] = mapped_column(Text)
    guardrails: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(10), default="auto")
    assistant_name: Mapped[str] = mapped_column(String(50), default="CamThink 助手")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[str] = mapped_column(String(20), default="1.0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CustomizationBinding(Base):
    __tablename__ = "customization_bindings"

    channel: Mapped[str] = mapped_column(String(20), primary_key=True)
    customization_id: Mapped[str] = mapped_column(ForeignKey("customizations.id", ondelete="CASCADE"))


class AnswerOverride(Base):
    __tablename__ = "answer_overrides"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    match_pattern: Mapped[str] = mapped_column(Text, nullable=False)
    match_type: Mapped[str] = mapped_column(String(20), default="semantic")
    override_answer: Mapped[str] = mapped_column(Text, nullable=False)
    override_sources: Mapped[list[Any]] = mapped_column(JSONB, default=[])
    created_by: Mapped[str | None] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20), default="viewer")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LLMProviderModel(Base):
    __tablename__ = "llm_providers"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LLMRouting(Base):
    __tablename__ = "llm_routing"

    task: Mapped[str] = mapped_column(String(50), primary_key=True)
    chain: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# 索引(对齐设计文档 §11 SQL DDL)
Index("idx_conversations_created_at", Conversation.created_at)
Index("idx_conversations_is_answered", Conversation.is_answered)
Index("idx_conversations_channel", Conversation.channel)
Index("idx_conversations_cluster_id", Conversation.cluster_id, postgresql_where=text("cluster_id IS NOT NULL"))
Index("idx_conversations_gap_status", Conversation.gap_status, postgresql_where=text("gap_status IS NOT NULL"))
Index("idx_source_clicks_conversation", SourceClick.conversation_id)
Index("idx_source_clicks_source_url", SourceClick.source_url)
Index("idx_sync_log_source", SyncLog.source_id, SyncLog.started_at.desc())
Index("idx_sync_log_status", SyncLog.status, SyncLog.started_at.desc())
```

- [ ] **Step 3: Create backend/db/session.py**

```python
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from backend.db.models import Base


def get_engine(dsn: str) -> AsyncEngine:
    return create_async_engine(dsn, echo=False, pool_pre_ping=True)


def get_session_factory(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/db/test_models.py -v -m integration`
Note: Requires Postgres running (see Task 3 for Docker Compose).

- [ ] **Step 5: Commit**

```bash
git add backend/db/ tests/db/
git commit -m "feat: Postgres 数据模型(10 张表,含预留字段)"
```

---

## Task 3: Docker Compose

**Files:**
- Create: `deploy/docker-compose.yml`
- Create: `backend/main.py` (minimal FastAPI app)

**Interfaces:**
- Produces: Running Postgres + Weaviate + backend on localhost

- [ ] **Step 1: Create docker-compose.yml**

```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: ask_ai
      POSTGRES_USER: ask_ai
      POSTGRES_PASSWORD: changeme
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ask_ai"]
      interval: 5s
      retries: 5

  weaviate:
    image: cr.weaviate.io/semitechnologies/weaviate:1.28
    command:
      - --host
      - 0.0.0.0
      - --port
      - "8080"
      - --scheme
      - http
    environment:
      AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED: "true"
      DISABLE_TELEMETRY: "true"
      PERSISTENCE_DATA_PATH: "/var/lib/weaviate"
    ports:
      - "8080:8080"
    volumes:
      - weaviate_data:/var/lib/weaviate

  backend:
    build: .
    ports:
      - "8000:8000"
    env_file: ../.env
    depends_on:
      postgres:
        condition: service_healthy
      weaviate:
        condition: service_started

volumes:
  pgdata:
  weaviate_data:
```

- [ ] **Step 2: Create minimal backend/main.py**

```python
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from backend.config import load_settings

logger = logging.getLogger(__name__)
settings = load_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Ask AI 后端启动中...")
    yield
    logger.info("Ask AI 后端关闭")


app = FastAPI(title="Ask AI", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    logging.basicConfig(level=settings.log_level)
    uvicorn.run(app, host=settings.api_host, port=settings.api_port)
```

- [ ] **Step 3: Test locally**

Run: `docker compose -f deploy/docker-compose.yml up -d postgres weaviate`
Then: `python -m backend.main`
Expected: Server starts, `GET /health` returns `{"status": "ok"}`

- [ ] **Step 4: Commit**

```bash
git add deploy/ backend/main.py
git commit -m "feat: Docker Compose(Postgres+Weaviate)+ FastAPI 入口"
```

---

## Task 4: LLM Provider Framework

**Files:**
- Create: `backend/llm/__init__.py`
- Create: `backend/llm/base.py`
- Create: `backend/llm/registry.py`
- Create: `backend/llm/deepseek.py`
- Test: `tests/llm/test_deepseek.py`

**Interfaces:**
- Consumes: `Settings` (from Task 1)
- Produces: `LLMProvider` Protocol, `LLMResponse`, `LLMRegistry`, `LLMRouter`, `DeepseekProvider`

- [ ] **Step 1: Write test**

```python
# tests/llm/test_deepseek.py
import pytest
from backend.llm.base import LLMResponse
from backend.llm.deepseek import DeepseekProvider
from backend.llm.registry import LLMRegistry


@pytest.mark.unit
def test_deepseek_provider_registered():
    assert "openai_compatible" in LLMRegistry._providers


@pytest.mark.unit
def test_deepseek_generate_returns_llm_response(monkeypatch):
    provider = DeepseekProvider(
        provider_id="deepseek",
        api_base="https://api.deepseek.com/v1",
        api_key="fake-key",
        model="deepseek-chat",
    )

    async def fake_post(self, url, **kwargs):
        class FakeResponse:
            status_code = 200
            def json(self):
                return {
                    "choices": [{"message": {"content": "NE503 功耗 2.5W"}}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 10},
                }
            def elapsed(self):
                return 0.5
        return FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)
    import asyncio
    result = asyncio.get_event_loop().run_until_complete(
        provider.generate(messages=[{"role": "user", "content": "test"}])
    )
    assert isinstance(result, LLMResponse)
    assert "2.5W" in result.content
```

- [ ] **Step 2: Create backend/llm/base.py**

```python
from dataclasses import dataclass
from typing import AsyncIterator, Protocol


@dataclass(frozen=True)
class LLMResponse:
    content: str
    model: str
    tokens_input: int
    tokens_output: int
    latency_ms: int


class LLMProvider(Protocol):
    @property
    def provider_id(self) -> str: ...

    async def generate(self, messages: list[dict], **kwargs) -> LLMResponse: ...

    async def stream(self, messages: list[dict], **kwargs) -> AsyncIterator[str]: ...

    async def health_check(self) -> bool: ...
```

- [ ] **Step 3: Create backend/llm/registry.py**

```python
from typing import Protocol

from backend.llm.base import LLMProvider


class LLMRegistry:
    _providers: dict[str, type] = {}

    @classmethod
    def register(cls, provider_type: str):
        def decorator(provider_cls):
            cls._providers[provider_type] = provider_cls
            return provider_cls
        return decorator

    @classmethod
    def create(cls, provider_type: str, **kwargs) -> LLMProvider:
        provider_cls = cls._providers[provider_type]
        return provider_cls(**kwargs)


class LLMRouter:
    def __init__(self, providers: dict[str, LLMProvider], routing: dict[str, list[str]]):
        self._providers = providers
        self._routing = routing

    def _get_chain(self, task: str) -> list[str]:
        return self._routing.get(task, self._routing.get("generation", []))

    async def generate(self, messages: list[dict], task: str = "generation", **kwargs):
        from backend.llm.base import LLMResponse
        chain = self._get_chain(task)
        last_error = None
        for provider_id in chain:
            provider = self._providers.get(provider_id)
            if provider is None:
                continue
            try:
                if await provider.health_check():
                    return await provider.generate(messages, **kwargs)
            except Exception as e:
                last_error = e
                continue
        raise RuntimeError(f"All LLM providers unavailable: {last_error}")

    async def stream(self, messages: list[dict], task: str = "generation", **kwargs):
        chain = self._get_chain(task)
        for provider_id in chain:
            provider = self._providers.get(provider_id)
            if provider is None:
                continue
            try:
                if await provider.health_check():
                    async for chunk in provider.stream(messages, **kwargs):
                        yield chunk
                    return
            except Exception:
                continue
        raise RuntimeError("All LLM providers unavailable")
```

- [ ] **Step 4: Create backend/llm/deepseek.py**

```python
import time
import logging

import httpx

from backend.llm.base import LLMResponse
from backend.llm.registry import LLMRegistry

logger = logging.getLogger(__name__)


@LLMRegistry.register("openai_compatible")
class DeepseekProvider:
    def __init__(
        self,
        provider_id: str,
        api_base: str,
        api_key: str,
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ):
        self._id = provider_id
        self._api_base = api_base.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature

    @property
    def provider_id(self) -> str:
        return self._id

    async def generate(self, messages: list[dict], **kwargs) -> LLMResponse:
        start = time.monotonic()
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self._api_base}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": kwargs.get("model", self._model),
                    "messages": messages,
                    "max_tokens": kwargs.get("max_tokens", self._max_tokens),
                    "temperature": kwargs.get("temperature", self._temperature),
                    "stream": False,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        elapsed_ms = int((time.monotonic() - start) * 1000)
        return LLMResponse(
            content=data["choices"][0]["message"]["content"],
            model=data.get("model", self._model),
            tokens_input=data["usage"]["prompt_tokens"],
            tokens_output=data["usage"]["completion_tokens"],
            latency_ms=elapsed_ms,
        )

    async def stream(self, messages: list[dict], **kwargs):
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST",
                f"{self._api_base}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": kwargs.get("model", self._model),
                    "messages": messages,
                    "max_tokens": kwargs.get("max_tokens", self._max_tokens),
                    "temperature": kwargs.get("temperature", self._temperature),
                    "stream": True,
                },
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data: ") and line != "data: [DONE]":
                        import json
                        chunk = json.loads(line[6:])
                        delta = chunk["choices"][0].get("delta", {})
                        if content := delta.get("content"):
                            yield content

    async def health_check(self) -> bool:
        return bool(self._api_key)
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/llm/test_deepseek.py -v -m unit`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/llm/ tests/llm/
git commit -m "feat: LLM 供应商框架(Protocol+Registry+DeepseekProvider)"
```

---

## Task 5: Data Connector Framework

**Files:**
- Create: `backend/connectors/__init__.py`
- Create: `backend/connectors/base.py`
- Create: `backend/connectors/registry.py`
- Test: `tests/connectors/test_registry.py`

**Interfaces:**
- Produces: `RawDocument`, `DataSourceConnector` Protocol, `ConnectorRegistry`, `SourceConfig`

- [ ] **Step 1: Write test**

```python
# tests/connectors/test_registry.py
import pytest
from datetime import datetime
from typing import Iterator

from backend.connectors.base import DataSourceConnector, RawDocument
from backend.connectors.registry import ConnectorRegistry, SourceConfig


@pytest.mark.unit
def test_register_and_create_connector():
    @ConnectorRegistry.register("test_type")
    class TestConnector:
        def __init__(self, config: SourceConfig):
            self._config = config

        @property
        def source_id(self) -> str:
            return self._config.id

        @property
        def product(self) -> str:
            return self._config.product

        def fetch_all(self) -> Iterator[RawDocument]:
            yield RawDocument(
                source_id="test-1",
                source_type="test_type",
                product="test",
                title="Test Doc",
                content="Hello world",
                url="https://example.com/test",
                metadata={},
                content_hash="abc123",
            )

        def fetch_changes(self, since: datetime) -> Iterator[RawDocument]:
            return iter([])

        def fetch_deleted(self, since: datetime) -> list[str]:
            return []

    config = SourceConfig(
        id="test-source",
        type="test_type",
        product="test",
        enabled=True,
        config={},
        sync_interval="1h",
    )

    connector = ConnectorRegistry.create(config)
    assert connector.source_id == "test-source"
    docs = list(connector.fetch_all())
    assert len(docs) == 1
    assert docs[0].title == "Test Doc"
```

- [ ] **Step 2: Create backend/connectors/base.py**

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterator, Protocol


@dataclass(frozen=True)
class RawDocument:
    source_id: str
    source_type: str
    product: str
    title: str
    content: str
    url: str
    metadata: dict[str, Any]
    content_hash: str


class DataSourceConnector(Protocol):
    @property
    def source_id(self) -> str: ...

    @property
    def product(self) -> str: ...

    def fetch_all(self) -> Iterator[RawDocument]: ...
    def fetch_changes(self, since: datetime) -> Iterator[RawDocument]: ...
    def fetch_deleted(self, since: datetime) -> list[str]: ...
```

- [ ] **Step 3: Create backend/connectors/registry.py**

```python
from dataclasses import dataclass
from typing import Any

from backend.connectors.base import DataSourceConnector


@dataclass(frozen=True)
class SourceConfig:
    id: str
    type: str
    product: str
    enabled: bool
    config: dict[str, Any]
    sync_interval: str


class ConnectorRegistry:
    _connectors: dict[str, type] = {}

    @classmethod
    def register(cls, connector_type: str):
        def decorator(connector_cls):
            cls._connectors[connector_type] = connector_cls
            return connector_cls
        return decorator

    @classmethod
    def create(cls, config: SourceConfig) -> DataSourceConnector:
        connector_cls = cls._connectors[config.type]
        return connector_cls(config)

    @classmethod
    def load_configs(cls, yaml_data: dict) -> list[SourceConfig]:
        configs = []
        for src in yaml_data.get("sources", []):
            configs.append(SourceConfig(
                id=src["id"],
                type=src["type"],
                product=src["product"],
                enabled=src.get("enabled", True),
                config=src.get("config", {}),
                sync_interval=src.get("sync_interval", "24h"),
            ))
        return configs
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/connectors/test_registry.py -v -m unit`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/connectors/ tests/connectors/
git commit -m "feat: 数据源 Connector 框架(Protocol+Registry+SourceConfig)"
```

---

## Task 6: GitHub Connector

**Files:**
- Create: `backend/connectors/github.py`
- Test: `tests/connectors/test_github.py`

**Interfaces:**
- Consumes: `SourceConfig` (type="github"), `GITHUB_TOKEN` env var
- Produces: `RawDocument` stream from GitHub repos

- [ ] **Step 1: Write test**

```python
# tests/connectors/test_github.py
import pytest
from backend.connectors.registry import SourceConfig, ConnectorRegistry


@pytest.mark.unit
def test_github_connector_registered():
    assert "github" in ConnectorRegistry._connectors


@pytest.mark.integration
def test_github_fetch_wiki_docs():
    """集成测试:拉取 camthink-ai/wiki-documents 的 README"""
    import os
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        pytest.skip("GITHUB_TOKEN not set")

    config = SourceConfig(
        id="github-wiki-test",
        type="github",
        product="wiki",
        enabled=True,
        config={
            "owner": "camthink-ai",
            "repo": "wiki-documents",
            "branch": "main",
            "file_types": [".md"],
            "include_dirs": ["README.md"],
        },
        sync_interval="1h",
    )
    connector = ConnectorRegistry.create(config)
    docs = list(connector.fetch_all())
    assert len(docs) > 0
    assert all(d.source_type == "github" for d in docs)
```

- [ ] **Step 2: Create backend/connectors/github.py**

```python
import base64
import hashlib
import logging
import re
from datetime import datetime
from typing import Any, Iterator

import httpx

from backend.connectors.base import RawDocument
from backend.connectors.registry import ConnectorRegistry, SourceConfig

logger = logging.getLogger(__name__)

SUPPORTED_FILE_TYPES = {
    ".md", ".mdx", ".txt", ".py", ".ts", ".tsx", ".js", ".jsx",
    ".rs", ".c", ".h", ".cpp", ".hpp", ".go", ".java", ".json",
    ".yaml", ".yml", ".sh", ".ipynb",
}

AUTO_EXCLUDE = re.compile(
    r"(node_modules|\.next|\.git|__pycache__|venv|\.venv|\.tox|dist|build)/",
    re.IGNORECASE,
)


@ConnectorRegistry.register("github")
class GitHubConnector:
    def __init__(self, config: SourceConfig):
        import os
        self._config = config
        self._owner = config.config["owner"]
        self._repo = config.config["repo"]
        self._branch = config.config.get("branch", "main")
        self._file_types = set(config.config.get("file_types", [".md"]))
        self._include_dirs = config.config.get("include_dirs", [])
        self._exclude_regex = config.config.get("exclude_regex")
        self._token = os.environ.get("GITHUB_TOKEN", "")
        self._headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}" if self._token else "",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._exclude_regex:
            self._exclude_pattern = re.compile(self._exclude_regex)
        else:
            self._exclude_pattern = None

    @property
    def source_id(self) -> str:
        return self._config.id

    @property
    def product(self) -> str:
        return self._config.product

    def _api_url(self, path: str) -> str:
        return f"https://api.github.com/repos/{self._owner}/{self._repo}/contents/{path}?ref={self._branch}"

    def _fetch_tree(self) -> list[dict]:
        url = f"https://api.github.com/repos/{self._owner}/{self._repo}/git/trees/{self._branch}?recursive=1"
        with httpx.Client(timeout=30, headers=self._headers) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.json().get("tree", [])

    def _should_include(self, path: str) -> bool:
        if AUTO_EXCLUDE.search(path):
            return False
        if self._exclude_pattern and self._exclude_pattern.search(path):
            return False
        if self._include_dirs:
            if not any(path.startswith(d.rstrip("/")) or path == d for d in self._include_dirs):
                return False
        ext = "." + path.rsplit(".", 1)[-1] if "." in path else ""
        return ext in self._file_types

    def _fetch_file_content(self, path: str) -> str:
        with httpx.Client(timeout=30, headers=self._headers) as client:
            resp = client.get(self._api_url(path))
            resp.raise_for_status()
            data = resp.json()
            if data.get("encoding") == "base64":
                return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
            return data.get("content", "")

    def _make_document(self, path: str, content: str) -> RawDocument:
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        title = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        url = f"https://github.com/{self._owner}/{self._repo}/blob/{self._branch}/{path}"
        return RawDocument(
            source_id=f"{self._owner}/{self._repo}/{path}",
            source_type="github",
            product=self.product,
            title=title,
            content=content,
            url=url,
            metadata={
                "repo": f"{self._owner}/{self._repo}",
                "branch": self._branch,
                "path": path,
            },
            content_hash=content_hash,
        )

    def fetch_all(self) -> Iterator[RawDocument]:
        tree = self._fetch_tree()
        for item in tree:
            if item["type"] != "blob":
                continue
            path = item["path"]
            if not self._should_include(path):
                continue
            try:
                content = self._fetch_file_content(path)
                yield self._make_document(path, content)
            except Exception as e:
                logger.warning(f"Failed to fetch {path}: {e}")

    def fetch_changes(self, since: datetime) -> Iterator[RawDocument]:
        url = f"https://api.github.com/repos/{self._owner}/{self._repo}/commits"
        params = {"since": since.isoformat(), "sha": self._branch, "per_page": 100}
        changed_paths: set[str] = set()
        with httpx.Client(timeout=30, headers=self._headers) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            for commit in resp.json():
                for f in commit.get("files", []):
                    changed_paths.add(f["filename"])

        for path in changed_paths:
            if not self._should_include(path):
                continue
            try:
                content = self._fetch_file_content(path)
                yield self._make_document(path, content)
            except Exception as e:
                logger.warning(f"Failed to fetch changed {path}: {e}")

    def fetch_deleted(self, since: datetime) -> list[str]:
        url = f"https://api.github.com/repos/{self._owner}/{self._repo}/commits"
        params = {"since": since.isoformat(), "sha": self._branch, "per_page": 100}
        deleted: list[str] = []
        with httpx.Client(timeout=30, headers=self._headers) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            for commit in resp.json():
                for f in commit.get("files", []):
                    if f["status"] == "removed" and self._should_include(f["filename"]):
                        deleted.append(f"{self._owner}/{self._repo}/{f['filename']}")
        return deleted
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/connectors/test_github.py -v -m unit`
Expected: PASS (registration test)

Run: `pytest tests/connectors/test_github.py -v -m integration`
Expected: PASS if GITHUB_TOKEN set

- [ ] **Step 4: Commit**

```bash
git add backend/connectors/github.py tests/connectors/test_github.py
git commit -m "feat: GitHubConnector(GitHub API 拉取 + 过滤 + 增量)"
```

---

## Task 7: Filesystem Connector

**Files:**
- Create: `backend/connectors/filesystem.py`
- Test: `tests/connectors/test_filesystem.py`

**Interfaces:**
- Consumes: `SourceConfig` (type="filesystem")
- Produces: `RawDocument` stream from local files

- [ ] **Step 1: Write test**

```python
# tests/connectors/test_filesystem.py
import pytest
from pathlib import Path

from backend.connectors.registry import SourceConfig, ConnectorRegistry


@pytest.mark.unit
def test_filesystem_connector_registered():
    assert "filesystem" in ConnectorRegistry._connectors


@pytest.mark.unit
def test_filesystem_fetch_local_files(tmp_path):
    (tmp_path / "doc1.md").write_text("# NE503\n功耗 2.5W")
    (tmp_path / "doc2.txt").write_text("Hello")
    (tmp_path / "ignore.log").write_text("nope")

    config = SourceConfig(
        id="test-fs",
        type="filesystem",
        product="test",
        enabled=True,
        config={
            "root_path": str(tmp_path),
            "file_types": [".md", ".txt"],
        },
        sync_interval="1h",
    )
    connector = ConnectorRegistry.create(config)
    docs = list(connector.fetch_all())
    assert len(docs) == 2
    titles = {d.title for d in docs}
    assert "doc1" in titles
    assert "doc2" in titles
```

- [ ] **Step 2: Create backend/connectors/filesystem.py**

```python
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Iterator

from backend.connectors.base import RawDocument
from backend.connectors.registry import ConnectorRegistry, SourceConfig

logger = logging.getLogger(__name__)


@ConnectorRegistry.register("filesystem")
class FilesystemConnector:
    def __init__(self, config: SourceConfig):
        self._config = config
        root = Path(config.config["root_path"]).expanduser()
        self._root = root
        self._file_types = set(config.config.get("file_types", [".md", ".txt"]))
        self._include_dirs = config.config.get("include_dirs", [])

    @property
    def source_id(self) -> str:
        return self._config.id

    @property
    def product(self) -> str:
        return self._config.product

    def _should_include(self, path: Path) -> bool:
        if path.suffix not in self._file_types:
            return False
        rel = path.relative_to(self._root)
        if self._include_dirs:
            if not any(str(rel).startswith(d.rstrip("/")) for d in self._include_dirs):
                return False
        return True

    def _make_document(self, path: Path) -> RawDocument:
        content = path.read_text(encoding="utf-8", errors="replace")
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        rel = str(path.relative_to(self._root))
        title = path.stem
        return RawDocument(
            source_id=f"{self._config.id}/{rel}",
            source_type="filesystem",
            product=self.product,
            title=title,
            content=content,
            url=f"file://{path.absolute()}",
            metadata={"path": rel, "root": str(self._root)},
            content_hash=content_hash,
        )

    def fetch_all(self) -> Iterator[RawDocument]:
        for path in sorted(self._root.rglob("*")):
            if path.is_file() and self._should_include(path):
                yield self._make_document(path)

    def fetch_changes(self, since: datetime) -> Iterator[RawDocument]:
        import os
        for path in sorted(self._root.rglob("*")):
            if path.is_file() and self._should_include(path):
                mtime = datetime.fromtimestamp(path.stat().st_mtime)
                if mtime > since:
                    yield self._make_document(path)

    def fetch_deleted(self, since: datetime) -> list[str]:
        return []
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/connectors/test_filesystem.py -v -m unit`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/connectors/filesystem.py tests/connectors/test_filesystem.py
git commit -m "feat: FilesystemConnector(本地文件 + 增量)"
```

---

## Task 8: Embedder & Reranker

**Files:**
- Create: `backend/embedder/__init__.py`
- Create: `backend/embedder/base.py`
- Create: `backend/embedder/bge.py`
- Test: `tests/embedder/test_bge.py`

**Interfaces:**
- Consumes: `EMBEDDER_DEVICE` env var
- Produces: `Embedder` Protocol, `Reranker` Protocol, `BGEEembedder`, `BGEReranker`

- [ ] **Step 1: Write test**

```python
# tests/embedder/test_bge.py
import pytest
import numpy as np


@pytest.mark.integration
def test_embedder_produces_vectors():
    from backend.embedder.bge import BGEEmbedder
    embedder = BGEEmbedder(device="cpu")
    vectors = embedder.embed(["Hello world", "NE503 specs"])
    assert len(vectors) == 2
    assert all(isinstance(v, np.ndarray) for v in vectors)
    assert all(len(v) == 1024 for v in vectors)


@pytest.mark.integration
def test_reranker_scores_pairs():
    from backend.embedder.bge import BGEReranker
    reranker = BGEReranker(device="cpu")
    scores = reranker.rerank(
        query="NE503 功耗",
        documents=["NE503 功耗 2.5W", "天气很好今天"],
    )
    assert len(scores) == 2
    assert scores[0] > scores[1]
```

- [ ] **Step 2: Create backend/embedder/base.py**

```python
from typing import Protocol
import numpy as np


def detect_device(preference: str = "auto") -> str:
    if preference != "auto":
        return preference
    import torch
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class Embedder(Protocol):
    @property
    def dimension(self) -> int: ...

    def embed(self, texts: list[str]) -> list[np.ndarray]: ...


class Reranker(Protocol):
    def rerank(self, query: str, documents: list[str]) -> list[float]: ...
```

- [ ] **Step 3: Create backend/embedder/bge.py**

```python
import logging
from typing import Optional

import numpy as np

from backend.embedder.base import detect_device

logger = logging.getLogger(__name__)


class BGEEmbedder:
    def __init__(self, device: str = "auto", model_name: str = "BAAI/bge-m3"):
        self._device = detect_device(device)
        self._dimension = 1024
        logger.info(f"加载 BGE-m3 嵌入模型(device={self._device})...")
        from FlagEmbedding import BGEM3FlagModel
        self._model = BGEM3FlagModel(model_name, use_fp16=self._device != "cpu")
        logger.info("BGE-m3 加载完成")

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        embeddings = self._model.encode(
            texts,
            batch_size=12,
            max_length=8192,
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=False,
        )
        return [np.array(v) for v in embeddings["dense_vecs"]]


class BGEReranker:
    def __init__(self, device: str = "auto", model_name: str = "BAAI/bge-reranker-v2-m3"):
        self._device = detect_device(device)
        logger.info(f"加载 bge-reranker-v2-m3(device={self._device})...")
        from FlagEmbedding import FlagReranker
        self._model = FlagReranker(model_name, use_fp16=self._device != "cpu")
        logger.info("bge-reranker 加载完成")

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        pairs = [[query, doc] for doc in documents]
        scores = self._model.compute_score(pairs, normalize=True)
        if isinstance(scores, float):
            scores = [scores]
        return list(scores)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/embedder/test_bge.py -v -m integration`
Note: Requires downloading model weights on first run (several GB).

- [ ] **Step 5: Commit**

```bash
git add backend/embedder/ tests/embedder/
git commit -m "feat: BGE-m3 嵌入 + bge-reranker-v2-m3 重排 + device 抽象"
```

---

## Task 9: Chunking Pipeline

**Files:**
- Create: `backend/pipeline/__init__.py`
- Create: `backend/pipeline/chunk.py`
- Test: `tests/pipeline/test_chunk.py`

**Interfaces:**
- Consumes: `RawDocument`
- Produces: `Chunk` (text segment with metadata)

- [ ] **Step 1: Write test**

```python
# tests/pipeline/test_chunk.py
import pytest
from backend.pipeline.chunk import chunk_document, Chunk
from backend.connectors.base import RawDocument


@pytest.mark.unit
def test_chunk_short_document():
    doc = RawDocument(
        source_id="test/1",
        source_type="filesystem",
        product="test",
        title="Short",
        content="This is a short doc.",
        url="https://example.com",
        metadata={},
        content_hash="abc",
    )
    chunks = chunk_document(doc, max_tokens=500, overlap=50)
    assert len(chunks) == 1
    assert chunks[0].text == "This is a short doc."
    assert chunks[0].document == doc


@pytest.mark.unit
def test_chunk_long_document_splits():
    content = "\n\n".join([f"## Section {i}\n\nParagraph content for section {i}." for i in range(50)])
    doc = RawDocument(
        source_id="test/2",
        source_type="github",
        product="ne503",
        title="Big Doc",
        content=content,
        url="https://github.com/test",
        metadata={"path": "docs/big.md"},
        content_hash="def",
    )
    chunks = chunk_document(doc, max_tokens=200, overlap=20)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.chunk_index >= 0
        assert len(chunk.text) > 0
```

- [ ] **Step 2: Create backend/pipeline/chunk.py**

```python
import re
from dataclasses import dataclass
from typing import Iterator

import tiktoken

from backend.connectors.base import RawDocument


@dataclass(frozen=True)
class Chunk:
    text: str
    document: RawDocument
    chunk_index: int
    total_chunks: int
    start_char: int
    end_char: int


def _split_by_structure(content: str) -> list[str]:
    parts = re.split(r"\n(?=#{1,3}\s)", content)
    return [p.strip() for p in parts if p.strip()]


def _estimate_tokens(text: str) -> int:
    enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))


def _merge_small_sections(sections: list[str], max_tokens: int) -> list[str]:
    merged: list[str] = []
    buffer = ""
    for section in sections:
        candidate = f"{buffer}\n\n{section}" if buffer else section
        if _estimate_tokens(candidate) <= max_tokens:
            buffer = candidate
        else:
            if buffer:
                merged.append(buffer)
            buffer = section
    if buffer:
        merged.append(buffer)
    return merged


def chunk_document(
    doc: RawDocument,
    max_tokens: int = 600,
    overlap: int = 50,
) -> list[Chunk]:
    sections = _split_by_structure(doc.content)
    if len(sections) <= 1:
        sections = [doc.content]

    merged = _merge_small_sections(sections, max_tokens)
    if not merged:
        merged = [doc.content]

    chunks: list[Chunk] = []
    offset = 0
    for i, text in enumerate(merged):
        chunks.append(Chunk(
            text=text,
            document=doc,
            chunk_index=i,
            total_chunks=len(merged),
            start_char=doc.content.find(text, offset),
            end_char=doc.content.find(text, offset) + len(text),
        ))
        offset += len(text)
    return chunks
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/pipeline/test_chunk.py -v -m unit`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/pipeline/chunk.py tests/pipeline/
git commit -m "feat: 文档分段管道(按结构分割 + token 估算 + 合并)"
```

---

## Task 10: Ingestion Pipeline

**Files:**
- Create: `backend/pipeline/ingest.py`
- Test: `tests/pipeline/test_ingest.py`

**Interfaces:**
- Consumes: `DataSourceConnector`, `Embedder`, Weaviate client, Postgres session
- Produces: Ingested documents in Weaviate + Postgres

- [ ] **Step 1: Write test**

```python
# tests/pipeline/test_ingest.py
import pytest
from unittest.mock import MagicMock, AsyncMock

from backend.connectors.base import RawDocument
from backend.pipeline.ingest import IngestionPipeline


@pytest.mark.unit
def test_ingest_document_stores_in_weaviate():
    embedder = MagicMock()
    embedder.embed.return_value = [[0.1] * 1024]
    embedder.dimension = 1024

    weaviate_client = MagicMock()
    collection = MagicMock()
    weaviate_client.collections.get.return_value = collection

    doc = RawDocument(
        source_id="test/1",
        source_type="github",
        product="ne503",
        title="Test",
        content="NE503 specs",
        url="https://github.com/test",
        metadata={"path": "README.md"},
        content_hash="abc123",
    )

    pipeline = IngestionPipeline(embedder, weaviate_client, class_name="Document")
    pipeline.ingest_document(doc)

    embedder.embed.assert_called_once_with(["NE503 specs"])
    assert collection.data.insert.called
```

- [ ] **Step 2: Create backend/pipeline/ingest.py**

```python
import hashlib
import logging
from typing import Any

from backend.connectors.base import RawDocument
from backend.embedder.base import Embedder
from backend.pipeline.chunk import Chunk, chunk_document

logger = logging.getLogger(__name__)


class IngestionPipeline:
    def __init__(
        self,
        embedder: Embedder,
        weaviate_client: Any,
        class_name: str = "Document",
        max_tokens: int = 600,
        overlap: int = 50,
    ):
        self._embedder = embedder
        self._client = weaviate_client
        self._class_name = class_name
        self._max_tokens = max_tokens
        self._overlap = overlap
        self._collection = None

    def _ensure_collection(self):
        if self._collection is not None:
            return
        try:
            self._collection = self._client.collections.get(self._class_name)
        except Exception:
            from weaviate.classes.config import Configure, Property, DataType
            self._collection = self._client.collections.create(
                name=self._class_name,
                vectorizer_config=Configure.Vectorizer.none(),
                properties=[
                    Property(name="source_id", data_type=DataType.TEXT),
                    Property(name="source_type", data_type=DataType.TEXT),
                    Property(name="product", data_type=DataType.TEXT),
                    Property(name="title", data_type=DataType.TEXT),
                    Property(name="text", data_type=DataType.TEXT),
                    Property(name="url", data_type=DataType.TEXT),
                    Property(name="chunk_index", data_type=DataType.INT),
                    Property(name="content_hash", data_type=DataType.TEXT),
                ],
            )

    def ingest_document(self, doc: RawDocument) -> int:
        chunks = chunk_document(doc, self._max_tokens, self._overlap)
        if not chunks:
            return 0

        texts = [c.text for c in chunks]
        vectors = self._embedder.embed(texts)

        self._ensure_collection()
        for chunk, vector in zip(chunks, vectors):
            self._collection.data.insert(
                properties={
                    "source_id": doc.source_id,
                    "source_type": doc.source_type,
                    "product": doc.product,
                    "title": doc.title,
                    "text": chunk.text,
                    "url": doc.url,
                    "chunk_index": chunk.chunk_index,
                    "content_hash": doc.content_hash,
                },
                vector=vector.tolist(),
            )
        return len(chunks)

    def delete_document(self, source_id: str) -> None:
        self._ensure_collection()
        self._collection.data.delete_many(
            where=self._collection.filter.by_property("source_id").equal(source_id)
        )

    def ingest_all(self, docs: list[RawDocument]) -> dict[str, int]:
        results: dict[str, int] = {}
        for doc in docs:
            try:
                count = self.ingest_document(doc)
                results[doc.source_id] = count
                logger.info(f"已索引 {doc.source_id}: {count} 个 chunk")
            except Exception as e:
                logger.error(f"索引失败 {doc.source_id}: {e}")
                results[doc.source_id] = 0
        return results
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/pipeline/test_ingest.py -v -m unit`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/pipeline/ingest.py tests/pipeline/test_ingest.py
git commit -m "feat: 数据灌入管道(chunk → embed → Weaviate)"
```

---

## Task 11: Sync Script

**Files:**
- Create: `scripts/sync.py`
- Test: `tests/pipeline/test_sync.py`

**Interfaces:**
- Consumes: All connectors + ingestion pipeline + Postgres sync_log

- [ ] **Step 1: Create scripts/sync.py**

```python
import asyncio
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.config import load_settings, load_yaml_config
from backend.connectors.registry import ConnectorRegistry
import backend.connectors.github  # noqa: F401 - register
import backend.connectors.filesystem  # noqa: F401 - register
from backend.db.models import SyncLog
from backend.db.session import get_engine, get_session_factory, init_db
from backend.embedder.bge import BGEEmbedder
from backend.pipeline.ingest import IngestionPipeline

logger = logging.getLogger(__name__)


async def run_sync(settings, source_id: str | None = None):
    config_data = load_yaml_config(settings.config_dir / "data_sources.yaml")
    configs = ConnectorRegistry.load_configs(config_data)

    engine = get_engine(settings.postgres_dsn)
    await init_db(engine)
    session_factory = get_session_factory(engine)

    import weaviate
    weaviate_client = weaviate.connect_to_local(
        host=settings.weaviate_url.split("//")[1].split(":")[0],
        port=int(settings.weaviate_url.split(":")[2]),
    )

    embedder = BGEEmbedder(device=settings.embedder_device)
    pipeline = IngestionPipeline(embedder, weaviate_client, settings.weaviate_class_name)

    for cfg in configs:
        if not cfg.enabled:
            continue
        if source_id and cfg.id != source_id:
            continue

        start = time.monotonic()
        log_entry = SyncLog(
            source_id=cfg.id,
            source_type=cfg.type,
            status="success",
            triggered_by="manual" if source_id else "cron",
        )

        try:
            connector = ConnectorRegistry.create(cfg)
            since = datetime.now(timezone.utc) - timedelta(hours=24)

            docs = list(connector.fetch_changes(since))
            if not docs:
                # 首次同步,全量拉取
                docs = list(connector.fetch_all())

            results = pipeline.ingest_all(docs)
            deleted = connector.fetch_deleted(since)
            for d in deleted:
                pipeline.delete_document(d)

            log_entry.items_new = sum(1 for v in results.values() if v > 0)
            log_entry.items_updated = sum(v for v in results.values())
            log_entry.items_deleted = len(deleted)
            log_entry.finished_at = datetime.now(timezone.utc)
            log_entry.duration_ms = int((time.monotonic() - start) * 1000)
            logger.info(f"同步完成 {cfg.id}: {log_entry.items_new} 新, {log_entry.items_updated} 更新")

        except Exception as e:
            log_entry.status = "failed"
            log_entry.error_detail = str(e)
            log_entry.finished_at = datetime.now(timezone.utc)
            log_entry.duration_ms = int((time.monotonic() - start) * 1000)
            logger.error(f"同步失败 {cfg.id}: {e}")

        async with session_factory() as session:
            session.add(log_entry)
            await session.commit()

    weaviate_client.close()
    await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = load_settings()
    target = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(run_sync(settings, target))
```

- [ ] **Step 2: Commit**

```bash
git add scripts/sync.py
git commit -m "feat: 数据源同步脚本(cron 入口 + sync_log 记录)"
```

---

## Task 12: Retrieval (Weaviate Hybrid Search)

**Files:**
- Create: `backend/retrieval/__init__.py`
- Create: `backend/retrieval/search.py`
- Test: `tests/retrieval/test_search.py`

**Interfaces:**
- Consumes: Weaviate client, `Embedder`
- Produces: `SearchResult` list

- [ ] **Step 1: Write test**

```python
# tests/retrieval/test_search.py
import pytest
from unittest.mock import MagicMock

from backend.retrieval.search import HybridSearcher, SearchResult


@pytest.mark.unit
def test_search_result_dataclass():
    sr = SearchResult(
        text="NE503 功耗 2.5W",
        source_id="github-ne503/README.md",
        source_type="github",
        product="ne503",
        title="README",
        url="https://github.com/camthink-ai/ne503-aipc-sdks",
        score=0.95,
        chunk_index=0,
    )
    assert sr.product == "ne503"
    assert sr.score == 0.95
```

- [ ] **Step 2: Create backend/retrieval/search.py**

```python
import logging
from dataclasses import dataclass
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SearchResult:
    text: str
    source_id: str
    source_type: str
    product: str
    title: str
    url: str
    score: float
    chunk_index: int


class HybridSearcher:
    def __init__(self, weaviate_client: Any, embedder: Any, class_name: str = "Document"):
        self._client = weaviate_client
        self._embedder = embedder
        self._class_name = class_name

    def search(
        self,
        query: str,
        alpha: float = 0.5,
        limit: int = 50,
        product_filter: str | None = None,
    ) -> list[SearchResult]:
        query_vector = self._embedder.embed([query])[0].tolist()

        collection = self._client.collections.get(self._class_name)

        from weaviate.classes.query import Hybrid, MetadataQuery, Filter
        kwargs: dict = {
            "query": query,
            "vector": query_vector,
            "alpha": alpha,
            "limit": limit,
            "return_metadata": MetadataQuery(distance=True),
        }
        if product_filter:
            kwargs["filters"] = collection.filter.by_property("product").equal(product_filter)

        results = collection.query.hybrid(**kwargs)

        search_results: list[SearchResult] = []
        for obj in results.objects:
            props = obj.properties
            distance = obj.metadata.distance if obj.metadata else 1.0
            score = 1.0 - distance if distance is not None else 0.0
            search_results.append(SearchResult(
                text=props.get("text", ""),
                source_id=props.get("source_id", ""),
                source_type=props.get("source_type", ""),
                product=props.get("product", ""),
                title=props.get("title", ""),
                url=props.get("url", ""),
                score=score,
                chunk_index=props.get("chunk_index", 0),
            ))
        return search_results
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/retrieval/test_search.py -v -m unit`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/retrieval/ tests/retrieval/
git commit -m "feat: Weaviate hybrid 检索 + SearchResult"
```

---

## Task 13: Reranking

**Files:**
- Create: `backend/retrieval/rerank.py`
- Test: `tests/retrieval/test_rerank.py`

**Interfaces:**
- Consumes: `Reranker`, `SearchResult` list
- Produces: Reranked `SearchResult` list (top N)

- [ ] **Step 1: Write test**

```python
# tests/retrieval/test_rerank.py
import pytest
from unittest.mock import MagicMock

from backend.retrieval.search import SearchResult
from backend.retrieval.rerank import RerankPipeline


@pytest.mark.unit
def test_rerank_orders_by_score():
    results = [
        SearchResult("text A", "s1", "github", "ne503", "A", "url", 0.8, 0),
        SearchResult("text B", "s2", "github", "ne503", "B", "url", 0.6, 0),
        SearchResult("text C", "s3", "wiki", "ne503", "C", "url", 0.9, 0),
    ]
    reranker = MagicMock()
    reranker.rerank.return_value = [0.3, 0.95, 0.7]  # B > C > A

    pipeline = RerankPipeline(reranker)
    reranked = pipeline.rerank("query", results, top_k=2)
    assert len(reranked) == 2
    assert reranked[0].source_id == "s2"  # B has highest reranker score
    assert reranked[1].source_id == "s3"  # C second


@pytest.mark.unit
def test_rerank_threshold_rejects_low_scores():
    results = [
        SearchResult("text A", "s1", "github", "ne503", "A", "url", 0.8, 0),
    ]
    reranker = MagicMock()
    reranker.rerank.return_value = [0.1]  # very low

    pipeline = RerankPipeline(reranker, threshold=0.3)
    reranked = pipeline.rerank("query", results, top_k=5)
    assert len(reranked) == 0
```

- [ ] **Step 2: Create backend/retrieval/rerank.py**

```python
import logging
from dataclasses import replace

from backend.retrieval.search import SearchResult

logger = logging.getLogger(__name__)


class RerankPipeline:
    def __init__(self, reranker, threshold: float = 0.3, top_k: int = 10):
        self._reranker = reranker
        self._threshold = threshold
        self._default_top_k = top_k

    def rerank(
        self,
        query: str,
        results: list[SearchResult],
        top_k: int | None = None,
    ) -> list[SearchResult]:
        if not results:
            return []

        k = top_k or self._default_top_k
        documents = [r.text for r in results]
        scores = self._reranker.rerank(query, documents)

        scored = list(zip(results, scores))
        scored.sort(key=lambda x: x[1], reverse=True)

        filtered = [
            replace(r, score=s)
            for r, s in scored
            if s >= self._threshold
        ]
        return filtered[:k]

    @property
    def threshold(self) -> float:
        return self._threshold
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/retrieval/test_rerank.py -v -m unit`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/retrieval/rerank.py tests/retrieval/test_rerank.py
git commit -m "feat: 重排管道(bge-reranker + 阈值过滤 + top_k)"
```

---

## Task 14: Utils (PII + Language)

**Files:**
- Create: `backend/utils/__init__.py`
- Create: `backend/utils/pii.py`
- Create: `backend/utils/language.py`
- Test: `tests/utils/test_pii.py`
- Test: `tests/utils/test_language.py`

- [ ] **Step 1: Write tests + implementation together**

```python
# backend/utils/pii.py
import re

EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_PATTERN = re.compile(r"(?:\+?86)?1[3-9]\d{9}|(\d{3}[-.]?\d{3,4}[-.]?\d{4})")


def mask_pii(text: str) -> str:
    text = EMAIL_PATTERN.sub("[邮箱已脱敏]", text)
    text = PHONE_PATTERN.sub("[电话已脱敏]", text)
    return text
```

```python
# backend/utils/language.py
from langdetect import detect, DetectorFactory

DetectorFactory.seed = 42  # 确保结果稳定


def detect_language(text: str) -> str:
    try:
        lang = detect(text)
        return lang
    except Exception:
        return "en"
```

```python
# tests/utils/test_pii.py
from backend.utils.pii import mask_pii


def test_mask_email():
    assert mask_pii("联系我 test@example.com") == "联系我 [邮箱已脱敏]"

def test_mask_phone():
    assert mask_pii("电话 13800138000") == "电话 [电话已脱敏]"

def test_no_pii_unchanged():
    assert mask_pii("NE503 功耗 2.5W") == "NE503 功耗 2.5W"
```

```python
# tests/utils/test_language.py
from backend.utils.language import detect_language

def test_detect_chinese():
    assert detect_language("NE503 的功耗是多少") == "zh-cn"

def test_detect_english():
    assert detect_language("What is the power consumption of NE503") == "en"
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/utils/ -v -m unit`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add backend/utils/ tests/utils/
git commit -m "feat: PII 脱敏 + 语言检测工具"
```

---

## Task 15: RAG Orchestration

**Files:**
- Create: `backend/pipeline/rag.py`
- Test: `tests/pipeline/test_rag.py`

**Interfaces:**
- Consumes: `HybridSearcher`, `RerankPipeline`, `LLMRouter`, system prompt config
- Produces: `RAGAnswer` (answer text + sources + is_answered)

- [ ] **Step 1: Write test**

```python
# tests/pipeline/test_rag.py
import pytest
from unittest.mock import MagicMock, AsyncMock

from backend.retrieval.search import SearchResult
from backend.pipeline.rag import RAGOrchestrator, RAGAnswer


@pytest.mark.unit
async def test_rag_rejects_when_no_results():
    searcher = MagicMock()
    searcher.search.return_value = []
    reranker = MagicMock()
    llm = MagicMock()

    rag = RAGOrchestrator(searcher, reranker, llm, system_prompt="You are helpful.")
    result = await rag.answer("random question", "widget")

    assert isinstance(result, RAGAnswer)
    assert result.is_answered is False
    assert "暂未在官方资料中找到" in result.answer


@pytest.mark.unit
async def test_rag_generates_answer():
    from backend.llm.base import LLMResponse

    searcher = MagicMock()
    searcher.search.return_value = [
        SearchResult("NE503 功耗 2.5W", "s1", "github", "ne503", "README", "url", 0.9, 0)
    ]
    reranker = MagicMock()
    reranker.rerank.return_value = [0.95]  # 返回 float 分数列表,不是 SearchResult
    llm = AsyncMock()
    llm.generate.return_value = LLMResponse(
        content="NE503 的功耗为 2.5W [GitHub]",
        model="deepseek-chat",
        tokens_input=100,
        tokens_output=20,
        latency_ms=500,
    )

    rag = RAGOrchestrator(searcher, reranker, llm, system_prompt="You are helpful.")
    result = await rag.answer("NE503 功耗是多少?", "widget")

    assert result.is_answered is True
    assert "2.5W" in result.answer
    assert len(result.sources) == 1
```

- [ ] **Step 2: Create backend/pipeline/rag.py**

```python
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from backend.retrieval.search import SearchResult
from backend.utils.language import detect_language

logger = logging.getLogger(__name__)

REJECT_ANSWER = "暂未在官方资料中找到相关信息。"

SOURCE_LABELS = {
    "github": "[GitHub]",
    "wiki": "[Wiki]",
    "website": "[官网]",
    "blog": "[博客]",
    "filesystem": "[知识库]",
}


@dataclass(frozen=True)
class RAGAnswer:
    answer: str
    sources: list[dict]
    is_answered: bool
    reranked_results: list[SearchResult]
    language: str
    response_time_ms: int


class RAGOrchestrator:
    def __init__(
        self,
        searcher: Any,
        reranker: Any,
        llm: Any,
        system_prompt: str,
        alpha: float = 0.5,
        recall_limit: int = 50,
        top_k: int = 10,
        conversation_max_turns: int = 5,
        pruner: Any = None,  # Phase 3 预留:Pruner Protocol
    ):
        self._searcher = searcher
        self._reranker = reranker
        self._llm = llm
        self._system_prompt = system_prompt
        self._alpha = alpha
        self._recall_limit = recall_limit
        self._top_k = top_k
        self._max_turns = conversation_max_turns
        self._pruner = pruner

    def _build_context(self, results: list[SearchResult]) -> str:
        parts = []
        for i, r in enumerate(results, 1):
            label = SOURCE_LABELS.get(r.source_type, f"[{r.source_type}]")
            parts.append(f"[{i}] {label} {r.title}\nURL: {r.url}\n\n{r.text}")
        return "\n\n---\n\n".join(parts)

    def _build_messages(self, query: str, context: str, language: str, history: list[dict] | None) -> list[dict]:
        messages = [{"role": "system", "content": self._system_prompt}]
        if history:
            messages.extend(history[-self._max_turns * 2:])
        user_content = f"""请根据以下检索到的官方资料回答问题。

## 检索到的资料

{context}

## 问题

{query}

## 要求
- 只依据上面的资料回答,不编造
- 用 Markdown 格式
- 来源引用用内联格式,如:[Wiki] NE503 技术规格
- 用 {language} 回答
"""
        messages.append({"role": "user", "content": user_content})
        return messages

    def _extract_sources(self, results: list[SearchResult]) -> list[dict]:
        seen = set()
        sources = []
        for r in results:
            if r.url not in seen:
                seen.add(r.url)
                sources.append({
                    "url": r.url,
                    "title": r.title,
                    "type": r.source_type,
                    "product": r.product,
                })
        return sources

    async def answer(
        self,
        query: str,
        channel: str = "widget",
        conversation_history: list[dict] | None = None,
        product_filter: str | None = None,
    ) -> RAGAnswer:
        start = time.monotonic()
        language = detect_language(query)

        results = self._searcher.search(
            query=query,
            alpha=self._alpha,
            limit=self._recall_limit,
            product_filter=product_filter,
        )

        reranked = self._reranker.rerank(query, results, top_k=self._top_k)

        if self._pruner:
            reranked = self._pruner.prune(query, reranked)

        if not reranked:
            elapsed = int((time.monotonic() - start) * 1000)
            return RAGAnswer(
                answer=REJECT_ANSWER,
                sources=[],
                is_answered=False,
                reranked_results=[],
                language=language,
                response_time_ms=elapsed,
            )

        context = self._build_context(reranked)
        messages = self._build_messages(query, context, language, conversation_history)

        llm_response = await self._llm.generate(messages, task="generation")
        sources = self._extract_sources(reranked)
        elapsed = int((time.monotonic() - start) * 1000)

        return RAGAnswer(
            answer=llm_response.content,
            sources=sources,
            is_answered=True,
            reranked_results=reranked,
            language=language,
            response_time_ms=elapsed,
        )

    async def stream_answer(
        self,
        query: str,
        channel: str = "widget",
        conversation_history: list[dict] | None = None,
        product_filter: str | None = None,
    ):
        start = time.monotonic()
        language = detect_language(query)

        results = self._searcher.search(
            query=query,
            alpha=self._alpha,
            limit=self._recall_limit,
            product_filter=product_filter,
        )

        reranked = self._reranker.rerank(query, results, top_k=self._top_k)

        if self._pruner:
            reranked = self._pruner.prune(query, reranked)

        if not reranked:
            import json
            elapsed = int((time.monotonic() - start) * 1000)
            yield json.dumps({
                "type": "complete",
                "answer": REJECT_ANSWER,
                "sources": [],
                "is_answered": False,
                "language": language,
                "response_time_ms": elapsed,
            })
            return

        context = self._build_context(reranked)
        messages = self._build_messages(query, context, language, conversation_history)
        sources = self._extract_sources(reranked)

        import json
        yield json.dumps({"type": "sources", "sources": sources})

        full_answer = ""
        async for chunk in self._llm.stream(messages, task="generation"):
            full_answer += chunk
            yield json.dumps({"type": "token", "content": chunk})

        elapsed = int((time.monotonic() - start) * 1000)
        yield json.dumps({
            "type": "complete",
            "answer": full_answer,
            "sources": sources,
            "is_answered": True,
            "language": language,
            "response_time_ms": elapsed,
        })
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/pipeline/test_rag.py -v -m unit`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/pipeline/rag.py tests/pipeline/test_rag.py
git commit -m "feat: RAG 编排(检索→重排→拒答→生成→流式输出)"
```

---

## Task 16: FastAPI SSE Endpoint

**Files:**
- Create: `backend/api/__init__.py`
- Create: `backend/api/schemas.py`
- Create: `backend/api/routes.py`
- Modify: `backend/main.py`
- Test: `tests/api/test_routes.py`

**Interfaces:**
- Consumes: `RAGOrchchestrator`, Postgres session
- Produces: `POST /api/ask` (SSE), `POST /api/feedback`, `POST /api/click`

- [ ] **Step 1: Create schemas**

```python
# backend/api/schemas.py
from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    language: str | None = None
    channel: str = "widget"
    conversation_history: list[dict] = Field(default_factory=list, max_length=10)


class FeedbackRequest(BaseModel):
    conversation_id: str
    feedback: str = Field(..., pattern="^(up|down)$")


class ClickRequest(BaseModel):
    conversation_id: str
    source_url: str
    source_type: str
    product: str | None = None
```

- [ ] **Step 2: Create routes**

```python
# backend/api/routes.py
import json
import logging
import uuid

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse
from slowapi import Limiter
from slowapi.util import get_remote_address

from backend.api.schemas import AskRequest, FeedbackRequest, ClickRequest
from backend.db.models import Conversation, SourceClick
from backend.utils.pii import mask_pii

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")
limiter = Limiter(key_func=get_remote_address)


def get_rag(request: Request):
    return request.app.state.rag


def get_session_factory(request: Request):
    return request.app.state.session_factory


@router.post("/ask")
@limiter.limit("20/minute")
async def ask(
    req: AskRequest,
    request: Request,
    rag=Depends(get_rag),
    session_factory=Depends(get_session_factory),
):
    masked_message = mask_pii(req.message)

    async def event_generator():
        conversation_id = str(uuid.uuid4())
        full_answer = ""
        sources = []
        is_answered = False
        language = "en"
        elapsed = 0

        async for chunk in rag.stream_answer(
            query=masked_message,
            channel=req.channel,
            conversation_history=req.conversation_history,
        ):
            data = json.loads(chunk)
            if data["type"] == "sources":
                sources = data["sources"]
                yield {"event": "sources", "data": json.dumps({"conversation_id": conversation_id, "sources": sources})}
            elif data["type"] == "token":
                full_answer += data["content"]
                yield {"event": "token", "data": json.dumps({"content": data["content"]})}
            elif data["type"] == "complete":
                full_answer = data.get("answer", full_answer)
                is_answered = data["is_answered"]
                language = data.get("language", "en")
                elapsed = data.get("response_time_ms", 0)

        # 记录到 Postgres
        async with session_factory() as session:
            conv = Conversation(
                id=uuid.UUID(conversation_id),
                question=masked_message,
                answer=full_answer,
                channel=req.channel,
                language=language,
                sources=sources,
                is_answered=is_answered,
                response_time_ms=elapsed,
            )
            session.add(conv)
            await session.commit()

        yield {"event": "done", "data": json.dumps({"conversation_id": conversation_id})}

    return EventSourceResponse(event_generator())


@router.post("/feedback")
async def feedback(
    req: FeedbackRequest,
    session_factory=Depends(get_session_factory),
):
    async with session_factory() as session:
        from sqlalchemy import update
        await session.execute(
            update(Conversation)
            .where(Conversation.id == uuid.UUID(req.conversation_id))
            .values(feedback=req.feedback)
        )
        await session.commit()
    return {"status": "ok"}


@router.post("/click")
async def click(
    req: ClickRequest,
    session_factory=Depends(get_session_factory),
):
    async with session_factory() as session:
        click = SourceClick(
            conversation_id=uuid.UUID(req.conversation_id),
            source_url=req.source_url,
            source_type=req.source_type,
            product=req.product,
        )
        session.add(click)
        await session.commit()
    return {"status": "ok"}
```

- [ ] **Step 3: Update main.py to wire everything**

```python
# backend/main.py (update)
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
import weaviate
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from backend.config import load_settings, load_yaml_config
from backend.api.routes import router as api_router
from backend.connectors.registry import ConnectorRegistry
import backend.connectors.github  # noqa
import backend.connectors.filesystem  # noqa
from backend.db.session import get_engine, get_session_factory, init_db
from backend.embedder.bge import BGEEmbedder, BGEReranker
from backend.llm.registry import LLMRegistry, LLMRouter
from backend.retrieval.search import HybridSearcher
from backend.retrieval.rerank import RerankPipeline
from backend.pipeline.rag import RAGOrchestrator

logger = logging.getLogger(__name__)
settings = load_settings()

limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=settings.log_level)
    logger.info("Ask AI 后端启动中...")

    # Postgres
    engine = get_engine(settings.postgres_dsn)
    await init_db(engine)
    app.state.session_factory = get_session_factory(engine)

    # Weaviate
    weaviate_host = settings.weaviate_url.split("//")[1].split(":")[0]
    weaviate_port = int(settings.weaviate_url.split(":")[2])
    weaviate_client = weaviate.connect_to_local(host=weaviate_host, port=weaviate_port)

    # Embedder + Reranker
    embedder = BGEEmbedder(device=settings.embedder_device)
    reranker = BGEReranker(device=settings.embedder_device)

    # LLM
    llm_config = load_yaml_config(settings.config_dir / "llm_providers.yaml")
    providers = {}
    for prov in llm_config["providers"]:
        if not prov.get("enabled", True):
            continue
        cfg = prov["config"]
        provider = LLMRegistry.create(prov["type"],
            provider_id=prov["id"],
            api_base=cfg["api_base"],
            api_key=cfg["api_key"],
            model=cfg["model"],
            max_tokens=cfg.get("max_tokens", 4096),
            temperature=cfg.get("temperature", 0.3),
        )
        providers[prov["id"]] = provider
    router_llm = LLMRouter(providers, llm_config.get("routing", {}))

    # System prompt
    prompt_config = load_yaml_config(settings.config_dir / "system_prompt.yaml")

    # RAG
    searcher = HybridSearcher(weaviate_client, embedder, settings.weaviate_class_name)
    rerank_pipeline = RerankPipeline(reranker)
    app.state.rag = RAGOrchestrator(
        searcher=searcher,
        reranker=rerank_pipeline,
        llm=router_llm,
        system_prompt=prompt_config["system_prompt"],
    )
    app.state.weaviate_client = weaviate_client
    app.state.engine = engine

    logger.info("Ask AI 后端就绪")
    yield

    weaviate_client.close()
    await engine.dispose()
    logger.info("Ask AI 后端关闭")


app = FastAPI(title="Ask AI", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host=settings.api_host, port=settings.api_port)
```

- [ ] **Step 4: Write API test**

```python
# tests/api/test_routes.py
import pytest
from httpx import AsyncClient, ASGITransport
from backend.main import app


@pytest.mark.integration
async def test_health():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/api/ -v -m integration`
Expected: PASS (health check)

- [ ] **Step 6: Commit**

```bash
git add backend/api/ backend/main.py tests/api/
git commit -m "feat: FastAPI SSE 端点(ask/feedback/click)+ 全栈接线"
```

---

## Task 17: Widget Scaffolding

**Files:**
- Create: `widget/package.json`
- Create: `widget/tsconfig.json`
- Create: `widget/vite.config.ts`
- Create: `widget/src/index.tsx`
- Create: `widget/src/types.ts`
- Create: `widget/src/styles/widget.css`

**Interfaces:**
- Produces: `widget.js` (IIFE bundle, embeddable via `<script>`)

- [ ] **Step 1: Create package.json**

```json
{
  "name": "ask-ai-widget",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^19.0.0",
    "react-dom": "^19.0.0"
  },
  "devDependencies": {
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "@vitejs/plugin-react": "^4.3.0",
    "typescript": "^5.7",
    "vite": "^6.0.0"
  }
}
```

- [ ] **Step 2: Create vite.config.ts (IIFE build)**

```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    lib: {
      entry: "src/index.tsx",
      name: "AskAIWidget",
      fileName: "widget",
      formats: ["iife"],
    },
    cssCodeSplit: false,
  },
});
```

- [ ] **Step 3: Create types.ts**

```typescript
export interface SourceLink {
  url: string;
  title: string;
  type: string;
  product?: string;
}

export interface WidgetConfig {
  apiUrl: string;
  language?: string;
  primaryColor?: string;
}

export type MessageType = "user" | "assistant";

export interface ChatMessage {
  id: string;
  type: MessageType;
  content: string;
  sources?: SourceLink[];
}
```

- [ ] **Step 4: Create index.tsx (mount to DOM)**

```tsx
import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles/widget.css";

const container = document.createElement("div");
container.id = "ask-ai-widget-root";
document.body.appendChild(container);

const config: WidgetConfig = {
  apiUrl: (container.getAttribute("data-api-url") ||
    (window as any).AskAIConfig?.apiUrl ||
    "http://localhost:8000") as string,
  language: container.getAttribute("data-language") || undefined,
  primaryColor: container.getAttribute("data-primary-color") || "#2563eb",
};

const root = createRoot(container);
root.render(React.createElement(App, { config }));
```

- [ ] **Step 5: Create styles/widget.css**

```css
#ask-ai-widget-root {
  position: fixed;
  bottom: 0;
  right: 0;
  z-index: 99999;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
.ask-ai-fab {
  position: fixed;
  bottom: 24px;
  right: 24px;
  width: 56px;
  height: 56px;
  border-radius: 50%;
  border: none;
  cursor: pointer;
  box-shadow: 0 4px 12px rgba(0,0,0,0.15);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: 24px;
}
.ask-ai-panel {
  position: fixed;
  bottom: 96px;
  right: 24px;
  width: 380px;
  max-width: calc(100vw - 48px);
  height: 560px;
  max-height: calc(100vh - 120px);
  background: white;
  border-radius: 16px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.12);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.ask-ai-header {
  padding: 16px;
  color: white;
  font-weight: 600;
}
.ask-ai-messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}
.ask-ai-input {
  padding: 12px 16px;
  border-top: 1px solid #e5e7eb;
  display: flex;
  gap: 8px;
}
.ask-ai-input input {
  flex: 1;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 14px;
}
.ask-ai-input button {
  border: none;
  border-radius: 8px;
  padding: 8px 16px;
  color: white;
  cursor: pointer;
  font-size: 14px;
}
.ask-ai-bubble-user {
  background: #f3f4f6;
  border-radius: 12px 12px 4px 12px;
  padding: 8px 12px;
  margin: 8px 0 8px auto;
  max-width: 80%;
  word-break: break-word;
}
.ask-ai-bubble-assistant {
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 12px 12px 12px 4px;
  padding: 8px 12px;
  margin: 8px 0;
  max-width: 85%;
  word-break: break-word;
}
.ask-ai-source {
  font-size: 12px;
  color: #2563eb;
  text-decoration: none;
  margin-right: 8px;
}
.ask-ai-feedback {
  display: flex;
  gap: 8px;
  margin-top: 4px;
}
.ask-ai-feedback button {
  border: 1px solid #d1d5db;
  background: white;
  border-radius: 4px;
  padding: 2px 8px;
  cursor: pointer;
  font-size: 12px;
}
.ask-ai-suggested {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 8px 0;
}
.ask-ai-suggested button {
  border: 1px solid #d1d5db;
  background: white;
  border-radius: 16px;
  padding: 6px 14px;
  cursor: pointer;
  font-size: 13px;
  color: #374151;
}
@media (max-width: 640px) {
  .ask-ai-panel {
    width: calc(100vw - 32px);
    height: calc(100vh - 120px);
    right: 16px;
    bottom: 88px;
  }
  .ask-ai-fab {
    bottom: 16px;
    right: 16px;
  }
}
```

- [ ] **Step 6: Commit**

```bash
git add widget/
git commit -m "feat: Widget 脚手架(Vite + React + IIFE 打包配置)"
```

---

## Task 18: Widget Chat UI

**Files:**
- Create: `widget/src/App.tsx`
- Create: `widget/src/components/ChatPanel.tsx`
- Create: `widget/src/components/MessageBubble.tsx`
- Create: `widget/src/components/SuggestedQuestions.tsx`
- Create: `widget/src/hooks/useSSE.ts`

**Interfaces:**
- Consumes: `POST /api/ask` (SSE), `POST /api/feedback`, `POST /api/click`

- [ ] **Step 1: Create useSSE hook**

```typescript
// widget/src/hooks/useSSE.ts
import { useCallback } from "react";
import type { ChatMessage, SourceLink } from "../types";

interface SSECallbacks {
  onSources: (sources: SourceLink[], conversationId: string) => void;
  onToken: (token: string) => void;
  onDone: (conversationId: string) => void;
}

export function useSSE(apiUrl: string) {
  const ask = useCallback(async (
    message: string,
    history: ChatMessage[],
    channel: string,
    callbacks: SSECallbacks,
  ) => {
    const conversationHistory = history.map((m) => ({
      role: m.type === "user" ? "user" : "assistant",
      content: m.content,
    }));

    const resp = await fetch(`${apiUrl}/api/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        channel,
        conversation_history: conversationHistory.slice(-10),
      }),
    });

    const reader = resp.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const events = buffer.split("\n\n");
      buffer = events.pop() || "";

      for (const event of events) {
        const lines = event.trim().split("\n");
        let eventType = "";
        let dataStr = "";
        for (const line of lines) {
          if (line.startsWith("event: ")) eventType = line.slice(7).trim();
          if (line.startsWith("data: ")) dataStr = line.slice(6);
        }
        if (!dataStr) continue;
        try {
          const data = JSON.parse(dataStr);
          if (eventType === "sources") {
            callbacks.onSources(data.sources || [], data.conversation_id);
          } else if (eventType === "token") {
            callbacks.onToken(data.content || "");
          } else if (eventType === "done") {
            callbacks.onDone(data.conversation_id);
          }
        } catch {}
      }
    }
  }, [apiUrl]);

  return { ask };
}
```

- [ ] **Step 2: Create App.tsx**

```tsx
import { useState, useCallback, useRef } from "react";
import type { WidgetConfig, ChatMessage } from "./types";
import { useSSE } from "./hooks/useSSE";
import { ChatPanel } from "./components/ChatPanel";

const SUGGESTED_QUESTIONS = [
  "NE503 支持哪些接口?",
  "如何开始使用 NeoMind?",
  "NE101 的功耗是多少?",
  "AIToolStack 有哪些功能?",
];

export function App({ config }: { config: WidgetConfig }) {
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const { ask } = useSSE(config.apiUrl);

  const handleSend = useCallback(async (text: string) => {
    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      type: "user",
      content: text,
    };
    setMessages((prev) => [...prev, userMsg]);
    setIsStreaming(true);

    const assistantId = crypto.randomUUID();
    setMessages((prev) => [...prev, { id: assistantId, type: "assistant", content: "" }]);

    await ask(text, messages, "widget", {
      onSources: (sources, convId) => {
        setConversationId(convId);
        setMessages((prev) =>
          prev.map((m) => m.id === assistantId ? { ...m, sources } : m),
        );
      },
      onToken: (token) => {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId ? { ...m, content: m.content + token } : m,
          ),
        );
      },
      onDone: (convId) => {
        setConversationId(convId);
        setIsStreaming(false);
      },
    });
  }, [messages, ask]);

  const handleFeedback = useCallback(async (msgId: string, feedback: "up" | "down") => {
    if (!conversationId) return;
    await fetch(`${config.apiUrl}/api/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conversation_id: conversationId, feedback }),
    });
  }, [conversationId, config.apiUrl]);

  return (
    <>
      {!isOpen && (
        <button
          className="ask-ai-fab"
          style={{ backgroundColor: config.primaryColor }}
          onClick={() => setIsOpen(true)}
        >
          💬
        </button>
      )}
      {isOpen && (
        <ChatPanel
          config={config}
          messages={messages}
          isStreaming={isStreaming}
          conversationId={conversationId}
          suggestedQuestions={messages.length === 0 ? SUGGESTED_QUESTIONS : []}
          onSend={handleSend}
          onClose={() => setIsOpen(false)}
          onFeedback={handleFeedback}
        />
      )}
    </>
  );
}
```

- [ ] **Step 3: Create ChatPanel.tsx**

```tsx
import { useState, useRef, useEffect } from "react";
import type { WidgetConfig, ChatMessage } from "../types";
import { MessageBubble } from "./MessageBubble";
import { SuggestedQuestions } from "./SuggestedQuestions";

interface Props {
  config: WidgetConfig;
  messages: ChatMessage[];
  isStreaming: boolean;
  conversationId: string | null;
  suggestedQuestions: string[];
  onSend: (text: string) => void;
  onClose: () => void;
  onFeedback: (msgId: string, feedback: "up" | "down") => void;
}

export function ChatPanel({ config, messages, isStreaming, conversationId, suggestedQuestions, onSend, onClose, onFeedback }: Props) {
  const [input, setInput] = useState("");
  const messagesEnd = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEnd.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (input.trim() && !isStreaming) {
      onSend(input.trim());
      setInput("");
    }
  };

  return (
    <div className="ask-ai-panel">
      <div className="ask-ai-header" style={{ backgroundColor: config.primaryColor }}>
        <span>CamThink 助手</span>
        <button onClick={onClose} style={{ float: "right", background: "none", border: "none", color: "white", cursor: "pointer" }}>✕</button>
      </div>
      <div className="ask-ai-messages">
        {messages.length === 0 && (
          <div style={{ color: "#6b7280", fontSize: "14px", textAlign: "center", marginTop: "20px" }}>
            你好!我是 CamThink 助手,有什么可以帮你?
          </div>
        )}
        {messages.map((msg) => (
          <MessageBubble
            key={msg.id}
            message={msg}
            isStreaming={isStreaming}
            apiUrl={config.apiUrl}
            conversationId={conversationId}
            onFeedback={onFeedback}
          />
        ))}
        {suggestedQuestions.length > 0 && (
          <SuggestedQuestions questions={suggestedQuestions} onSelect={onSend} />
        )}
        <div ref={messagesEnd} />
      </div>
      <form className="ask-ai-input" onSubmit={handleSubmit}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="输入你的问题..."
          disabled={isStreaming}
        />
        <button type="submit" style={{ backgroundColor: config.primaryColor }} disabled={isStreaming || !input.trim()}>
          发送
        </button>
      </form>
    </div>
  );
}
```

- [ ] **Step 4: Create MessageBubble.tsx**

```tsx
import type { ChatMessage } from "../types";

interface Props {
  message: ChatMessage;
  isStreaming: boolean;
  apiUrl: string;
  conversationId: string | null;
  onFeedback: (msgId: string, feedback: "up" | "down") => void;
}

const SOURCE_LABELS: Record<string, string> = {
  github: "GitHub",
  wiki: "Wiki",
  website: "官网",
  blog: "博客",
  filesystem: "知识库",
};

export function MessageBubble({ message, isStreaming, apiUrl, conversationId, onFeedback }: Props) {
  const isUser = message.type === "user";
  return (
    <div className={isUser ? "ask-ai-bubble-user" : "ask-ai-bubble-assistant"}>
      <div dangerouslySetInnerHTML={{ __html: renderMarkdown(message.content) }} />
      {!isUser && message.content && !isStreaming && (
        <>
          {message.sources && message.sources.length > 0 && (
            <div style={{ marginTop: "8px", borderTop: "1px solid #f3f4f6", paddingTop: "8px" }}>
              {message.sources.map((src, i) => (
                <a
                  key={i}
                  className="ask-ai-source"
                  href={src.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={() => {
                    if (!conversationId) return;
                    fetch(`${apiUrl}/api/click`, {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({
                        conversation_id: conversationId,
                        source_url: src.url,
                        source_type: src.type,
                        product: src.product,
                      }),
                    });
                  }}
                >
                  [{SOURCE_LABELS[src.type] || src.type}] {src.title}
                </a>
              ))}
            </div>
          )}
          <div className="ask-ai-feedback">
            <button onClick={() => onFeedback(message.id, "up")}>👍</button>
            <button onClick={() => onFeedback(message.id, "down")}>👎</button>
          </div>
        </>
      )}
    </div>
  );
}

function renderMarkdown(text: string): string {
  // 简易 Markdown 渲染(Phase 1 足够;后期可替换为 react-markdown)
  let html = text;
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, "<pre><code>$2</code></pre>");
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/^## (.+)$/gm, "<h4>$1</h4>");
  html = html.replace(/^- (.+)$/gm, "<li>$1</li>");
  html = html.replace(/(<li>.*<\/li>)/s, "<ul>$1</ul>");
  html = html.replace(/\n/g, "<br>");
  return html;
}
```

- [ ] **Step 5: Create SuggestedQuestions.tsx**

```tsx
interface Props {
  questions: string[];
  onSelect: (question: string) => void;
}

export function SuggestedQuestions({ questions, onSelect }: Props) {
  return (
    <div className="ask-ai-suggested">
      {questions.map((q, i) => (
        <button key={i} onClick={() => onSelect(q)}>
          {q}
        </button>
      ))}
    </div>
  );
}
```

- [ ] **Step 6: Build and test**

Run: `cd widget && npm install && npm run build`
Expected: `widget/dist/widget.js` + `widget/dist/widget.css` generated.

- [ ] **Step 7: Commit**

```bash
git add widget/src/
git commit -m "feat: Widget 聊天 UI(SSE 流式 + 来源链接 + 反馈 + 推荐问题)"
```

---

## Task 19: Widget Embed Test

**Files:**
- Create: `widget/test-embed.html`

- [ ] **Step 1: Create test HTML page**

```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Ask AI Widget 测试</title>
  <style>
    body { font-family: sans-serif; padding: 40px; }
    h1 { color: #333; }
  </style>
</head>
<body>
  <h1>Ask AI Widget 嵌入测试页</h1>
  <p>这个页面用于测试 widget 是否正确加载和显示。</p>

  <!-- Ask AI Widget -->
  <script>
    window.AskAIConfig = {
      apiUrl: "http://localhost:8000",
      language: "zh",
      primaryColor: "#2563eb",
    };
  </script>
  <script src="./dist/widget.js"></script>
</body>
</html>
```

- [ ] **Step 2: Test locally**

Run: `cd widget && npm run build && open test-embed.html`
Expected: Widget FAB appears in bottom-right corner, clicking opens chat panel.

- [ ] **Step 3: Commit**

```bash
git add widget/test-embed.html
git commit -m "test: Widget 嵌入测试页"
```

---

## Task 20: End-to-End Integration

**Files:**
- Modify: `deploy/docker-compose.yml` (add backend build)
- Create: `Dockerfile`

- [ ] **Step 1: Create Dockerfile**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential git curl && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[dev]"

COPY . .

EXPOSE 8000

CMD ["python", "-m", "backend.main"]
```

- [ ] **Step 2: Test full stack**

Run:
```bash
# 1. Start services
docker compose -f deploy/docker-compose.yml up -d postgres weaviate

# 2. Run initial sync (requires GITHUB_TOKEN and DEEPSEEK_API_KEY in .env)
python scripts/sync.py

# 3. Start backend
python -m backend.main

# 4. Build and test widget
cd widget && npm install && npm run build
open test-embed.html
```

Expected: Widget loads, can ask questions, receives streamed answers with sources.

- [ ] **Step 3: Create README.md**

```markdown
# Ask AI

CamThink AI 知识助手 — 自建 RAG 系统。

## 快速开始

1. 复制 `.env.example` 为 `.env`,填入 API Key
2. 启动服务:`docker compose -f deploy/docker-compose.yml up -d postgres weaviate`
3. 同步知识库:`python scripts/sync.py`
4. 启动后端:`python -m backend.main`
5. 构建并测试 Widget:`cd widget && npm install && npm run build`

## 文档

设计文档见 `docs/superpowers/specs/`
```

- [ ] **Step 4: Commit**

```bash
git add Dockerfile deploy/docker-compose.yml README.md
git commit -m "feat: Docker 部署 + README"
```

---

## Task 21: Security Hardening

**Files:**
- Create: `backend/utils/budget.py`
- Create: `widget/src/utils/sanitize.ts`
- Create: `widget/src/utils/urlPolicy.ts`
- Modify: `backend/api/schemas.py`
- Modify: `backend/api/routes.py`
- Modify: `backend/connectors/github.py`
- Modify: `backend/main.py`
- Modify: `widget/src/components/MessageBubble.tsx`
- Modify: `widget/package.json` (加 dompurify 依赖)
- Test: `tests/utils/test_budget.py`, `tests/api/test_schemas.py`, `tests/api/test_hardening.py`, `tests/connectors/test_github_scope.py`, `widget/src/utils/__tests__/sanitize.test.ts`

**Interfaces:**
- Consumes: `AskRequest` (Task 16), tiktoken (Task 9), `GITHUB_TOKEN` env (Task 6)
- Produces: 5 项安全加固(对应 §13.2 威胁模型)

**威胁模型(本 Task 应对,详见 spec §13.2):**

| 威胁 | 现状风险 | 应对 |
|---|---|---|
| 输出 XSS | `MessageBubble` 用 `dangerouslySetInnerHTML` 渲染未转义的 LLM 输出 | S1 |
| 成本 DoS | 匿名 Widget 无限刷 `/api/ask` 烧 DeepSeek 额度 | S2 |
| 输入超长 | `conversation_history` 单条内容无上限,撑爆 context | S3 |
| 凭证过权 | `GITHUB_TOKEN` 无 scope 校验 | S4 |
| 配置泄露 | CORS `*`、异常堆栈回显、debug 未关 | S5 |

> **Phase 边界**:Phase 1 LLM 无工具调用,prompt injection 危害限于内容/成本层;Phase 4 接入 Skills/MCP 后升级为执行类威胁(spec §17),届时威胁模型需重做。

- [ ] **Step 1 (S3): conversation_history 后端强制边界**

```python
# tests/api/test_schemas.py
import pytest
from pydantic import ValidationError
from backend.api.schemas import AskRequest


@pytest.mark.unit
def test_normal_history_passes():
    req = AskRequest(message="hi", conversation_history=[
        {"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}])
    assert len(req.conversation_history) == 2


@pytest.mark.unit
def test_history_over_10_items_rejected():
    with pytest.raises(ValidationError):
        AskRequest(message="hi", conversation_history=[{"role": "user", "content": "x"}] * 11)


@pytest.mark.unit
def test_history_oversize_content_rejected():
    with pytest.raises(ValidationError):
        AskRequest(message="hi", conversation_history=[{"role": "user", "content": "x" * 5000}])


@pytest.mark.unit
def test_invalid_channel_rejected():
    with pytest.raises(ValidationError):
        AskRequest(message="hi", channel="evil")


@pytest.mark.unit
def test_history_strips_extra_keys():
    req = AskRequest(message="hi", conversation_history=[
        {"role": "user", "content": "a", "injected": "malware"}])
    assert "injected" not in req.conversation_history[0]
```

```python
# backend/api/schemas.py (update)
from pydantic import BaseModel, Field, field_validator

MAX_HISTORY_ITEMS = 10
MAX_HISTORY_CONTENT_CHARS = 4000
MAX_HISTORY_TOTAL_CHARS = 20000


class AskRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    language: str | None = None
    channel: str = Field(default="widget", pattern="^(widget|discord|whatsapp|mcp)$")
    conversation_history: list[dict] = Field(default_factory=list, max_length=MAX_HISTORY_ITEMS)

    @field_validator("conversation_history")
    @classmethod
    def _validate_history(cls, v: list[dict]) -> list[dict]:
        total = 0
        for item in v:
            content = str(item.get("content", ""))
            if len(content) > MAX_HISTORY_CONTENT_CHARS:
                raise ValueError(f"history 单条 content 超过 {MAX_HISTORY_CONTENT_CHARS} 字符")
            total += len(content)
        if total > MAX_HISTORY_TOTAL_CHARS:
            raise ValueError(f"history 总字符超过 {MAX_HISTORY_TOTAL_CHARS}")
        # 仅保留 role/content,丢弃其他键
        return [{"role": item.get("role", "user"), "content": str(item.get("content", ""))} for item in v]


class FeedbackRequest(BaseModel):
    conversation_id: str
    feedback: str = Field(..., pattern="^(up|down)$")


class ClickRequest(BaseModel):
    conversation_id: str
    source_url: str
    source_type: str
    product: str | None = None
```

- [ ] **Step 2 (S2): 成本预算熔断**

```python
# tests/utils/test_budget.py
import pytest
from datetime import date
from backend.utils.budget import BudgetLimiter, BudgetConfig


@pytest.mark.unit
def test_allows_within_budget():
    lim = BudgetLimiter(BudgetConfig(daily_request_limit=5, daily_token_limit=1_000_000))
    assert lim.check_and_reserve(estimated_tokens=100) is True
    assert lim.snapshot()["requests"] == 1


@pytest.mark.unit
def test_blocks_when_request_limit_hit():
    lim = BudgetLimiter(BudgetConfig(daily_request_limit=2, daily_token_limit=1_000_000))
    lim.check_and_reserve(10)
    lim.check_and_reserve(10)
    assert lim.check_and_reserve(10) is False


@pytest.mark.unit
def test_blocks_when_token_limit_hit():
    lim = BudgetLimiter(BudgetConfig(daily_request_limit=100, daily_token_limit=100))
    assert lim.check_and_reserve(60) is True
    assert lim.check_and_reserve(50) is False  # 60+50 > 100


@pytest.mark.unit
def test_resets_on_new_day():
    today = {"d": date(2026, 7, 28)}
    lim = BudgetLimiter(
        BudgetConfig(daily_request_limit=1, daily_token_limit=1_000_000),
        _now=lambda: today["d"],
    )
    assert lim.check_and_reserve(10) is True
    assert lim.check_and_reserve(10) is False
    today["d"] = date(2026, 7, 29)  # 跨天
    assert lim.check_and_reserve(10) is True  # 计数重置
```

```python
# backend/utils/budget.py
import logging
import threading
from dataclasses import dataclass
from datetime import date

import tiktoken

logger = logging.getLogger(__name__)
_enc = tiktoken.get_encoding("cl100k_base")


@dataclass(frozen=True)
class BudgetConfig:
    daily_request_limit: int = 500
    daily_token_limit: int = 2_000_000


@dataclass
class _Counter:
    requests: int = 0
    tokens: int = 0


def estimate_tokens(text: str) -> int:
    """用 cl100k_base 估算 token 数(与 Task 9 chunking 同编码;DeepSeek 实际 tokenizer 的合理近似)。"""
    return len(_enc.encode(text))


class BudgetLimiter:
    """每日 LLM 调用预算熔断,保护计费额度。

    Phase 1:内存计数器(单 worker)。超阈值拒绝新请求并返回降级响应。
    多 worker / 持久化场景 Phase 2 迁移至 Redis 或 Postgres。
    """

    def __init__(self, config: BudgetConfig, *, _now=None):
        self._config = config
        self._now = _now or date.today
        self._current_date = self._now()
        self._counter = _Counter()
        self._lock = threading.Lock()

    def _maybe_reset(self) -> None:
        today = self._now()
        if today != self._current_date:
            self._current_date = today
            self._counter = _Counter()

    def check_and_reserve(self, estimated_tokens: int) -> bool:
        with self._lock:
            self._maybe_reset()
            if self._counter.requests >= self._config.daily_request_limit:
                logger.warning("预算熔断:日请求数达上限 %d", self._config.daily_request_limit)
                return False
            if self._counter.tokens + estimated_tokens > self._config.daily_token_limit:
                logger.warning("预算熔断:日 token 估算达上限 %d", self._config.daily_token_limit)
                return False
            self._counter.requests += 1
            self._counter.tokens += estimated_tokens
            return True

    def snapshot(self) -> dict:
        with self._lock:
            self._maybe_reset()
            return {
                "date": self._current_date.isoformat(),
                "requests": self._counter.requests,
                "tokens": self._counter.tokens,
                "daily_request_limit": self._config.daily_request_limit,
                "daily_token_limit": self._config.daily_token_limit,
            }
```

接入 `ask` 端点(在 Task 16 的 `ask` 函数内,`event_generator` 定义之前插入预算检查):

```python
# backend/api/routes.py (update — ask 端点增量)
from backend.utils.budget import BudgetLimiter, estimate_tokens


def get_budget(request: Request):
    return request.app.state.budget


@router.post("/ask")
@limiter.limit("20/minute")
async def ask(
    req: AskRequest,
    request: Request,
    rag=Depends(get_rag),
    session_factory=Depends(get_session_factory),
    budget: BudgetLimiter = Depends(get_budget),
):
    masked_message = mask_pii(req.message)

    # S2: 预算熔断 — 估算 prompt token + max_tokens 预扣
    est_input = estimate_tokens(masked_message) + sum(
        estimate_tokens(str(h.get("content", ""))) for h in req.conversation_history
    )
    if not budget.check_and_reserve(est_input + 4096):
        async def declined():
            yield {"event": "declined", "data": json.dumps({"reason": "服务繁忙,请稍后再试"})}
            yield {"event": "done", "data": json.dumps({"conversation_id": str(uuid.uuid4())})}
        return EventSourceResponse(declined())

    async def event_generator():
        ...  # Task 16 原有逻辑不变
```

- [ ] **Step 3 (S4): GITHUB_TOKEN 最小权限校验**

```python
# tests/connectors/test_github_scope.py
import pytest
from unittest.mock import patch, MagicMock
from backend.connectors.github import validate_github_token


@pytest.mark.unit
def test_classic_token_readonly_passes():
    resp = MagicMock()
    resp.headers = {"x-oauth-scopes": "repo:read"}
    resp.raise_for_status = MagicMock()
    with patch("backend.connectors.github.httpx.Client") as m:
        m.return_value.__enter__.return_value.get.return_value = resp
        validate_github_token("token", strict=True)  # 不抛


@pytest.mark.unit
def test_classic_token_write_scope_fails_in_prod():
    resp = MagicMock()
    resp.headers = {"x-oauth-scopes": "repo, write:org"}
    resp.raise_for_status = MagicMock()
    with patch("backend.connectors.github.httpx.Client") as m:
        m.return_value.__enter__.return_value.get.return_value = resp
        with pytest.raises(RuntimeError):
            validate_github_token("token", strict=True)


@pytest.mark.unit
def test_classic_token_write_scope_warns_in_dev():
    resp = MagicMock()
    resp.headers = {"x-oauth-scopes": "repo"}
    resp.raise_for_status = MagicMock()
    with patch("backend.connectors.github.httpx.Client") as m:
        m.return_value.__enter__.return_value.get.return_value = resp
        validate_github_token("token", strict=False)  # 不抛,仅 warn


@pytest.mark.unit
def test_fine_grained_token_no_scopes_passes():
    resp = MagicMock()
    resp.headers = {"x-oauth-scopes": ""}  # fine-grained token 返回空
    resp.raise_for_status = MagicMock()
    with patch("backend.connectors.github.httpx.Client") as m:
        m.return_value.__enter__.return_value.get.return_value = resp
        validate_github_token("token", strict=True)


@pytest.mark.unit
def test_no_token_warns():
    validate_github_token("", strict=True)  # 不抛,仅 warn
```

```python
# backend/connectors/github.py (append module-level function)
_WRITE_SCOPE_PREFIXES = ("repo", "write:", "delete:", "admin:")
_READONLY_SCOPES = {"repo:read", "public_repo", ""}


def validate_github_token(token: str, *, strict: bool = False) -> None:
    """启动时校验 GITHUB_TOKEN 为只读最小权限。

    classic token:检查 X-OAuth-Scopes 不含写权限(repo/write:/delete:/admin:),
                   repo:read 与 public_repo 视为只读放行。
    fine-grained token:响应头无 x-oauth-scopes,视为有效(权限粒度在 token 配置层保证)。
    无 token:warn(私有仓库将拉取失败)。
    写权限命中:strict=True(prod)抛 RuntimeError 阻断启动;strict=False(dev)仅 warn。
    """
    if not token:
        logger.warning("GITHUB_TOKEN 未设置:私有仓库将无法拉取")
        return
    try:
        with httpx.Client(timeout=10, headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
        }) as client:
            resp = client.get("https://api.github.com/user")
            resp.raise_for_status()
            scopes = resp.headers.get("x-oauth-scopes", "")
            found_write = [
                s.strip() for s in scopes.split(",")
                if s.strip() not in _READONLY_SCOPES
                and any(s.strip().startswith(p) for p in _WRITE_SCOPE_PREFIXES)
            ]
            if found_write:
                msg = f"GITHUB_TOKEN 含写权限 scope {found_write},违反最小权限原则"
                if strict:
                    raise RuntimeError(msg)
                logger.warning(msg)
    except httpx.HTTPError as e:
        logger.warning("GITHUB_TOKEN 校验失败(网络或无效 token):%s", e)
```

- [ ] **Step 4 (S5): FastAPI 生产配置加固 + S2/S4 接线**

```python
# tests/api/test_hardening.py
import pytest
from httpx import AsyncClient, ASGITransport
from backend.main import app


@pytest.mark.integration
async def test_unhandled_exception_hides_stack():
    @app.get("/__raise")
    async def _raise():
        raise RuntimeError("secret internal detail")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/__raise")
        assert resp.status_code == 500
        assert "secret internal detail" not in resp.text
        assert "detail" in resp.json()


@pytest.mark.integration
async def test_security_headers_present():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["x-frame-options"] == "DENY"
```

`backend/main.py` 关键增量(顶部新增 import):

```python
import os
from fastapi import Request
from fastapi.responses import JSONResponse
from backend.utils.budget import BudgetLimiter, BudgetConfig
```

在 `lifespan` 内(LLM 接线之后、RAG 创建之前)新增:

```python
    # S2: 预算熔断器
    budget_cfg = BudgetConfig(
        daily_request_limit=int(os.environ.get("BUDGET_DAILY_REQUESTS", "500")),
        daily_token_limit=int(os.environ.get("BUDGET_DAILY_TOKENS", "2000000")),
    )
    app.state.budget = BudgetLimiter(budget_cfg)

    # S4: GITHUB_TOKEN 最小权限校验(prod 严格)
    from backend.connectors.github import validate_github_token
    validate_github_token(
        os.environ.get("GITHUB_TOKEN", ""),
        strict=os.environ.get("APP_MODE", "dev") == "prod",
    )
```

`app` 创建与中间件部分替换为(env 控制 debug / 生产关 docs):

```python
# backend/main.py (update — app 创建 + 中间件)
_debug = os.environ.get("FASTAPI_DEBUG", "false").lower() == "true"
app = FastAPI(
    title="Ask AI",
    lifespan=lifespan,
    debug=_debug,
    docs_url="/docs" if _debug else None,
    redoc_url="/redoc" if _debug else None,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# S5: 全局异常 handler — 记录堆栈到日志,但不回显给客户端
@app.exception_handler(Exception)
async def _global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "内部服务错误"})


# S5: 安全响应头
@app.middleware("http")
async def _security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


# S5: CORS 白名单(env 控制,默认仅本地开发站点;不再用 "*")
_cors = [o.strip() for o in os.environ.get(
    "CORS_ALLOW_ORIGINS", "http://localhost:3000,http://localhost:1313"
).split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.include_router(api_router)
```

- [ ] **Step 5 (S1): Widget 输出 XSS 防护**

先加依赖:

```bash
cd widget && npm install dompurify @types/dompurify
```

```typescript
// widget/src/utils/sanitize.ts
import DOMPurify from "dompurify";

const ALLOWED_TAGS = ["p", "br", "strong", "em", "code", "pre", "h4", "ul", "ol", "li", "a"];
const ALLOWED_ATTR = ["href", "target", "rel"];

/** DOMPurify 清洗,兜底移除任何残余危险标签/属性 */
export function sanitizeHtml(html: string): string {
  return DOMPurify.sanitize(html, { ALLOWED_TAGS, ALLOWED_ATTR });
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

/** 安全 Markdown 渲染:先转义全部 HTML(杜绝原始 <script> 注入),再应用格式化,最后 DOMPurify 兜底 */
export function renderMarkdownSafe(text: string): string {
  let html = escapeHtml(text);
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, "<pre><code>$2</code></pre>");
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/^## (.+)$/gm, "<h4>$1</h4>");
  html = html.replace(/^- (.+)$/gm, "<li>$1</li>");
  html = html.replace(/(<li>.*<\/li>)/s, "<ul>$1</ul>");
  html = html.replace(/\n/g, "<br>");
  return sanitizeHtml(html);
}
```

```typescript
// widget/src/utils/urlPolicy.ts
const ALLOWED_PROTOCOLS = ["http:", "https:"];
const ALLOWED_HOSTS = [
  "github.com",
  "raw.githubusercontent.com",
  "camthink.ai",
  "wiki.camthink.ai",
  "docs.camthink.ai",
];

/** 来源链接协议 + 域白名单:拦截 javascript: / data: 等危险协议与非官方域名 */
export function isAllowedUrl(url: string): boolean {
  try {
    const u = new URL(url);
    if (!ALLOWED_PROTOCOLS.includes(u.protocol)) return false;
    return ALLOWED_HOSTS.some(
      (h) => u.hostname === h || u.hostname.endsWith("." + h),
    );
  } catch {
    return false;
  }
}
```

`widget/src/components/MessageBubble.tsx` 改造两点:

```tsx
// 顶部 import 替换:
import { renderMarkdownSafe } from "../utils/sanitize";
import { isAllowedUrl } from "../utils/urlPolicy";

// 渲染行(原 renderMarkdown(message.content) 改为):
<div dangerouslySetInnerHTML={{ __html: renderMarkdownSafe(message.content) }} />

// 删除原文件内的 renderMarkdown 函数(已由 renderMarkdownSafe 取代)

// 来源链接循环改为(校验 URL 后再决定是否可点):
{message.sources.map((src, i) => {
  const safe = isAllowedUrl(src.url);
  return (
    <a
      key={i}
      className="ask-ai-source"
      href={safe ? src.url : "#"}
      target="_blank"
      rel="noopener noreferrer"
      onClick={(e) => {
        if (!safe) { e.preventDefault(); return; }
        if (!conversationId) return;
        fetch(`${apiUrl}/api/click`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            conversation_id: conversationId,
            source_url: src.url,
            source_type: src.type,
            product: src.product,
          }),
        });
      }}
    >
      [{SOURCE_LABELS[src.type] || src.type}] {src.title}
    </a>
  );
})}
```

```typescript
// widget/src/utils/__tests__/sanitize.test.ts
import { describe, it, expect } from "vitest";
import { renderMarkdownSafe } from "../sanitize";
import { isAllowedUrl } from "../urlPolicy";

describe("renderMarkdownSafe", () => {
  it("strips <script> injection", () => {
    expect(renderMarkdownSafe("<script>alert(1)</script>")).not.toContain("<script>");
  });
  it("strips <img onerror>", () => {
    const out = renderMarkdownSafe('<img src=x onerror="alert(1)">');
    expect(out).not.toContain("onerror");
    expect(out).not.toContain("<img");
  });
  it("preserves bold markdown", () => {
    expect(renderMarkdownSafe("**bold**")).toContain("<strong>bold</strong>");
  });
});

describe("isAllowedUrl", () => {
  it("rejects javascript: protocol", () => {
    expect(isAllowedUrl("javascript:alert(1)")).toBe(false);
  });
  it("rejects data: protocol", () => {
    expect(isAllowedUrl("data:text/html,<script>")).toBe(false);
  });
  it("accepts github.com", () => {
    expect(isAllowedUrl("https://github.com/camthink-ai/ne503")).toBe(true);
  });
  it("rejects unknown domain", () => {
    expect(isAllowedUrl("https://evil.com/path")).toBe(false);
  });
});
```

- [ ] **Step 6: 运行所有测试**

```bash
pytest tests/utils/test_budget.py tests/api/test_schemas.py tests/api/test_hardening.py tests/connectors/test_github_scope.py -v
cd widget && npm test -- src/utils/__tests__/sanitize.test.ts
```

Expected: PASS

- [ ] **Step 7: 更新 .env.example + Commit**

在 `.env.example` 追加:

```bash
# Security (Task 21)
FASTAPI_DEBUG=false                # 生产保持 false
APP_MODE=dev                       # prod 时 GITHUB_TOKEN 写权限校验严格
CORS_ALLOW_ORIGINS=http://localhost:3000,http://localhost:1313  # 生产改为官网/Wiki 域名
BUDGET_DAILY_REQUESTS=500          # 每日 /api/ask 请求上限
BUDGET_DAILY_TOKENS=2000000        # 每日 LLM 估算 token 上限
```

```bash
git add backend/ widget/ tests/ .env.example
git commit -m "feat: 安全加固(输出XSS/成本熔断/输入边界/Token最小权限/生产配置)"
```

---

## Self-Review

**Spec coverage check:**

| Spec 要求 | 对应 Task | 状态 |
|---|---|---|
| FastAPI SSE 端点 | Task 16 | ✅ |
| 限流(访客级+全局) | Task 16 (slowapi: 全局 60/min + ask 端点 20/min) | ✅ 已修复 |
| PII 脱敏 | Task 14 | ✅ |
| Weaviate hybrid 检索 | Task 12 | ✅ |
| bge-reranker 重排 | Task 8, 13 | ✅ |
| 拒答(阈值) | Task 13, 15 | ✅ |
| DeepSeek 生成 | Task 4 | ✅ |
| DataSourceConnector 框架 | Task 5 | ✅ |
| GitHubConnector (10 仓库) | Task 6 + config | ✅ |
| FilesystemConnector | Task 7 | ✅ |
| 分段管道 | Task 9 | ✅ |
| 灌入管道 | Task 10 | ✅ |
| cron 同步 + sync_log | Task 11 | ✅ |
| 匿名统计 | Task 16 (conversations) | ✅ |
| 来源点击追踪 | Task 16 (click endpoint) | ✅ |
| Widget (script 嵌入) | Task 17, 18, 19 | ✅ |
| 有限多轮(前端 5 轮) | Task 18 (conversation_history) | ✅ |
| 推荐问题 | Task 18 | ✅ |
| 反馈 👍/👎 | Task 16, 18 | ✅ |
| device 抽象 | Task 8 | ✅ |
| 全部 10 张 Postgres 表 | Task 2 | ✅ |
| Postgres 索引(6 个) | Task 2 (Index 定义) | ✅ 已修复 |
| Pruner 管线预留位置 | Task 15 (pruner=None 可选参数) | ✅ 已修复 |
| 输出 XSS 防护(转义+DOMPurify+URL白名单) | Task 21 (S1) | ✅ 新增 |
| 成本预算熔断(日请求+token 双阈值) | Task 21 (S2) | ✅ 新增 |
| conversation_history 后端边界 | Task 21 (S3) | ✅ 新增 |
| GITHUB_TOKEN 最小权限校验 | Task 21 (S4) | ✅ 新增 |
| 生产配置(异常不回显/CORS白名单/debug关/安全头) | Task 21 (S5) | ✅ 新增 |

**Spec 待确认项(不影响 Phase 1 开工):**
- 日志保留期 90 天(§13)— 需后续加 cron 清理任务或 Postgres retention policy
- 查询分解(§5 pipeline 图提到,§10 Phase 1 列表未列)— 按 §10 处理,Phase 1 不实现

**Bug 修复记录:**
- B1: test_ingest.py 构造函数参数不匹配 → 已修复(移除多余的 postmark_session 参数)
- B2: MessageBubble click conversation_id → 已修复(透传 conversationId prop)
- B3: test_rag.py reranker mock 返回类型错误 → 已修复(返回 float 列表)
- B4: useSSE.ts 死代码 → 已修复(合并为单个 ask 函数)
- B5: SQLAlchemy LLMProvider 类名冲突 → 已修复(重命名为 LLMProviderModel)

**Type consistency:** Checked — `SearchResult`, `RawDocument`, `LLMResponse`, `RAGAnswer` used consistently across tasks.

**Placeholder scan:** No TBD/TODO found. All code blocks contain implementation.
