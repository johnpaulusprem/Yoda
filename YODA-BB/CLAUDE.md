# YODA — Microservices Backend

## Overview
Python 3.11+ FastAPI microservices backend. 6 services + shared foundation library.
Full spec: `teams-meeting-assistant-spec.md`

## Architecture
- **yoda_foundation** — Shared library (models, schemas, RAG, DSPy, security, resilience, observability, guardrails, events, memory)
- **meeting-service** (port 8001) — Meeting lifecycle, transcription, ACS, Graph webhooks, action items, nudges
- **document-service** (port 8002) — Document ingestion, RAG pipeline, search
- **chat-service** (port 8003) — AI-powered Q&A with RAG and citations
- **dashboard-service** (port 8004) — Stats, insights, notifications, search aggregation
- **pre-meeting-brief-service** (port 8005) — Pre-meeting briefs with attendee context
- **weekly-digest-service** (port 8006) — Weekly summaries with APScheduler

## Tech Stack
- **Framework:** FastAPI (async)
- **DB:** PostgreSQL + pgvector via SQLAlchemy 2.0 async (asyncpg) + Alembic
- **Cache/Queue:** Redis, APScheduler
- **Azure:** ACS (Call Automation), Graph API, AI Foundry (GPT-4o-mini/4o), Entra ID
- **Cross-cutting:** OpenTelemetry, circuit breakers, guardrails, RBAC, event bus
- **Deploy:** Docker Compose + Nginx reverse proxy → Azure Container Apps

## LSP
Use Pyright for type checking and code intelligence.

## Commands
```bash
# Install foundation (editable)
cd foundation && pip install -e ".[dev]"

# Install a service (editable)
cd services/meeting-service && pip install -e ".[dev]"

# Run individual service
cd services/meeting-service && uvicorn meeting_service.main:app --reload --port 8001

# Database migrations (from YODA-BB root)
alembic upgrade head
alembic revision --autogenerate -m "description"

# Tests
cd foundation && pytest tests/ -v
cd services/meeting-service && pytest tests/ -v
cd services/document-service && pytest tests/ -v

# Docker local dev (all services)
docker-compose -f deployment/docker-compose.yml up
```

## Project Structure
```
YODA-BB/
├── foundation/                      # Shared library (pip install -e .)
│   ├── pyproject.toml
│   └── src/yoda_foundation/
│       ├── models/                  # 12 SQLAlchemy models
│       ├── schemas/                 # 15 Pydantic schemas
│       ├── config/                  # Settings (90+ env vars)
│       ├── exceptions/              # YodaBaseException hierarchy
│       ├── security/                # JWT, RBAC, data governance
│       ├── resilience/              # Retry, circuit breaker, bulkhead, etc.
│       ├── observability/           # OTel tracing, metrics, logging
│       ├── guardrails/              # Content safety, jailbreak detection
│       ├── events/                  # Event bus, handlers, triggers
│       ├── memory/                  # Tiered memory (working, episodic, semantic)
│       ├── rag/                     # Chunking, embeddings, retrieval, pipeline
│       ├── dspy/                    # LLM adapters, signatures, modules
│       ├── data_access/             # Base connectors, repos, Azure connectors
│       ├── utils/                   # Auth, caching, retry
│       ├── middleware/              # Correlation ID, error handler, rate limiter
│       └── templates/               # Adaptive Card JSON
├── services/
│   ├── meeting-service/             # Port 8001 (restructured monolith)
│   ├── document-service/            # Port 8002
│   ├── chat-service/                # Port 8003
│   ├── dashboard-service/           # Port 8004
│   ├── pre-meeting-brief-service/   # Port 8005
│   └── weekly-digest-service/       # Port 8006
├── alembic/                         # Centralized DB migrations
├── deployment/                      # docker-compose.yml, nginx-gateway.conf
└── .env.example                     # All env vars
```

## Key Patterns
- All config via env vars (pydantic-settings), never hardcode secrets
- All DB models use UUID PKs + created_at/updated_at (TimestampMixin)
- Async everywhere: use `async def`, `await`, asyncpg driver
- SQLAlchemy 2.0 style (mapped_column, Mapped type hints)
- Structured logging (JSON format for Azure Monitor)
- Tenacity-based retry for all external API calls
- Services share one PostgreSQL database, routed via Nginx by URL prefix

## Environment
Copy `.env.example` to `.env`. Required vars:
- `DATABASE_URL` — PostgreSQL connection string (asyncpg)
- `REDIS_URL` — Redis connection string
- `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET` — Entra ID app
- `ACS_CONNECTION_STRING`, `ACS_ENDPOINT` — Azure Communication Services
- `AI_FOUNDRY_ENDPOINT`, `AI_FOUNDRY_API_KEY` — Azure AI Foundry
- `AZURE_OPENAI_EMBEDDING_ENDPOINT`, `AZURE_OPENAI_EMBEDDING_API_KEY` — Embeddings
- `BASE_URL` — Public URL for webhook callbacks

## Gotchas
- ACS Call Automation requires Teams-ACS interop federation
- Graph calendar subscriptions expire after 3 days — must auto-renew
- Graph webhook validation: respond to `validationToken` query param
- Transcript chunks arrive via WebSocket — buffer and reassemble per speaker
- Use app-only (daemon) auth flow, not delegated
- All services depend on yoda-foundation — install it first
