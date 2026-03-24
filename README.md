# YODA — AI Meeting Companion

## Release Contents

```
YODA-BB/                    Backend (Python/FastAPI microservices)
├── foundation/             Shared library (241 files)
├── services/               6 microservices
│   ├── meeting-service/    Meeting lifecycle, transcription, AI, action items
│   ├── document-service/   Documents, RAG, classification, search
│   ├── chat-service/       AI-powered Q&A with citations
│   ├── dashboard-service/  Stats, insights, notifications, recommendations
│   ├── pre-meeting-brief-service/  Meeting preparation briefs
│   └── weekly-digest-service/      Weekly AI summaries
├── alembic/                Database migrations
├── deployment/             Docker Compose + Nginx gateway
├── config/                 Golden QA cases for DSPy optimization
├── .github/workflows/      CI/CD pipeline
└── .env.example            Environment variables template

yoda-frontend/              Frontend (Angular 21)
├── src/app/                9 views, 11 services, 8 model files
├── Dockerfile              Multi-stage build
└── nginx.conf              SPA routing

docs/                       Documentation
├── YODA_User_Stories_Requirements.docx    47 user stories, 11 epics
├── YODA_Database_Schema_Reference.docx    16 tables, relationships, indexes
├── YODA_Low_Level_Design.docx             21-section technical design
└── wireframe-backend-mapping.csv          108 features mapped

wireframes/                 UI wireframe prototype (HTML)
```

## Quick Start

### Prerequisites
- Python 3.11+
- Node.js 20+
- Docker (for PostgreSQL + Redis)

### Setup
```bash
# 1. Start infrastructure
cd YODA-BB/deployment && docker compose up -d postgres redis

# 2. Install backend
cd YODA-BB/foundation && pip install -e ".[dev]"

# 3. Create database tables
cd YODA-BB && DATABASE_URL=postgresql+asyncpg://yoda:yoda_dev@localhost:5432/yoda alembic upgrade head

# 4. Start backend services
REQUIRE_AUTH=false DATABASE_URL=postgresql+asyncpg://yoda:yoda_dev@localhost:5432/yoda \
  PYTHONPATH=services/dashboard-service/src:foundation/src \
  uvicorn dashboard_service.main:app --port 8013

# 5. Install frontend
cd yoda-frontend && npm install

# 6. Start frontend
npx ng serve --port 4210
```

Open http://localhost:4210

## Tests
```bash
# Backend (323 tests)
cd YODA-BB
for svc in meeting document chat dashboard pre-meeting-brief weekly-digest; do
  PYTHONPATH=services/${svc}-service/src:foundation/src pytest services/${svc}-service/tests/ -v
done
PYTHONPATH=foundation/src pytest foundation/tests/ -v

# Frontend
cd yoda-frontend && npx ng build --configuration=production
```

## Tech Stack
- Backend: Python 3.11+, FastAPI, SQLAlchemy 2.0, PostgreSQL + pgvector
- Frontend: Angular 21, TypeScript strict, MSAL auth
- AI: Azure AI Foundry (GPT-4o), DSPy v3.1.3, RAG with hybrid search
- Deploy: Docker Compose (10 containers), Nginx gateway, GitHub Actions CI/CD
