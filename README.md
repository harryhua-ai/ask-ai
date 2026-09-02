# ASK-AI

ASK-AI is an AI-powered product knowledge and professional consultation platform that turns enterprise knowledge into grounded, context-aware answers and guidance.

> Grounded answers. Real sources. Your knowledge.

## Overview

ASK-AI connects to enterprise knowledge — repositories, websites, files, and other supported data sources — keeps it synchronized and searchable, and uses it to answer user questions with evidence-grounded responses, complete with citations back to the originating sources.

Every question passes through a complete consultation pipeline: intent understanding, multi-path knowledge retrieval, evidence-based generation, and citation enforcement. Behavior adapts to what the user needs — product questions, technical support, commercial consultation — and supports professional consultation flows that go beyond simple Q&A.

ASK-AI is a reusable platform rather than a single-purpose chatbot. Product-specific content lives in configuration, while the ingestion, retrieval, citation, and experience layers remain product-agnostic. It ships as a self-hostable backend, an embeddable web assistant, headless APIs, and a full Admin console for knowledge operations.

## Key Features

### Knowledge Ingestion

Connect and synchronize enterprise knowledge from repositories, websites, files, and supported data sources — with idempotent re-syncs and consistency reconciliation.

### Intelligent Retrieval

Hybrid semantic and keyword retrieval with fusion and cross-encoder reranking improves relevance across product documentation and technical knowledge.

### Grounded AI Responses

Answers are built from retrieved knowledge with citation and provenance support, backed by configurable knowledge visibility controls.

### Intent-Aware Assistance

Retrieval and response behavior adapt to user intent — product questions, technical support, consultation — with deterministic smalltalk handling and friendly off-topic boundaries.

### Professional Consultation Flows

Beyond Q&A: troubleshooting-guided support, consultation guidance, and configurable sales-lead capture with admin handoff.

### Multilingual Experience

Multilingual interactions resolved across page language, site defaults, browser settings, and question text — with a localized widget UI and per-site welcome content.

### Flexible LLM Integration

Configurable LLM providers with per-task routing and failover, manageable at runtime through the Admin console or YAML configuration.

### Widget & API

An embeddable script-tag web assistant plus REST and streaming APIs for fully custom integrations.

### Admin Console

Manage knowledge sources, AI configuration, conversations, insights, and operational settings through a role-based admin application.

## Architecture

```mermaid
flowchart TD
    U["Users / Applications"] --> W["Widget / API"]
    W --> E["Experience Layer"]
    E --> P["Intent + RAG Pipeline"]
    P --> R["Retrieval & Reranking"]
    R --> K[("Knowledge Sources")]
    R --> G["LLM Generation"]
    G --> O["Grounded Response"]

    A["Admin Console"] --> S["Knowledge Sync"]
    S --> K
    D[("PostgreSQL")] --- P
    V[("Weaviate")] --- R
```

The knowledge sync worker keeps the document store and the vector index consistent; the Admin console manages sources, providers, and configuration through the same API layer.

## Technology Stack

| Layer | Technology |
| --- | --- |
| Backend | Python / FastAPI |
| Admin Console | React / TypeScript / Vite |
| Widget | React / TypeScript / Vite |
| Database | PostgreSQL |
| Vector Store | Weaviate |
| Embeddings | BGE family |
| Retrieval | Hybrid search / cross-encoder reranking |
| LLM | Configurable provider architecture |
| CI / Packaging | Docker / GitHub Actions |

## Quick Start

Prerequisites: Python 3.12+ with [uv](https://docs.astral.sh/uv/), Node.js 18+, Docker.

```bash
git clone https://github.com/harryhua-ai/ask-ai.git
cd ask-ai

# 1. Install backend dependencies
uv sync

# 2. Configure the environment (database, Weaviate, LLM credentials)
cp .env.example .env

# 3. Start PostgreSQL and Weaviate
docker compose -f deploy/dev/docker-compose.yml up -d postgres weaviate

# 4. Create an admin account
uv run python scripts/create_admin_user.py admin@example.com --name "Admin" --role admin

# 5. Ingest a knowledge source
uv run python scripts/sync.py

# 6. Start the API server
uv run python -m backend.main
```

Then run the frontends:

```bash
# Admin console → http://localhost:5174
cd admin && npm install && npm run dev

# Widget (development build)
cd widget && npm install && npm run dev
```

## Project Structure

```
backend/   FastAPI application — API, consultation pipeline, retrieval, connectors, LLM routing
admin/     Admin console (React + Vite + TypeScript)
widget/    Embeddable assistant widget (React + Vite + TypeScript)
config/    YAML configuration — sites, data sources, LLM providers, prompts
scripts/   Knowledge sync, admin bootstrap, schema utilities
tests/     Backend test suite (pytest)
deploy/    Docker Compose files for local infrastructure
docs/      Engineering and implementation documentation
```

## Development

```bash
# Backend tests (uses an isolated database via TEST_DATABASE_URL)
uv sync --extra dev
export TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:PASSWORD@localhost:5432/ask_ai_test
uv run pytest tests/

# Admin console / widget
cd admin  && npm run test && npm run build
cd widget && npm run test && npm run build
```

The database schema is created automatically on first startup.
