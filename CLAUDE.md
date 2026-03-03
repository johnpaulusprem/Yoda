# Teams Meeting Assistant Bot — Backend

## Overview
Python 3.11+ FastAPI backend. No UI — backend services and API layer only.
Full spec: `teams-meeting-assistant-spec.md`

## Tech Stack
- **Framework:** FastAPI (async)
- **DB:** PostgreSQL via SQLAlchemy 2.0 async (asyncpg) + Alembic migrations
- **Task Queue:** APScheduler or Celery + Redis
- **Azure Services:** ACS (Call Automation), Graph API, AI Foundry (GPT-4o-mini/4o)
- **Auth:** MSAL (app-only, daemon flow)
- **Deploy:** Docker → Azure Container Apps

## LSP
Use Pyright for type checking and code intelligence.

## Commands
```bash
# Install
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Run dev server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Database migrations
alembic upgrade head
alembic revision --autogenerate -m "description"

# Tests
pytest tests/ -v
pytest tests/test_calendar_watcher.py -v  # single file

# Docker local dev
docker-compose -f deployment/docker-compose.yml up
```

## Project Structure
```
app/
├── main.py              # FastAPI entry point
├── config.py            # pydantic-settings, all config from env vars
├── dependencies.py      # DI: DB sessions, clients
├── models/              # SQLAlchemy 2.0 async models
├── schemas/             # Pydantic request/response schemas
├── services/            # Business logic (graph, ACS, AI, delivery)
├── routes/              # API endpoints
├── templates/           # Adaptive Card JSON templates
└── utils/               # Auth (MSAL), logging, retry
```

## Key Patterns
- All config via env vars (pydantic-settings), never hardcode secrets
- All DB models use UUID PKs + created_at/updated_at (TimestampMixin)
- Async everywhere: use `async def`, `await`, asyncpg driver
- SQLAlchemy 2.0 style (mapped_column, Mapped type hints)
- Structured logging (JSON format for Azure Monitor)
- Tenacity-based retry for all external API calls

## Environment
Copy `.env.example` to `.env`. Required vars:
- `DATABASE_URL` — PostgreSQL connection string (asyncpg)
- `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET` — Entra ID app
- `ACS_CONNECTION_STRING`, `ACS_ENDPOINT` — Azure Communication Services
- `AI_FOUNDRY_ENDPOINT`, `AI_FOUNDRY_API_KEY` — Azure AI Foundry
- `BASE_URL` — Public URL for webhook callbacks

## Gotchas
- ACS Call Automation requires Teams-ACS interop federation (see `scripts/setup_acs_federation.ps1`)
- Graph calendar subscriptions expire after 3 days — must auto-renew
- Graph webhook validation: respond to `validationToken` query param on subscription creation
- Transcript chunks arrive via WebSocket — buffer and reassemble per speaker
- Use app-only (daemon) auth flow, not delegated — bot runs without user interaction
