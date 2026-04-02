# CXO AI Companion — Architecture Overview

## 1. What Is This Application

The CXO AI Companion is an **AI-powered executive assistant** that connects to a CXO's Microsoft 365 environment (calendar, email, Teams, OneDrive) and provides:

- **Pre-meeting briefs**: Who you're meeting, what was decided last time, what documents changed, what questions to ask
- **Live meeting transcription**: Bot joins Teams calls, transcribes in real time
- **Post-meeting summaries**: AI-extracted decisions, action items with owners/deadlines, conflict detection
- **Ask AI (RAG chat)**: Natural language Q&A across all meetings, documents, and emails
- **Action item tracking**: Automatically extracted, assigned, and followed up
- **Insights & analytics**: Meeting time analysis, collaboration patterns, decision velocity, recurring topics
- **Weekly digests**: Automated executive summary of the week
- **Notifications**: Real-time alerts for summaries, assignments, overdue items, conflicts

---

## 2. Architecture Style

```
┌─────────────────────────────────────────────────────────────┐
│                    MONOLITHIC FastAPI APP                     │
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────────┐ │
│  │  Routes   │  │ Services │  │   RAG    │  │    DSPy     │ │
│  │ (REST API)│→ │ (Logic)  │→ │ Pipeline │  │ (Structured │ │
│  └──────────┘  └──────────┘  └──────────┘  │  Extraction)│ │
│       │             │             │         └─────────────┘ │
│       │             ▼             ▼                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                  │
│  │ Schemas  │  │  Models  │  │ pgvector │                  │
│  │(Pydantic)│  │(SQLAlch) │  │ (Vectors)│                  │
│  └──────────┘  └──────────┘  └──────────┘                  │
│                      │                                       │
└──────────────────────┼───────────────────────────────────────┘
                       │
            ┌──────────┼──────────┐
            ▼          ▼          ▼
     ┌──────────┐ ┌────────┐ ┌───────────┐
     │PostgreSQL│ │ Azure  │ │ Microsoft │
     │+ pgvector│ │AI Found│ │ Graph API │
     └──────────┘ └────────┘ └───────────┘
```

**Style**: API-driven monolith (single deployable unit)
**NOT microservices** — all code runs in one process, shares one database, one deployment

### Why monolith (for now)
- Single team, single deployment target (Azure Container Apps)
- All services share the same database (meetings, actions, summaries, vectors)
- Simpler to develop, test, and deploy
- Can be split later along clear service boundaries (see Section 10)

---

## 3. Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Framework** | FastAPI (async) | REST API, dependency injection, OpenAPI docs |
| **Language** | Python 3.11+ | Async/await everywhere |
| **Database** | PostgreSQL + pgvector | Relational data + vector embeddings |
| **ORM** | SQLAlchemy 2.0 (async) | Mapped models, async sessions, asyncpg driver |
| **Migrations** | Alembic | Schema versioning and upgrades |
| **Schemas** | Pydantic v2 | Request/response validation, serialization |
| **Auth** | MSAL + PyJWT | Daemon flow (bot) + Delegated flow (user SSO) |
| **AI** | Azure AI Foundry (GPT-4o-mini/4o) | Summarization, extraction, question generation |
| **Embeddings** | Azure OpenAI (text-embedding-3-small) | 1536-dim vectors for semantic search |
| **Structured AI** | DSPy | Typed signatures for extraction with confidence |
| **Call Automation** | Azure Communication Services | Join Teams meetings, transcribe, record |
| **Microsoft 365** | Microsoft Graph API | Calendar, email, Teams, OneDrive, directory |
| **Observability** | OpenTelemetry | Tracing, metrics, structured logging |
| **Deploy** | Docker → Azure Container Apps | Containerized deployment |

---

## 4. Layer Architecture

```
Request → Route → Service → Repository → Database
                     ↓
              External APIs (Graph, AI Foundry, ACS)
```

### 4.1 Routes (`api/rest/routes/`)

REST API endpoints. Each route file maps to a resource:
- `meetings.py` — CRUD + calendar view + brief + summary + conflicts
- `action_items.py` — CRUD + filtering by status/owner
- `chat.py` — Chat sessions + messages (RAG-powered)
- `dashboard.py` — Stats, attention items, activity feed
- `documents.py` — Document CRUD + upload
- `insights.py` — Analytics, collaboration, patterns
- `notifications.py` — List, count, mark read
- `projects.py` — CRUD + meeting linking
- `search.py` — Global search across meetings/docs/actions

Routes validate input (Pydantic schemas), call services, and return responses. They do NOT contain business logic.

### 4.2 Services (`services/`)

Business logic layer. Each service encapsulates a domain:

| Service | Domain | External Dependencies |
|---------|--------|----------------------|
| `GraphClient` | Microsoft 365 access | Graph API |
| `CalendarWatcher` | Detect upcoming meetings | Graph subscriptions |
| `ACSCallService` | Join/leave Teams calls | ACS Call Automation |
| `TranscriptionHandler` | Process transcript chunks | ACS WebSocket |
| `AIProcessor` | Summarize, extract actions/decisions | AI Foundry + DSPy |
| `OwnerResolver` | Match names → user IDs | Fuzzy matching + Graph |
| `DeliveryService` | Send summaries to Teams/email | Graph API |
| `NudgeScheduler` | Remind about overdue actions | APScheduler |
| `DashboardService` | Aggregate dashboard stats | Database |
| `PreMeetingService` | Generate pre-meeting briefs | Graph + DB + AI |
| `ChatService` | RAG-powered Q&A | RAG Pipeline |
| `DocumentService` | Ingest/manage documents | Ingestion Pipeline |
| `InsightService` | Analytics and patterns | Database |
| `WeeklyDigestService` | Generate weekly summaries | AI + Database |
| `NotificationService` | Create/manage notifications | Database |
| `ConflictDetectionService` | Detect decision contradictions | AI + Database |

### 4.3 Data Access (`data_access/repositories/`)

Generic Repository pattern. Each repository extends `GenericRepository[T]`:
- `MeetingRepository`, `SummaryRepository`, `ActionItemRepository`
- `TranscriptRepository`, `DocumentRepository`, `InsightRepository`
- `NotificationRepository`, `ProjectRepository`

Key pattern: repositories use `flush()` (not `commit()`) — the route-level `get_db()` dependency handles commit/rollback.

### 4.4 Models (`models/`)

SQLAlchemy 2.0 ORM models. All use `UUIDMixin` (UUID PK) + `TimestampMixin` (created_at, updated_at):
- `Meeting`, `MeetingParticipant` — Core meeting data
- `TranscriptSegment` — Transcript chunks from ACS
- `MeetingSummary` — AI-generated summary with decisions, topics, questions
- `ActionItem` — Extracted tasks with owner, deadline, confidence
- `Document`, `DocumentChunk` — Uploaded files with vector embeddings
- `MeetingInsight` — AI analytics (conflicts, sentiment, patterns)
- `WeeklyDigest` — Aggregated weekly summary
- `Notification` — User notifications
- `Project`, `project_meetings_table` — Project tracking with meeting links

### 4.5 Schemas (`schemas/`)

Pydantic v2 models for API validation:
- `*Response` — Output schemas (`ConfigDict(from_attributes=True)`)
- `*Request` — Input schemas (create/update)
- `*ListResponse` — Paginated lists (`items: list[T], total: int`)

### 4.6 Security (`security/`)

- `SecurityContext` — Propagated through all operations (user_id, tenant_id, roles, permissions)
- `JWTValidator` — Validates Entra ID tokens from React frontend
- `auth_dependency` — FastAPI `Depends()` for protected routes
- `TokenProvider` — MSAL client-credentials (bot) + OBO (user) token acquisition

---

## 5. Authentication Flows

### Flow 1: Delegated (User Sign-In from React)

```
React → MSAL.js login → Entra ID → JWT access token
→ React sends Bearer token to FastAPI
→ JWTValidator decodes + validates
→ SecurityContext(user_id, tenant_id, roles) created
→ OBO flow: backend calls Graph API as the signed-in user
```

### Flow 2: Daemon (Bot Background Tasks)

```
Bot scheduler triggers → MSAL client-credentials
→ App-only token (no user context)
→ Graph API / ACS with application permissions
```

---

## 6. Data Flow: Meeting Lifecycle

```
1. Calendar Event Detected (Graph webhook / CalendarWatcher)
         ↓
2. Meeting Created in DB (status: scheduled)
         ↓
3. Bot Joins Meeting (ACSCallService → ACS Call Automation)
         ↓  status: in_progress
4. Live Transcription (ACS WebSocket → TranscriptionHandler)
         ↓  TranscriptSegments stored
5. Meeting Ends (CallDisconnected callback)
         ↓  status: completed
6. Post-Processing Pipeline (background task)
   ├── AIProcessor: summarize transcript → MeetingSummary
   ├── AIProcessor: extract action items → ActionItem[]
   ├── AIProcessor: detect decisions → MeetingSummary.decisions
   ├── OwnerResolver: match names → user IDs
   ├── ConflictDetection: compare decisions against history
   └── DeliveryService: send summary to Teams chat
         ↓
7. User Accesses via React App
   ├── Dashboard: stats, attention items, activity feed
   ├── Pre-Meeting Brief: context for next meeting
   ├── Summary: review/edit/share
   ├── Ask AI: RAG Q&A across all data
   └── Insights: analytics and patterns
```

---

## 7. Database Schema (Key Tables)

```
meetings
  ├── meeting_participants (1:N)
  ├── transcript_segments (1:N)
  ├── meeting_summary (1:1)
  ├── action_items (1:N)
  ├── documents (1:N)
  │     └── document_chunks (1:N, with vector embedding)
  └── meeting_insights (1:N)

notifications (standalone, indexed by user_id)
projects → project_meetings (M:N with meetings)
weekly_digests (standalone, indexed by user_id)
```

---

## 8. External Service Integration

### Microsoft Graph API (`services/graph_client.py`)
- **Calendar**: List events, create/renew subscriptions, detect meetings
- **Users**: Get profile, search directory, list org users
- **Email**: Read messages, filter by participants, get recent threads
- **Teams**: Send chat messages, proactive notifications
- **Files**: Get recent OneDrive/SharePoint documents
- **Meetings**: Get online meeting details, join URLs

### Azure Communication Services (`services/acs_call_service.py`)
- **Call Automation**: Join Teams meetings as a bot
- **Media Streaming**: WebSocket audio stream
- **Transcription**: Real-time speech-to-text via WebSocket
- **Callbacks**: CloudEvent webhooks for call lifecycle events

### Azure AI Foundry (`services/ai_processor.py`)
- **GPT-4o-mini**: Fast summarization, action extraction, question generation
- **GPT-4o**: Complex analysis (conflict detection, insight generation)
- **DSPy integration**: Structured extraction with typed signatures and confidence scores

### Azure OpenAI Embeddings (`rag/embeddings/azure_embedder.py`)
- **text-embedding-3-small**: 1536-dimension vectors for semantic search
- Used by the RAG pipeline for document and query embedding

---

## 9. Dependency Injection

All singletons are managed in `dependencies.py`:

```python
get_settings()          → Settings (pydantic-settings, from .env)
get_db()                → AsyncSession (per-request, auto commit/rollback)
get_session_factory()   → async_sessionmaker (for services managing own sessions)
get_embedder()          → AzureEmbedder
get_vector_store()      → PGVectorStore
get_chunker()           → RecursiveChunker
get_retriever()         → SimilarityRetriever
get_context_builder()   → ContextBuilder
get_citation_tracker()  → CitationTracker (per-request)
get_ingestion_pipeline()→ IngestionPipeline
get_rag_pipeline()      → RAGPipeline
get_llm_adapter()       → CachedLLMAdapter
```

---

## 10. Future: Microservice Split Points

If you need to split into microservices later, these are the natural boundaries:

| Potential Service | Current Location | Why it's separable |
|-------------------|-----------------|-------------------|
| **Meeting Ingestion** | ACSCallService + TranscriptionHandler | Stateful WebSocket connections, different scaling profile |
| **AI Processing** | AIProcessor + DSPy modules | GPU/compute-intensive, could scale independently |
| **RAG Pipeline** | rag/ package + DocumentService | Vector search is I/O intensive, separate scaling |
| **Notification Service** | NotificationService | Event-driven, could be async queue consumer |
| **Calendar Sync** | CalendarWatcher + GraphClient | Runs on timer, doesn't need to be in request path |

Each would communicate via async message queue (Redis/Azure Service Bus) with the shared PostgreSQL database, or with dedicated databases per service.

---

## 11. API Endpoints Summary

| Prefix | Resource | Key Endpoints |
|--------|----------|---------------|
| `/api/meetings` | Meetings | CRUD, calendar view, brief, summary, conflicts, join/leave |
| `/api/action-items` | Action Items | CRUD, filter by status/owner |
| `/api/chat` | Ask AI (RAG) | Sessions, messages with citations |
| `/api/dashboard` | Dashboard | Stats, attention items, activity feed |
| `/api/documents` | Documents | CRUD, upload, ingestion |
| `/api/insights` | Insights | Analytics, collaboration, patterns, weekly digest |
| `/api/notifications` | Notifications | List, count, mark read |
| `/api/projects` | Projects | CRUD, link/unlink meetings |
| `/api/search` | Global Search | Cross-entity search (meetings, docs, actions) |
| `/callbacks/acs` | ACS Callbacks | Call lifecycle webhooks |
| `/webhooks/graph` | Graph Webhooks | Calendar subscription notifications |

All endpoints return JSON. OpenAPI docs auto-generated at `/docs` (Swagger UI) and `/redoc`.

---

## 12. Deployment

```
┌──────────────────────────────────┐
│     Azure Container Apps         │
│                                  │
│  ┌────────────────────────────┐  │
│  │   FastAPI Container        │  │
│  │   (uvicorn, 1+ replicas)  │  │
│  └────────────┬───────────────┘  │
│               │                  │
│  ┌────────────┴───────────────┐  │
│  │   PostgreSQL + pgvector    │  │
│  │   (Azure DB for PostgreSQL)│  │
│  └────────────────────────────┘  │
│                                  │
│  ┌────────────────────────────┐  │
│  │   Redis (optional)         │  │
│  │   (rate limiting, caching) │  │
│  └────────────────────────────┘  │
└──────────────────────────────────┘
         │          │          │
         ▼          ▼          ▼
   Azure AI    Microsoft    Azure
   Foundry     Graph API    ACS
```

**Docker**: `deployment/docker-compose.yml` for local dev
**Production**: Azure Container Apps with managed PostgreSQL
