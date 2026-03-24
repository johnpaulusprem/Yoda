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

## Prerequisites

- **Python** 3.11+
- **Node.js** 22+ (Angular 21 requires Node 20.19+ or 22.12+)
- **npm** 10+
- **Docker** (for PostgreSQL + Redis)

## Step-by-Step Setup & Start

### 1. Start Infrastructure (PostgreSQL + Redis)

```bash
cd YODA-BB/deployment
sudo docker compose up -d postgres redis
```

Verify containers are healthy:
```bash
sudo docker ps
# Both postgres and redis should show "healthy" status
```

### 2. Create Python Virtual Environment

```bash
cd YODA-BB
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Backend Dependencies

```bash
# Install all dependencies
pip install -r requirements.txt

# Install foundation library (editable mode)
cd foundation && pip install -e . && cd ..
```

### 4. Configure Environment Variables

```bash
# Copy the example env file
cp .env.example .env
```

Edit `.env` and fill in your Azure credentials if available. For local development without Azure:
- Set `REQUIRE_AUTH=false`
- Leave Azure credential fields empty (the services will start with Azure integrations disabled)

### 5. Run Database Migrations

```bash
cd YODA-BB
DATABASE_URL=postgresql+asyncpg://yoda:yoda_dev@localhost:5432/yoda alembic upgrade head
```

### 6. Start Backend Services

Open separate terminals (or use `&` to background) for each service. Activate the venv in each terminal first:

```bash
source YODA-BB/.venv/bin/activate
```

**Meeting Service (port 8010):**
```bash
cd YODA-BB
REQUIRE_AUTH=false DATABASE_URL=postgresql+asyncpg://yoda:yoda_dev@localhost:5432/yoda \
  REDIS_URL=redis://localhost:6379/0 \
  PYTHONPATH=services/meeting-service/src:foundation/src \
  uvicorn meeting_service.main:app --port 8010 --host 0.0.0.0
```

**Document Service (port 8011):**
```bash
cd YODA-BB
REQUIRE_AUTH=false DATABASE_URL=postgresql+asyncpg://yoda:yoda_dev@localhost:5432/yoda \
  REDIS_URL=redis://localhost:6379/0 \
  PYTHONPATH=services/document-service/src:foundation/src \
  uvicorn document_service.main:app --port 8011 --host 0.0.0.0
```

**Chat Service (port 8012):**
```bash
cd YODA-BB
REQUIRE_AUTH=false DATABASE_URL=postgresql+asyncpg://yoda:yoda_dev@localhost:5432/yoda \
  REDIS_URL=redis://localhost:6379/0 \
  PYTHONPATH=services/chat-service/src:foundation/src \
  uvicorn chat_service.main:app --port 8012 --host 0.0.0.0
```

**Dashboard Service (port 8013):**
```bash
cd YODA-BB
REQUIRE_AUTH=false DATABASE_URL=postgresql+asyncpg://yoda:yoda_dev@localhost:5432/yoda \
  REDIS_URL=redis://localhost:6379/0 \
  PYTHONPATH=services/dashboard-service/src:foundation/src \
  uvicorn dashboard_service.main:app --port 8013 --host 0.0.0.0
```

**Pre-Meeting Brief Service (port 8014):**
```bash
cd YODA-BB
REQUIRE_AUTH=false DATABASE_URL=postgresql+asyncpg://yoda:yoda_dev@localhost:5432/yoda \
  REDIS_URL=redis://localhost:6379/0 \
  PYTHONPATH=services/pre-meeting-brief-service/src:foundation/src \
  uvicorn pre_meeting_brief_service.main:app --port 8014 --host 0.0.0.0
```

**Weekly Digest Service (port 8015):**
```bash
cd YODA-BB
REQUIRE_AUTH=false DATABASE_URL=postgresql+asyncpg://yoda:yoda_dev@localhost:5432/yoda \
  REDIS_URL=redis://localhost:6379/0 \
  PYTHONPATH=services/weekly-digest-service/src:foundation/src \
  uvicorn weekly_digest_service.main:app --port 8015 --host 0.0.0.0
```

### 7. Verify Backend Services

```bash
for port in 8010 8011 8012 8013 8014 8015; do
  echo -n "Port $port: "; curl -s -o /dev/null -w "%{http_code}" http://localhost:$port/health; echo
done
```

All ports should return `200`.

You can also visit the interactive API docs for any service:
- Meeting Service: http://localhost:8010/docs
- Document Service: http://localhost:8011/docs
- Chat Service: http://localhost:8012/docs
- Dashboard Service: http://localhost:8013/docs
- Pre-Meeting Brief Service: http://localhost:8014/docs
- Weekly Digest Service: http://localhost:8015/docs

### 8. Start Frontend

```bash
cd yoda-frontend
npm install
npx ng serve --port 4210 --host 0.0.0.0
```

Open **http://localhost:4210** in your browser.

## Testing

### Backend Tests (323 tests)

```bash
cd YODA-BB
source .venv/bin/activate

# Run all service tests
for svc in meeting document chat dashboard pre-meeting-brief weekly-digest; do
  echo "=== Testing ${svc}-service ==="
  PYTHONPATH=services/${svc}-service/src:foundation/src \
    pytest services/${svc}-service/tests/ -v
done

# Run foundation library tests
echo "=== Testing foundation ==="
PYTHONPATH=foundation/src pytest foundation/tests/ -v
```

### Frontend Build Verification

```bash
cd yoda-frontend
npx ng build --configuration=production
```

### Health Check (Quick Smoke Test)

```bash
# Check all services are responding
curl http://localhost:8010/health   # meeting-service
curl http://localhost:8011/health   # document-service
curl http://localhost:8012/health   # chat-service
curl http://localhost:8013/health   # dashboard-service
curl http://localhost:8014/health   # pre-meeting-brief-service
curl http://localhost:8015/health   # weekly-digest-service
```

### API Smoke Tests

```bash
# List meetings (should return empty array)
curl http://localhost:8010/api/meetings

# Get dashboard stats
curl http://localhost:8013/api/dashboard/stats

# List documents
curl http://localhost:8011/api/documents
```

## Service Port Map

| Service                    | Port | API Docs                          |
|----------------------------|------|-----------------------------------|
| Meeting Service            | 8010 | http://localhost:8010/docs        |
| Document Service           | 8011 | http://localhost:8011/docs        |
| Chat Service               | 8012 | http://localhost:8012/docs        |
| Dashboard Service          | 8013 | http://localhost:8013/docs        |
| Pre-Meeting Brief Service  | 8014 | http://localhost:8014/docs        |
| Weekly Digest Service      | 8015 | http://localhost:8015/docs        |
| Frontend                   | 4210 | http://localhost:4210             |
| PostgreSQL                 | 5432 | —                                 |
| Redis                      | 6379 | —                                 |

## Tech Stack

- **Backend:** Python 3.11+, FastAPI, SQLAlchemy 2.0, PostgreSQL + pgvector
- **Frontend:** Angular 21, TypeScript strict, MSAL auth
- **AI:** Azure AI Foundry (GPT-4o), DSPy v3.1.3, RAG with hybrid search
- **Deploy:** Docker Compose (10 containers), Nginx gateway, GitHub Actions CI/CD
