# How to Use YODA — AI Meeting Companion

YODA is an AI-powered Teams meeting assistant that transcribes meetings, generates summaries, tracks action items, and provides intelligent insights across your organization's meetings and documents.

---

## Table of Contents

1. [Getting Started](#getting-started)
2. [Dashboard](#dashboard)
3. [Meetings](#meetings)
4. [Action Items](#action-items)
5. [Documents & Search](#documents--search)
6. [AI Chat](#ai-chat)
7. [Pre-Meeting Briefs](#pre-meeting-briefs)
8. [Weekly Digests](#weekly-digests)
9. [Insights & Analytics](#insights--analytics)
10. [Settings](#settings)

---

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 20+
- Docker (for PostgreSQL + Redis)
- Azure credentials (Entra ID, AI Foundry, ACS) for full functionality

### Installation

```bash
# 1. Start infrastructure (PostgreSQL + Redis)
cd YODA-BB/deployment
docker compose up -d postgres redis

# 2. Install the shared foundation library
cd YODA-BB/foundation
pip install -e ".[dev]"

# 3. Run database migrations
cd YODA-BB
DATABASE_URL=postgresql+asyncpg://yoda:yoda_dev@localhost:5432/yoda \
  alembic upgrade head

# 4. Configure environment variables
cp YODA-BB/.env.example YODA-BB/.env
# Edit .env with your Azure credentials (see Environment Configuration below)

# 5. Start backend services
REQUIRE_AUTH=false DATABASE_URL=postgresql+asyncpg://yoda:yoda_dev@localhost:5432/yoda \
  PYTHONPATH=services/dashboard-service/src:foundation/src \
  uvicorn dashboard_service.main:app --port 8013

# 6. Install and start the frontend
cd yoda-frontend
npm install
npx ng serve --port 4210
```

Open your browser at **http://localhost:4210** to access the app.

### Running All Services with Docker

For a full deployment with all microservices:

```bash
cd YODA-BB/deployment
docker compose up
```

This starts all 10 containers (6 services + PostgreSQL + Redis + Nginx gateway + frontend).

### Environment Configuration

Copy `.env.example` to `.env` and fill in the required values:

| Variable | Description |
|----------|-------------|
| `AZURE_TENANT_ID` | Your Azure Entra ID tenant |
| `AZURE_CLIENT_ID` | App registration client ID |
| `AZURE_CLIENT_SECRET` | App registration secret |
| `AI_FOUNDRY_ENDPOINT` | Azure AI Foundry endpoint URL |
| `AI_FOUNDRY_API_KEY` | Azure AI Foundry API key |
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | Redis connection string |

---

## Dashboard

The dashboard is your home screen, providing an at-a-glance overview of your meeting activity.

### What You'll See

- **Today's Meetings** — Number of meetings scheduled for today
- **Pending Action Items** — Outstanding tasks assigned to you
- **Completion Rate** — Percentage of action items completed on time
- **Attention Items** — Overdue action items that need immediate follow-up
- **Activity Feed** — Recent meetings, summaries, and changes
- **Recommendations** — AI-suggested follow-ups based on meeting patterns

### How to Use

1. Log in with your Microsoft account (via MSAL authentication)
2. The dashboard loads automatically as the home page
3. Click on any meeting in the activity feed to view its details
4. Review attention items and act on overdue tasks
5. Check notifications (bell icon) for updates on meetings and action items

---

## Meetings

YODA integrates with your Microsoft Teams calendar to track and enhance your meetings.

### Viewing Meetings

- Navigate to the **Meetings** page to see your upcoming and past meetings
- Each meeting shows the title, time, participants, and current status
- Click a meeting to view its full details, transcript, and summary

### Meeting Transcription

When YODA's bot joins a Teams meeting, it captures the conversation in real-time:

1. The bot joins automatically for scheduled meetings (or manually via the **Join** button)
2. Speech is transcribed with speaker labels
3. After the meeting ends, the AI processes the transcript to generate:
   - An **executive summary** highlighting key discussion points
   - A list of **key decisions** made during the meeting
   - **Action items** with suggested owners and due dates

### Managing Meetings

- **Join/Leave** — Control when the YODA bot joins or leaves a meeting
- **View Transcript** — Read the full transcription with speaker identification
- **Regenerate Summary** — Re-run the AI pipeline if the summary needs updating
- **Reprocess** — Trigger a full reprocessing of the meeting data

---

## Action Items

Action items are tasks extracted from meetings by the AI, assigned to team members with due dates.

### Viewing Action Items

- Navigate to the **Action Items** page to see all tasks assigned to you
- Filter by status: Open, In Progress, Completed, or Overdue
- Each item shows the source meeting, assignee, due date, and status

### Managing Action Items

- **Update** — Change the owner, due date, or add notes
- **Complete** — Mark an action item as done
- **Snooze** — Temporarily dismiss a notification for an action item
- Overdue items appear in the dashboard's attention section with nudge notifications

---

## Documents & Search

YODA indexes documents from SharePoint, OneDrive, and email to enable intelligent search across your organization's knowledge.

### Browsing Documents

- Navigate to the **Documents** page to see indexed documents
- View documents shared with you by colleagues
- Check the "Needs Review" section for documents recommended by the AI

### Searching

YODA supports **semantic search** powered by RAG (Retrieval-Augmented Generation):

1. Use the search bar on the Documents page or the global search
2. Type a natural language query (e.g., "What was decided about the Q3 budget?")
3. Results include relevant document excerpts ranked by relevance
4. Click a result to view the full document with the matching section highlighted

### Syncing Documents

- Click **Sync** to manually trigger a SharePoint/OneDrive synchronization
- Email indexing can be triggered to include email content in search results
- Documents are automatically chunked and embedded for semantic retrieval

---

## AI Chat

The AI Chat feature lets you ask questions about your meetings and documents, with answers backed by citations.

### Starting a Conversation

1. Navigate to the **Chat** page
2. Click **New Session** to start a fresh conversation
3. Type your question in natural language

### Example Questions

- "What were the key decisions from last week's project standup?"
- "Who is responsible for the API redesign?"
- "Summarize all discussions about the migration plan"
- "What action items are overdue for the marketing team?"

### How It Works

- YODA uses RAG to retrieve relevant meeting transcripts and documents
- The AI generates an answer with **citations** pointing to specific sources
- Conversation history is preserved so you can ask follow-up questions
- Each answer includes links to the original meetings or documents

---

## Pre-Meeting Briefs

Before a meeting, YODA can generate a preparation brief to help you walk in informed.

### What's Included

- **Meeting context** — Previous meetings on the same topic
- **Attendee information** — Roles and recent activity of participants
- **Open action items** — Unresolved tasks related to the meeting topic
- **Relevant documents** — Key documents you should review beforehand
- **Suggested questions** — AI-generated questions to drive the discussion

### How to Use

1. Navigate to the **Brief** page or click "Prepare" on an upcoming meeting
2. The AI generates the brief based on your meeting history and documents
3. Review the brief before your meeting to be fully prepared

---

## Weekly Digests

YODA automatically generates weekly summaries of your meeting activity.

### What's Included

- Summary of all meetings attended during the week
- Status of action items (new, completed, overdue)
- Key decisions made across meetings
- Trends and patterns in your meeting activity

### How to Access

- Navigate to the **Digest** page to view past weekly digests
- Digests are generated automatically (default: Friday at 3 PM UTC)
- Notifications are sent when a new digest is available

---

## Insights & Analytics

The Insights page provides data-driven analytics about your meeting habits and team collaboration.

### Available Insights

| Insight | Description |
|---------|-------------|
| **Meeting Time** | Hours spent in meetings over time |
| **Action Completion** | Completion rate trends for action items |
| **Collaboration** | Team collaboration patterns and frequency |
| **Meeting Patterns** | Common themes and recurring topics |
| **Decision Velocity** | How quickly decisions are made and acted upon |
| **Recurring Topics** | Topics that come up frequently across meetings |

### How to Use

1. Navigate to the **Insights** page
2. Select a time period (week, month, quarter)
3. Explore charts and visualizations for each insight category
4. Use insights to optimize your meeting habits and team productivity

---

## Settings

Customize YODA to match your preferences.

### Available Settings

- **Notification preferences** — Choose which notifications you receive (email, in-app, Teams)
- **Meeting defaults** — Auto-join settings, summary preferences
- **Display preferences** — Theme, language, timezone
- **Integration settings** — Connected accounts and sync frequency

### How to Access

Navigate to the **Settings** page from the sidebar or user menu.

---

## Architecture & Startup Flow

Understanding how YODA's microservices boot up helps with local development, debugging, and deployment.

### Boot Sequence Overview

```
                    ┌──────────┐    ┌───────┐
                    │PostgreSQL│    │ Redis │
                    └────┬─────┘    └───┬───┘
                         │   healthy    │
                    ┌────┴──────────────┴────┐
                    │   alembic upgrade head  │
                    └───────────┬─────────────┘
        ┌───────┬───────┬──────┼──────┬────────┐
        ▼       ▼       ▼      ▼      ▼        ▼
    meeting  document  chat  dashboard brief  digest
    :8001    :8002    :8003   :8004   :8005   :8006
        │       │       │      │      │        │
        └───────┴───────┴──┬───┴──────┴────────┘
                           ▼
                     Nginx Gateway
                        :80
                           │
                     ┌─────┴─────┐
                     │ Frontend  │
                     │   :4200   │
                     └───────────┘
```

### Layer 1 — Infrastructure (Starts First)

Everything depends on these two containers. Docker Compose will not start any application service until both report healthy.

| Container | Port | Health Check | Timeout |
|-----------|------|-------------|---------|
| **PostgreSQL** (pgvector/pgvector:pg16) | 5432 | `pg_isready -U yoda` | 5s interval, 3s timeout, 5 retries |
| **Redis** (redis:7-alpine) | 6379 | `redis-cli ping` | 5s interval, 3s timeout, 5 retries |

### Layer 2 — Database Migrations (One-Time Prerequisite)

```bash
cd YODA-BB
DATABASE_URL=postgresql+asyncpg://yoda:yoda_dev@localhost:5432/yoda alembic upgrade head
```

Alembic creates all tables in a single shared PostgreSQL database. All 6 services use the same DB. The migration loads 12+ SQLAlchemy models from the foundation library (Meeting, MeetingParticipant, TranscriptSegment, MeetingSummary, ActionItem, Document, DocumentChunk, ChatSession, ChatMessage, WeeklyDigest, Notification, Project, etc.).

**Migrations must complete before any service starts.**

### Layer 3 — Foundation Library (Install Prerequisite)

```bash
cd YODA-BB/foundation
pip install -e ".[dev]"
```

Every service imports `yoda_foundation` for shared models, schemas, config, security, and database utilities. This must be installed before running any service.

### Layer 4 — Application Services (Start in Parallel)

Once PostgreSQL and Redis are healthy, **all 6 services start simultaneously**. They are completely independent of each other — no service depends on another service.

#### Service Startup Details

| Service | Port | Startup Weight | Key Startup Actions |
|---------|------|----------------|---------------------|
| **dashboard-service** | 8004 | Lightest | DB engine only. No Azure deps. Fastest to boot. |
| **document-service** | 8002 | Light | DB engine + optional GraphConnector. RAG components (embedder, vector store, chunker) lazy-load on first request. |
| **pre-meeting-brief-service** | 8005 | Light | DB engine + optional Graph client, AI connector, Redis cache. All Azure deps are optional. |
| **weekly-digest-service** | 8006 | Light | DB engine + optional AI connector + APScheduler (cron job for Friday digest generation). |
| **chat-service** | 8003 | Medium | DB engine + Redis cache (with MemoryCache fallback). Embedder, LLM, and RAG pipeline lazy-load on first request. |
| **meeting-service** | 8001 | Heaviest | DB engine + TokenProvider + GraphClient + BotCommander + AIProcessor + CalendarWatcher + NudgeScheduler + APScheduler. Also starts a background task to set up calendar subscriptions (30s timeout, non-blocking). |

#### What Each Service Initializes on Startup

**meeting-service** (most complex):
1. Load Settings, setup logging + OpenTelemetry
2. Initialize DB connection pool
3. Initialize TokenProvider (Azure AD), GraphClient (Microsoft Graph API)
4. Initialize APScheduler with two periodic jobs:
   - `nudge_scheduler.run()` — every 60 minutes
   - `calendar_watcher.renew_subscriptions()` — every 12 hours
5. Initialize BotCommander (ACS bot), AIProcessor, DeliveryService, PostProcessingService
6. Background: setup calendar subscriptions (non-blocking, 30s timeout)

**document-service**:
1. Load Settings, setup logging
2. Initialize DB engine + session factory
3. Initialize GraphConnector (optional, for SharePoint/OneDrive sync)
4. **Lazy on first request**: AzureEmbedder, PGVectorStore, RecursiveChunker (chunk_size=1000, overlap=200), SimilarityRetriever, IngestionPipeline, DocumentClassifier

**chat-service**:
1. Load Settings, setup logging
2. Initialize DB engine + session factory
3. Initialize cache (try Redis first, fallback to MemoryCache with 1000 entry limit)
4. **Lazy on first request**: AzureEmbedder, PGVectorStore, SimilarityRetriever, ContextBuilder, LLMAdapter, RAGPipeline (DSPy ChainOfThought module)

**dashboard-service**:
1. Load Settings, setup logging
2. Initialize DB engine
3. Ready — minimal startup, no external dependencies beyond DB + Redis

**pre-meeting-brief-service**:
1. Load Settings, setup logging
2. Initialize DB engine + session factory
3. Optional: Graph client, AI connector, Redis cache (all can be `None`)

**weekly-digest-service**:
1. Load Settings, setup logging
2. Initialize DB engine + session factory
3. Optional: AI connector, TokenProvider
4. Initialize APScheduler with cron job for digest generation (default: Friday afternoon)

### Layer 5 — Nginx API Gateway

```
Nginx (Port 80) — starts after all services are available
```

Routes requests by URL prefix to the correct service:

| Route | Service |
|-------|---------|
| `/api/meetings`, `/api/action-items`, `/api/admin`, `/api/bot-events`, `/webhooks`, `/health` | meeting-service:8010 |
| `/api/documents`, `/api/insights` | document-service:8011 |
| `/api/chat` | chat-service:8012 |
| `/api/dashboard`, `/api/notifications`, `/api/search`, `/api/settings` | dashboard-service:8013 |
| `/api/briefs` | pre-meeting-brief-service:8014 |
| `/api/digests` | weekly-digest-service:8015 |
| `/` (catch-all) | frontend:4200 |

WebSocket support is enabled (Upgrade/Connection headers). Max upload size: 50 MB.

### Layer 6 — Frontend

```
Angular (Port 4200) — starts in parallel with backend, no backend dependency at startup
```

The frontend is fully independent at boot time. It only needs the backend to be available when making API calls at runtime.

### Service Independence Matrix

| Service | PostgreSQL | Redis | Graph API | AI Foundry | ACS | Embeddings | Can Run Standalone? |
|---------|-----------|-------|-----------|------------|-----|-----------|---------------------|
| **dashboard-service** | Required | Required | — | — | — | — | **Yes** — fully independent |
| **document-service** | Required | Required | Optional | Optional | — | Required (for search) | Partially — needs embeddings for RAG |
| **pre-meeting-brief** | Required | Required | Optional | Optional | — | — | **Yes** — degrades gracefully |
| **weekly-digest** | Required | Required | Optional | Optional | — | — | **Yes** — degrades gracefully |
| **chat-service** | Required | Required | — | Required | — | Required | No — needs AI + embeddings |
| **meeting-service** | Required | Required | Required | Required | Required | — | No — needs Azure credentials |

### Key Gotchas

1. **Shared database** — All 6 services use one PostgreSQL instance; migrations must run first
2. **Lazy-loaded RAG** — Document and Chat services don't initialize embedder/LLM at startup; the first request will be slower
3. **Redis fallback** — Chat-service gracefully falls back to MemoryCache (1000 entries) if Redis is unavailable; other services log a warning but continue
4. **Calendar subscription timeout** — Meeting-service has a 30s timeout for initial subscription setup but continues if it fails (non-blocking)
5. **meeting-service is Azure-critical** — Requires valid `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `ACS_CONNECTION_STRING`, and `AI_FOUNDRY_ENDPOINT`
6. **Local dev tip** — Start only **dashboard-service** for the fastest feedback loop; it has zero Azure dependencies

---

## API Reference (For Developers)

YODA exposes REST APIs for each microservice:

| Service | Port | Base Path | Purpose |
|---------|------|-----------|---------|
| Meeting Service | 8001 | `/api/meetings` | Meetings, transcription, action items |
| Document Service | 8002 | `/api/documents` | Document management, RAG search |
| Chat Service | 8003 | `/api/chat` | AI-powered Q&A |
| Dashboard Service | 8004 | `/api/dashboard` | Stats, insights, notifications |
| Pre-Meeting Brief | 8005 | `/api/briefs` | Meeting preparation |
| Weekly Digest | 8006 | `/api/digests` | Weekly summaries |

Each service provides interactive API docs at `/docs` (Swagger UI) and `/redoc` when running locally.

---

## Running Tests

```bash
# Backend tests (323+ tests across all services)
cd YODA-BB
for svc in meeting document chat dashboard pre-meeting-brief weekly-digest; do
  PYTHONPATH=services/${svc}-service/src:foundation/src \
    pytest services/${svc}-service/tests/ -v
done

# Foundation library tests
PYTHONPATH=foundation/src pytest foundation/tests/ -v

# Frontend build verification
cd yoda-frontend
npx ng build --configuration=production
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Database connection error | Ensure PostgreSQL is running: `docker compose up -d postgres` |
| Redis connection error | Ensure Redis is running: `docker compose up -d redis` |
| Auth errors in development | Set `REQUIRE_AUTH=false` to bypass authentication locally |
| Missing AI features | Verify `AI_FOUNDRY_ENDPOINT` and `AI_FOUNDRY_API_KEY` in `.env` |
| Frontend won't start | Run `npm install` in `yoda-frontend/` and ensure Node.js 20+ |
| Migration errors | Run `alembic upgrade head` from the `YODA-BB/` directory |
