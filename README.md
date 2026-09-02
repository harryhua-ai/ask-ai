# ASK-AI

ASK-AI is an AI product-knowledge and professional-consultation platform built around grounded enterprise knowledge. It currently powers the **CamThink** assistant (AIoT product documentation, support, and commercial consultation) while its core — knowledge ingestion, retrieval, evidence-grounded generation, and experience layers — is designed to be reusable across products and domains.

## What is ASK-AI?

ASK-AI is not a document-upload chatbot. It is a full consultation pipeline: every visitor question passes through intent and context understanding, multi-path knowledge retrieval, evidence-grounded generation, and deterministic citation enforcement before an answer reaches the user.

Answers may only be built from retrieved official sources. Citation markers (`[N]`) shown to the visitor are the same authoritative numbering given to the model — a deterministic validator removes dangling or numerically unsupported markers rather than trusting the LLM to cite honestly. Internal knowledge (e.g. historical support cases) can participate in generation as background context but is structurally excluded from both citations and the visitor-visible source list.

The platform also implements professional-consultation behaviors that go beyond Q&A: troubleshooting-guided support intents, product/commercial consultation, deterministic social smalltalk and friendly off-topic boundaries, and a sales-lead capture flow where qualified commercial signals trigger a one-time contact invitation after the question has been answered — never instead of an answer.

**CamThink is the first product deployment of ASK-AI, not the platform's boundary.** Product-specific content lives in configuration (site definitions, knowledge sources, prompts) while the ingestion, retrieval, citation, experience, and integration layers remain product-agnostic.

## Key Capabilities

All capabilities below are implemented in the current source.

- **Grounded knowledge Q&A** — retrieval-only answering with deterministic citation validation (dangling/unsupported `[N]` markers removed; authoritative numbering shared between model context and visitor sources).
- **Multi-source knowledge ingestion** — connectors for GitHub repositories, local Git checkouts, filesystem folders, and website crawling; chunking, embedding, and ledger bookkeeping with idempotent re-syncs.
- **Hybrid retrieval with fusion and reranking** — Weaviate hybrid search fused via Reciprocal Rank Fusion with symbol BM25 and intent-aware boost buckets, then cross-encoder reranking.
- **Intent-aware behavior** — LLM-based intent classification (product / commercial / support / off-topic) steering retrieval thresholds and boost buckets; deterministic smalltalk short-circuit and friendly off-topic boundary (zh/en) that never swallow product questions.
- **Citation provenance** — Wiki sources are presented through canonical page URLs while original source URLs are preserved for traceability (`provenance_url`).
- **Knowledge trust boundary** — per-source/per-channel visibility enforced at retrieval time plus a defense-in-depth visibility guard; internal sources can inform answers but are never exposed to visitors.
- **Multilingual responses** — language resolution chain (host/page language → site default → browser language → question-text detection) with en/zh normalization; localized widget UI and localized per-site welcome/suggested questions.
- **Site-aware experiences** — multiple hosted sites (origin-authorized, fail-closed), per-site welcome/starters/language, and untrusted host page-context used only as a labeled, non-citable hint.
- **Sales lead capture & handoff** — LLM qualification of commercial signals, one-proactive-ask invitation, deterministic contact detection, lead-thread continuity, and an Admin handoff workflow; contact PII is stored only in the leads table and never enters retrieval, prompts, traces, or logs in raw form.
- **Configurable LLM providers** — task-based provider chain routing (generation, intent, qualification, …) with automatic failover; DeepSeek implementation included, managed via Admin or `config/llm_providers.yaml`.
- **Admin console** — operations overview, data-source management with health, conversation review with trace drill-down, technical insights, sales leads, LLM provider configuration, channel customizations, human answer overrides, and user management (JWT + role-based access).
- **Embeddable widget & headless API** — script-tag widget for hosted sites plus a REST/SSE API for custom UIs.
- **Sync consistency controls** — authoritative ledger/vector reconciliation with source-confirmed retirement (absence from an extraction round never triggers destructive deletion), exact document-local deletion, and observable failure semantics.

## Architecture

```mermaid
flowchart TB
    subgraph Clients["Clients / Channels"]
        W["Embeddable Widget"]
        H["Headless REST / SSE API"]
        A["Admin Console"]
    end
    subgraph Core["ASK-AI Core (FastAPI)"]
        API["API & Experience Layer (origin authorization, budget, PII masking)"]
        P["Consultation Pipeline (social short-circuit, intent, rewrite)"]
        R["Retrieval (hybrid + BM25 + intent boost → RRF → rerank → prune)"]
        C["Citation Context & Validation (authoritative numbering, provenance)"]
        L["LLM Provider Routing (task chains, failover)"]
        LE["Lead Capture (qualification, contact detection)"]
    end
    subgraph Data["Knowledge & State"]
        PG[("PostgreSQL: sources, ledger, conversations, leads, traces")]
        WV[("Weaviate: vectors + metadata")]
        SYNC["Knowledge Sync (connectors, reconciliation)"]
    end
    W --> API
    H --> API
    A --> API
    API --> P --> R --> C --> L
    P --> LE
    R --> WV
    SYNC --> PG
    SYNC --> WV
    API --> PG
    LE --> PG
```

Supporting surfaces: the Admin console manages sources, providers, reviews, and leads through the same API layer; the knowledge sync worker keeps the document ledger (PostgreSQL) and vectors (Weaviate) consistent.

## Request Flow

A visitor question (`POST /api/ask`, SSE) is processed as follows:

1. **Guardrails first** — the message is PII-masked, the session budget is checked, and for site-embedded widgets the site identity is authorized by origin (fail-closed).
2. **Deterministic short-circuits** — human answer overrides and pure social smalltalk are matched before any LLM call.
3. **Intent classification** — product/commercial/support/off-topic; off-topic receives a friendly boundary response instead of entering retrieval.
4. **Retrieval** — query rewrite/extraction, then hybrid vector search fused with symbol BM25 and intent boost buckets (RRF), cross-encoder reranking, and pruning.
5. **Evidence assembly** — visitor-visible sources are extracted (public whitelist, deduplicated, capped) and become the authoritative citation numbering; internal sources join the prompt as unlabeled background.
6. **Generation** — the LLM provider chain generates the answer with citation markers; lead-qualification (when applicable) runs concurrently so invitations are appended only after the question is answered.
7. **Citation enforcement** — a streaming state machine and a final validator remove dangling or numerically unsupported `[N]` markers; the answer, sources (with canonical URLs and provenance), and trace metadata are persisted.

## Knowledge Sources

Current connectors (`backend/connectors/`):

| Connector | Source |
| --- | --- |
| `github` | GitHub repositories (branches, markdown docs) |
| `local_git` | Local Git checkouts |
| `filesystem` | Filesystem folders (uploaded or server-side paths) |
| `web_crawl` | Website crawling with sitemap support |

Sources are defined in `config/data_sources.yaml` and managed in Admin. Each sync records a run ledger (documents and chunk counts) in PostgreSQL; the reconciliation layer retires stale content only when the authoritative source membership confirms it, so partial extraction failures never silently delete knowledge. Deleting a source in Admin removes its exclusive corpus (ledger-exact deletion plus bounded orphan cleanup) and fails loudly — preserving all state for retry — if vector cleanup cannot complete.

## Retrieval & Answer Generation

- **Embeddings & reranking**: the current implementation uses BAAI `bge-m3` embeddings and `bge-reranker-v2-m3` reranking (local model cache via `MODEL_CACHE_DIR`, device selectable via `EMBEDDER_DEVICE`). The embedder/reranker sit behind interfaces, so alternative implementations can be added.
- **Fusion**: any number of retrieval paths are fused by Reciprocal Rank Fusion with `source_id + chunk_index` deduplication.
- **Vector store**: Weaviate (hybrid search); schema and class are configurable.
- **LLM providers**: provider chains are defined per task in `config/llm_providers.yaml` and editable at runtime in Admin; requests fall through the chain on failure. DeepSeek is the bundled implementation.
- **Citation integrity**: the visitor-visible source list is the single source of authoritative numbering; the model sees the same numbering, and both the stream and the final answer are validated.

## Interfaces

| Interface | Description |
| --- | --- |
| **Embeddable Widget** | Script-tag widget (`widget/`) for hosted sites: site identity (`data-site-id`), language resolution, suggested questions, attachments, SSE streaming |
| **Headless API** | `POST /api/ask` (SSE) plus site-config, feedback, upload endpoints — for fully custom UIs |
| **Admin Console** | `admin/` SPA (operations, sources, review, insights, leads, providers, customizations, overrides, users) |

A `channel` field labels conversation origin (widget/discord/whatsapp/mcp/admin) for analytics and per-channel customization; dedicated Discord/WhatsApp connectors are not part of the current implementation. Public endpoint availability is a deployment decision — the repository ships the interfaces, not a hosted service.

## Admin Console

- **Business Overview** — service conversation trends, intent distribution, lead funnel, hot products/questions.
- **Data Sources** — source CRUD, sync triggering, per-source health, corpus lifecycle.
- **Conversations Review** — full conversation list with trace drill-down (retrieval stages, citations, generation diagnostics) and intent tagging.
- **Technical Insights** — latency KPIs, stage-level diagnostics, coverage gaps, source analytics.
- **Sales Leads** — lead list with qualification details, conversation threads, manual handoff.
- **LLM Providers** — provider chain configuration and connectivity tests.
- **Customizations / Answer Overrides** — per-channel customization profiles and human answer overrides.
- **Users** — admin-managed accounts with `admin` / `editor` / `viewer` roles enforced by backend RBAC on every endpoint.

## Configuration

| Surface | Purpose |
| --- | --- |
| `.env` (from `.env.example`) | Database/Weaviate endpoints, LLM credentials, embedder device and model cache, host/port, CORS, budget limits, logging |
| `config/sites.yaml` | Hosted sites: identity, allowed origins, default language, welcome/starters (+ localized variants) |
| `config/llm_providers.yaml` | LLM provider chains per task |
| `config/data_sources.yaml` | Knowledge source definitions |
| `config/system_prompt.yaml` | Base assistant prompts per channel |
| Admin DB settings | Runtime-editable providers, customizations, and overrides (stored in PostgreSQL) |

Never commit real credentials; the `.env.example` documents every required key with placeholders.

## Quick Start

Prerequisites: Python 3.12+ with [uv](https://docs.astral.sh/uv/), Node.js 18+, Docker.

```bash
# 1. Install backend dependencies (creates .venv)
uv sync

# 2. Configure environment
cp .env.example .env   # fill in database/Weaviate/LLM credentials

# 3. Start PostgreSQL and Weaviate
docker compose -f deploy/dev/docker-compose.yml up -d postgres weaviate

# 4. Create an Admin account (prompts for password)
uv run python scripts/create_admin_user.py admin@example.com --name "Admin" --role admin

# 5. Ingest a knowledge source
uv run python scripts/sync.py

# 6. Run the API server
uv run python -m backend.main
```

First startup creates the database schema automatically. Then, for the frontends:

```bash
# Admin console (http://localhost:5174)
cd admin && npm install && npm run dev

# Widget (development build)
cd widget && npm install && npm run dev
```

The widget is embedded into any page with a script tag pointing at the API base URL plus optional `data-site-id` / `data-language` attributes.

## Environment Variables

The full list with placeholders lives in [`.env.example`](.env.example). Major groups:

- **Storage**: `POSTGRES_*`, `WEAVIATE_URL`, `WEAVIATE_CLASS_NAME`
- **LLM**: `DEEPSEEK_API_KEY`, `DEEPSEEK_API_BASE`, `DEEPSEEK_MODEL` (runtime provider chains override via Admin)
- **Embedding**: `EMBEDDER_DEVICE`, `MODEL_CACHE_DIR`
- **Serving**: `ASKAI_API_HOST`, `ASKAI_API_PORT`, `CORS_ALLOW_ORIGINS`, `APP_MODE`
- **Operations**: `BUDGET_DAILY_REQUESTS`, `BUDGET_DAILY_TOKENS`, `LOG_LEVEL`, `GITHUB_TOKEN`

## Database & Migrations

- **Fresh installation**: the schema is created automatically at first startup. No manual step is needed.
- **Upgrading an existing deployment**: additive schema changes ship as idempotent scripts in `scripts/migrate_*.py` (each reports "already applied" and is safe to re-run). Apply the scripts that correspond to the version you are upgrading to; automatic schema creation does not alter existing tables.

## Development

```bash
# Backend tests (dev tooling + an isolated test database)
uv sync --extra dev
export TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:PASSWORD@localhost:5432/ask_ai_test
uv run pytest tests/

# Admin console
cd admin
npm run test          # Vitest suite
npm run build         # TypeScript check + production build

# Widget
cd widget
npm run test          # Vitest suite
npm run build         # Production build
```

## Deployment

CI (`.github/workflows/build-image.yml`) builds a single self-contained container image — backend, Admin and Widget builds, and runtime dependencies — and publishes it to `ghcr.io/harryhua-ai/ask-ai` on pushes to `main`, version tags, and manual dispatch. Model weights and knowledge corpora are not part of the image; they are supplied by the deployment environment.

Deployment itself is operator-driven (pull the image and restart the compose stack on the target host); pushing to `main` builds and publishes an image but does not by itself update any running environment. Note that the latest `main` can be ahead of what is currently deployed in a given environment.

## Project Structure

```
backend/          FastAPI application: API layer, consultation pipeline,
                  retrieval (search/rerank/fusion), connectors, embedder,
                  LLM routing, services, auth, DB models
admin/            Admin console (React + Vite + TypeScript)
widget/           Embeddable widget (React + Vite + TypeScript)
config/           sites / data sources / LLM providers / system prompts (YAML)
scripts/          knowledge sync, admin bootstrap, idempotent DB migrations
tests/            backend test suite (pytest + pytest-asyncio)
docs/             engineering & implementation documentation
deploy/           development/prod compose files and deployment notes
```

## Current Deployment: CamThink

ASK-AI currently powers the CamThink assistant (camthink.ai product knowledge, support, and consultation). CamThink-specific content is configuration — site definitions in `config/sites.yaml`, knowledge sources, and prompts — while the core platform (ingestion, retrieval, citation, experience, and integration layers) is product-agnostic by design. Features present in this repository reach a given public deployment only after that deployment upgrades and activates them.

## Security & Trust Principles

- **Grounded answers only** — responses are built from retrieved official sources; unsupported claims cannot carry citation markers.
- **Provenance** — every displayed source keeps a traceable link to its origin.
- **Knowledge trust boundary** — source/channel visibility is enforced at retrieval time with a fail-closed guard; internal knowledge informs answers without ever being exposed to visitors.
- **Role-based Admin access** — JWT authentication with `admin`/`editor`/`viewer` roles checked on every endpoint.
- **PII handling** — visitor messages are PII-masked before processing; lead contact details are stored only in the dedicated leads table.
- **Operational limits** — daily request/token budget guards and rate limiting on public endpoints.
- **Secrets hygiene** — credentials live in `.env` / deployment environment only; no secrets are committed.

## Direction

Planned platform direction (not current capabilities): reusable multi-product knowledge-assistant deployments beyond CamThink, richer professional consultation workflows, additional channel integrations, and retrieval/model evaluation and tuning.
