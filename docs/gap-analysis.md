# YODA Gap Analysis

Comprehensive analysis of gaps across the backend (YODA-BB), frontend (yoda-frontend), and infrastructure layers. No fixes — documentation only.

---

## 1. Testing Gaps

### Foundation Library: ~5% Coverage

The foundation library has **158 source files across 7 major modules with zero unit tests**. Only import smoke tests and DSPy integration tests exist.

| Module | Source Files | Tests | Risk |
|--------|:-----------:|:-----:|------|
| RAG (chunking, embeddings, retrieval, pipeline, evaluation) | 35 | 0 | Critical — used by chat-service |
| Security/RBAC (JWT, roles, secrets, data governance) | 21 | 0 | Critical — used by all services |
| Resilience (circuit breaker, retry, bulkhead, timeout, dead letter, recovery) | 32 | 0 | Critical — production stability |
| Guardrails (jailbreak, content safety, prompt injection, encoding) | 12 | 0 | Critical — AI safety |
| Events (bus, handlers, triggers, sourcing, streaming) | 25 | 0 | High |
| Memory (working, episodic, semantic, procedural, consolidation, decay) | 16 | 0 | High |
| Middleware (correlation ID, error handler, rate limiter, security headers) | 6 | 0 | Medium |

### Service Tests: Reasonable but Heavily Mocked

| Service | Test Functions | Assertions | Mock Calls | Coverage |
|---------|:-----------:|:----------:|:----------:|----------|
| chat-service | 14 | 32 | 23 | ~80% of routes |
| dashboard-service | 28 | 127 | 25 | ~70% of routes |
| document-service | 49 | 92 | 192 | ~86% of routes |
| meeting-service | 38 | 143 | 180 | ~68% of routes |
| pre-meeting-brief-service | 10 | 20 | 21 | ~100% |
| weekly-digest-service | 10 | 25 | 6 | ~100% |

- Document and meeting services have mock-to-assertion ratios >1:1, limiting integration confidence
- No cross-service integration tests (e.g., meeting -> RAG ingestion -> chat retrieval)
- No end-to-end test suites
- Dashboard phase6 AI features test file exists but has no test functions

### Frontend Tests: Effectively Zero

- Only `app.spec.ts` exists — auto-generated scaffold (create + render tests)
- No component, service, or integration tests for any of the 10 feature modules
- CI runs `ng test` with `|| true`, so failures are silently ignored

---

## 2. Security Gaps

### Dual Auth Implementations

Meeting-service has its own `utils/azure_ad_auth.py` separate from the foundation's `security/auth_dependency.py`. The meeting-service version grants Admin role to all requests when `AZURE_AD_AUDIENCE` is unset:

```python
# meeting-service/utils/azure_ad_auth.py:46-47
if not settings.AZURE_AD_AUDIENCE:
    return {"sub": "dev-user", "name": "Developer", "roles": ["Admin"]}
```

Other services use the foundation auth. This inconsistency creates maintenance risk and a potential privilege escalation path if AZURE_AD_AUDIENCE is accidentally unset in production.

### RBAC Framework Not Enforced

The foundation has a complete RBAC framework (role hierarchy, permission engine, permission caching), but:
- No routes use `@requires_permission()` decorators
- Routes extract `SecurityContext` from JWT but never check permissions
- Data scoping uses `user_id` filtering, not role-based restrictions
- StandardRoles (Admin, Manager, User, Viewer) defined but never referenced by services

### Middleware Not Applied

Foundation defines production-ready middleware that no service actually registers:
- `SecurityHeadersMiddleware` (HSTS, X-Frame-Options, CSP, etc.) — not added to any service
- `RateLimiterMiddleware` (token-bucket per IP) — not added to any service
- `CorrelationIdMiddleware` — not added to any service
- `LoggingMiddleware` — not added to any service
- Only CORS middleware is actually registered

### Unprotected Endpoints

- `POST /webhooks/graph` in meeting-service has no authentication — Graph webhook signatures are not validated, only in-memory rate limiting
- Health endpoints are unauthenticated (expected/acceptable)

### Frontend Token Handling

- Tokens stored in localStorage (MSAL default) — vulnerable to XSS
- No explicit token refresh logic visible (relies on MSAL silent refresh)
- No 401 response handling to trigger re-login
- Environment configs have placeholder values (`'your-tenant-id'`, `'your-client-id'`)

---

## 3. Infrastructure Gaps

### Docker Compose

- **No service health checks**: All 6 microservices + meeting-assistant + browser-bot have `/health` endpoints but docker-compose doesn't probe them. Only PostgreSQL and Redis have health checks. If a service crashes, Nginx routes to a dead upstream.
- **No Nginx health check**: The critical API gateway has no health probe
- **Root docker-compose.yml missing init-db.sql**: The minimal compose has it, the full one doesn't
- **No persistent log volumes**: Services log to stdout only

### Dockerfiles

- **Running as root**: No non-root USER directive in any service Dockerfile
- **No .dockerignore files**: All files copied including .git, __pycache__, .pytest_cache
- **No HEALTHCHECK instruction**: `docker run` health monitoring won't work
- **Missing Python optimization flags**: No `PYTHONUNBUFFERED=1` or `PYTHONDONTWRITEBYTECODE=1`
- **No build labels**: Missing LABEL metadata (version, build date)

### Nginx Gateway

- **No SSL/TLS configuration**: HTTP only, no HTTPS
- **No proxy timeouts**: Missing `proxy_connect_timeout`, `proxy_send_timeout`, `proxy_read_timeout` — slow operations (document uploads, RAG processing) may timeout at defaults
- **No rate limiting**: No upstream connection limits
- **No caching directives**: Static frontend assets not cached
- **No gzip compression**: Missing `gzip on;` for bandwidth
- **No error pages**: No `error_page` directives for backend failures
- **No upstream health detection**: No `fail_timeout` or `max_fails`

### CI/CD Pipeline

| Present | Missing |
|---------|---------|
| Unit tests for all 6 services + foundation | No deployment pipeline (no Docker build, no registry push, no Azure Container Apps deploy) |
| Frontend production build | No type checking in CI (Pyright in dev deps but never run) |
| Ruff lint (E, W, F rules only, E501 ignored) | No ESLint/TypeScript checks for frontend |
| npm/pip caching | No security scanning (SAST, dependency vulnerabilities) |
| Matrix strategy for parallel service tests | No database migration testing (alembic upgrade/downgrade) |
| | No integration tests between services |
| | No test artifact preservation (coverage reports) |
| | Frontend test failures silently ignored (`|| true`) |

---

## 4. Database Gaps

### Missing Indexes

- **No vector index on `document_chunks.embedding`**: The pgvector column exists but no IVFFLAT or HNSW index — similarity search will do sequential scan
- **No foreign key indexes**: `meeting_id` columns across multiple tables (transcript_segments, action_items, meeting_summaries, etc.) lack indexes — slow joins at scale

### Missing Constraints

- `meeting.teams_meeting_id` should likely be UNIQUE but isn't
- No composite uniqueness constraints where expected (e.g., `chat_session.user_id + title`)

### Migration History

- Only 2 migration revisions total — limited schema evolution tracking
- No documented testing of downgrade/rollback paths

---

## 5. Environment Configuration Gaps

### 31 Environment Variables Used in Code but Not in .env.example

**Core**: `APP_NAME`, `APP_VERSION`, `DEBUG`, `LOG_LEVEL`, `LOG_JSON`, `HOST`, `PORT`

**Database/Cache**: `DATABASE_POOL_SIZE`, `DATABASE_MAX_OVERFLOW`, `REDIS_CACHE_DEFAULT`, `REDIS_CACHE_BRIEF`, `REDIS_CACHE_GRAPH`, `REDIS_CACHE_EMBEDDING`, `REDIS_CACHE_LLM`, `REDIS_CACHE_DASHBOARD`, `REDIS_KEY_PREFIX`

**Auth**: `AZURE_ISSUER`, `AZURE_JWKS_URI`, `AZURE_API_SCOPE`, `GRAPH_WEBHOOK_SECRET`

**ACS/Bot**: `ACS_CALLBACK_BASE_URL`, `ACS_CALLBACK_SECRET`, `AUTO_JOIN_ENABLED`, `BOT_JOIN_BEFORE_MINUTES`

**AI**: `AI_FOUNDRY_DEPLOYMENT_NAME`, `AI_FOUNDRY_DEPLOYMENT_NAME_COMPLEX`, `CHUNK_SIZE`, `CHUNK_OVERLAP`, `EMBEDDING_DIMENSIONS`, `DSPY_CACHE_ENABLED`, `DSPY_CACHE_TTL`

**Nudging**: `NUDGE_CHECK_INTERVAL_MINUTES`, `NUDGE_COOLDOWN_HOURS`, `NUDGE_ESCALATION_THRESHOLD`, `ESCALATION_DAYS`, `LONG_MEETING_THRESHOLD_MINUTES`

**Observability**: `OTEL_EXPORTER_ENDPOINT`, `OTEL_SERVICE_NAME`

**Rate Limiting**: `RATE_LIMIT_RPM`, `RATE_LIMIT_BURST`

### Naming Mismatches

- `.env.example` has `AI_FOUNDRY_DEPLOYMENT` but code expects `AI_FOUNDRY_DEPLOYMENT_NAME`
- `.env.example` has `AZURE_OPENAI_EMBEDDING_API_KEY` but code references `AZURE_OPENAI_EMBEDDING_KEY`

---

## 6. Frontend Gaps

### Missing Feature: Notifications

- `features/notifications/` directory exists but is empty (0 files)
- Not wired in app.routes.ts
- Referenced in requirements but unimplemented

### Incomplete Features

- **Settings page**: Notification toggle preferences are local-only (localStorage), not persisted to backend
- **Insights page**: "Decision Velocity" card marked "Coming soon" — placeholder
- **Models index**: `index.ts` doesn't export digest or notification models

### API Contract Risk

- All 10+ services make real HTTP calls to `/api/*` endpoints
- No API client code generation from OpenAPI specs — contract changes require manual sync between frontend services and backend routes
- No mock service layer for offline development

---

## 7. RAG Pipeline Gaps (Functional but Untested)

The RAG pipeline is fully implemented and production-ready, but:

- **No automated quality evaluation**: `rag/evaluation/` module exists but no test harness exercising it
- **No embedding drift detection**: Embeddings may degrade over time with model updates
- **No chunk quality validation**: No tests verifying chunking produces correct splits for different document types
- **No retrieval accuracy benchmarks**: No golden dataset for measuring search precision/recall
- **Citation tracking untested**: `rag/context/citation_tracker.py` handles source attribution but has no tests

---

## 8. Cross-Cutting Gaps

### Observability

- OpenTelemetry tracing, metrics, and logging modules exist in foundation
- No evidence of OTel SDK initialization in any service's `main.py`
- No Prometheus metrics endpoint exposed
- No distributed tracing correlation across services

### Secrets Management

- Foundation has `security/secrets/azure_keyvault.py` and `vault_client.py`
- No service integrates with Key Vault — all secrets loaded from environment variables
- `.env` file in repo contains real API keys and client secrets (should be rotated and removed from history)

### Error Recovery

- Foundation has comprehensive recovery patterns (checkpoint, state recovery, dead letter queue)
- No service integrates these patterns — services use basic try/except
