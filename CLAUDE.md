# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

YODA is a Teams meeting assistant platform with a Python microservices backend (`YODA-BB/`) and an Angular frontend (`yoda-frontend/`). The backend is composed of 6 FastAPI services sharing a foundation library, with PostgreSQL+pgvector for storage and Azure services for AI/communication.

## Architecture

```
YODA-BB/
├── foundation/               # Shared pip library (yoda_foundation)
│   └── src/yoda_foundation/  # Models, schemas, RAG, DSPy, security, events, etc.
├── services/                 # 6 independent FastAPI microservices
│   ├── meeting-service/      # Meeting lifecycle, ACS transcription, Graph webhooks, action items
│   ├── document-service/     # Document ingestion, RAG pipeline, vector search
│   ├── chat-service/         # AI Q&A with RAG and citations
│   ├── dashboard-service/    # Stats, insights, notifications, search aggregation
│   ├── pre-meeting-brief-service/  # Pre-meeting briefs with attendee context
│   └── weekly-digest-service/      # Weekly summaries via APScheduler
├── alembic/                  # Centralized DB migrations (PostgreSQL + pgvector)
└── deployment/               # docker-compose.yml, nginx-gateway.conf

yoda-frontend/                # Angular 21 SPA with MSAL auth
└── src/app/
    ├── core/                 # Services, interceptors, models
    ├── features/             # Feature modules (dashboard, chat, meetings, etc.)
    ├── layout/               # App shell components
    └── shared/               # Shared utilities
```

All backend services share one PostgreSQL database. Nginx routes requests by URL prefix. No inter-service HTTP calls.

## Commands

### Backend
```bash
# Install foundation first (required by all services)
cd YODA-BB/foundation && pip install -e ".[dev]"

# Install a specific service
cd YODA-BB/services/meeting-service && pip install -e ".[dev]"

# Run a service locally
cd YODA-BB/services/meeting-service && uvicorn meeting_service.main:app --reload --port 8001

# Run all services via Docker
cd YODA-BB && docker-compose -f deployment/docker-compose.yml up

# Database migrations (from YODA-BB root)
cd YODA-BB && alembic upgrade head
cd YODA-BB && alembic revision --autogenerate -m "description"

# Tests
cd YODA-BB/foundation && pytest tests/ -v
cd YODA-BB/services/meeting-service && pytest tests/ -v  # same pattern for other services

# Lint
ruff check YODA-BB/foundation/src/ YODA-BB/services/*/src/ --select E,W,F --ignore E501
```

### Frontend
```bash
cd yoda-frontend && npm ci          # install deps
cd yoda-frontend && ng serve        # dev server
cd yoda-frontend && ng build        # production build
cd yoda-frontend && ng test         # run tests (Vitest + Jasmine)
```

## Tech Stack

- **Backend:** Python 3.11+, FastAPI, SQLAlchemy 2.0 async (asyncpg), Pydantic 2.0+, Alembic
- **AI/Azure:** Azure Communication Services, Graph API, AI Foundry (GPT-4o), DSPy, OpenTelemetry
- **Infrastructure:** PostgreSQL 16 + pgvector, Redis, Docker Compose, Nginx
- **Frontend:** Angular 21, TypeScript 5.9, RxJS, @azure/msal-angular, Vitest
- **CI:** GitHub Actions — runs pytest per service, frontend build, ruff lint

## Key Patterns

- Config via env vars (pydantic-settings); copy `.env.example` to `.env` at the repo root
- All DB models use UUID PKs + `created_at`/`updated_at` (TimestampMixin)
- Async everywhere: `async def`, `await`, asyncpg driver
- SQLAlchemy 2.0 style: `mapped_column`, `Mapped` type hints
- Tenacity-based retry for external API calls
- Use Pyright for type checking
- Foundation must be installed before any service (`pip install -e "foundation/[dev]"`)

## Gotchas

- ACS Call Automation requires Teams-ACS interop federation to be configured
- Graph calendar subscriptions expire after 3 days — auto-renewal is required
- Graph webhook validation: must respond to `validationToken` query param
- Transcript chunks arrive via WebSocket — buffer and reassemble per speaker
- Use app-only (daemon) auth flow, not delegated
- CI lint runs `ruff check` with `--select E,W,F --ignore E501` (not the full rule set from pyproject.toml)
