"""Unified YODA API -- single FastAPI application.

Merges all former microservices (meeting, document, chat, dashboard,
pre-meeting-brief) into one process. Routes are organized by domain
sub-package with their original URL prefixes preserved.
"""

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from functools import lru_cache

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from yoda_api.config import Settings
from yoda_api.dependencies import init_db, init_cache, get_session_factory, get_engine
from yoda_api.utils.logging_config import setup_logging

logger = logging.getLogger(__name__)


@lru_cache
def _get_settings() -> Settings:
    return Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Unified startup / shutdown lifecycle.

    Startup:
    1. Logging + telemetry
    2. DB + cache initialization
    3. Meeting-domain services (Graph, APScheduler, bot commander)
    4. Document-domain services (Graph connector, document service)
    5. Brief-domain services (Graph, AI, cache)

    Shutdown:
    1. Stop scheduler
    2. Close HTTP clients
    3. Dispose DB engine
    """
    settings = _get_settings()
    setup_logging(debug=settings.DEBUG)

    from yoda_api.utils.telemetry import setup_telemetry
    setup_telemetry(app)

    logger.info("Starting YODA API")

    # ── Database + Cache ────────────────────────────────────────────
    init_db(settings)
    await init_cache(settings)
    session_factory = get_session_factory()
    app.state.settings = settings

    # ── Auth warnings ───────────────────────────────────────────────
    if settings.REQUIRE_AUTH and not settings.AZURE_AD_AUDIENCE:
        logger.critical(
            "SECURITY: AZURE_AD_AUDIENCE is empty while REQUIRE_AUTH is True. "
            "All requests will bypass JWT validation and receive Admin role. "
            "Set AZURE_AD_AUDIENCE or set REQUIRE_AUTH=false for dev mode."
        )

    # ── Meeting-domain services ─────────────────────────────────────
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from yoda_foundation.utils.auth.token_provider import TokenProvider

    from yoda_api.meetings.services.ai_processor import AIProcessor
    from yoda_api.meetings.services.bot_commander import (
        BotCommander,
        set_shared_bot_commander,
    )
    from yoda_api.meetings.services.calendar_watcher import CalendarWatcher
    from yoda_api.meetings.services.delivery import DeliveryService
    from yoda_api.meetings.services.graph_client import GraphClient
    from yoda_api.meetings.services.nudge_scheduler import NudgeScheduler
    from yoda_api.meetings.services.owner_resolver import OwnerResolver
    from yoda_api.meetings.services.post_processing import PostProcessingService

    token_provider = TokenProvider(
        tenant_id=settings.AZURE_TENANT_ID,
        client_id=settings.AZURE_CLIENT_ID,
        client_secret=settings.AZURE_CLIENT_SECRET,
    )
    graph_client = GraphClient(token_provider=token_provider)
    scheduler = AsyncIOScheduler()
    bot_commander = BotCommander(settings=settings)
    set_shared_bot_commander(bot_commander)

    app.state.token_provider = token_provider
    app.state.graph_client = graph_client
    app.state.scheduler = scheduler
    app.state.bot_commander = bot_commander

    ai_processor = AIProcessor(settings=settings)
    app.state.ai_processor = ai_processor

    owner_resolver = OwnerResolver(graph_client=graph_client)
    app.state.owner_resolver = owner_resolver

    delivery_service = DeliveryService(graph_client=graph_client, settings=settings)
    app.state.delivery_service = delivery_service

    post_processing = PostProcessingService(session_factory=session_factory)
    post_processing.ai_processor = ai_processor
    post_processing.owner_resolver = owner_resolver
    post_processing.delivery_service = delivery_service
    app.state.post_processing = post_processing

    calendar_watcher = CalendarWatcher(
        graph_client=graph_client,
        session_factory=session_factory,
        scheduler=scheduler,
        settings=settings,
    )
    app.state.calendar_watcher = calendar_watcher

    nudge_scheduler = NudgeScheduler(
        delivery=delivery_service,
        session_factory=session_factory,
        settings=settings,
    )
    app.state.nudge_scheduler = nudge_scheduler

    # Schedule periodic tasks
    scheduler.add_job(
        nudge_scheduler.run,
        "interval",
        minutes=settings.NUDGE_CHECK_INTERVAL_MINUTES,
        id="nudge_check",
    )
    scheduler.add_job(
        calendar_watcher.renew_subscriptions,
        "interval",
        hours=12,
        id="subscription_renewal",
    )
    scheduler.start()
    logger.info("Scheduler started")

    subscription_task: asyncio.Task[None] | None = None

    async def _setup_calendar_subscriptions() -> None:
        try:
            await asyncio.wait_for(
                calendar_watcher.setup_subscriptions(), timeout=30,
            )
            logger.info("Calendar subscriptions initialized")
        except asyncio.TimeoutError:
            logger.warning("Calendar subscription setup timed out; continuing")
        except Exception:
            logger.exception("Failed to set up calendar subscriptions")

    subscription_task = asyncio.create_task(_setup_calendar_subscriptions())

    # ── Document-domain services ────────────────────────────────────
    from yoda_foundation.data_access.connectors.graph_connector import GraphConnector
    from yoda_foundation.data_access.base.connector import ConnectorConfig

    graph_connector = None
    if settings.AZURE_TENANT_ID and settings.AZURE_CLIENT_ID and settings.AZURE_CLIENT_SECRET:
        graph_config = ConnectorConfig(timeout=30.0, retry_attempts=3)
        graph_connector = GraphConnector(
            config=graph_config, token_provider=token_provider,
        )
        logger.info("GraphConnector initialized for document sync")
    else:
        logger.warning("Graph-based document sync disabled (no Azure creds)")

    from yoda_api.documents.services.document_service import DocumentService

    app.state.document_service = DocumentService(
        graph_connector=graph_connector,
        db_session_factory=session_factory,
        ingestion_pipeline=None,  # lazy-loaded on first use
    )

    # ── Brief-domain services ───────────────────────────────────────
    brief_graph_client = None
    try:
        from yoda_api.briefs.services.graph_client import GraphClient as BriefGraphClient

        if settings.AZURE_TENANT_ID and settings.AZURE_CLIENT_ID:
            brief_graph_client = BriefGraphClient(token_provider=token_provider)
            logger.info("Brief graph client initialized")
    except Exception:
        logger.warning("Brief graph client not available")

    brief_ai_connector = None
    try:
        if settings.AI_FOUNDRY_ENDPOINT and settings.AI_FOUNDRY_API_KEY:
            from yoda_foundation.data_access.connectors.ai_foundry_connector import (
                AIFoundryConnector,
            )

            connector_config = ConnectorConfig(name="ai-foundry-briefs")
            brief_ai_connector = AIFoundryConnector(
                config=connector_config,
                endpoint=settings.AI_FOUNDRY_ENDPOINT,
                api_key=settings.AI_FOUNDRY_API_KEY,
            )
            logger.info("Brief AI connector initialized")
    except Exception:
        logger.warning("Brief AI connector not available")

    brief_cache = None
    try:
        if settings.REDIS_URL:
            from yoda_foundation.utils.caching import RedisCache, CacheConfig

            brief_cache = RedisCache(
                config=CacheConfig(
                    default_ttl_seconds=settings.BRIEF_CACHE_TTL_SECONDS,
                    key_prefix="brief",
                ),
                redis_url=settings.REDIS_URL,
            )
            await brief_cache._client.ping()
            logger.info("Brief cache initialized")
    except Exception:
        logger.warning("Brief cache not available")

    app.state.brief_graph_client = brief_graph_client
    app.state.brief_ai_connector = brief_ai_connector
    app.state.brief_cache = brief_cache

    logger.info("YODA API started successfully")

    yield

    # ── Shutdown ────────────────────────────────────────────────────
    scheduler.shutdown(wait=False)
    if subscription_task is not None and not subscription_task.done():
        subscription_task.cancel()
        with suppress(asyncio.CancelledError):
            await subscription_task
    set_shared_bot_commander(None)
    await bot_commander.close()
    await graph_client.close()
    if brief_graph_client and hasattr(brief_graph_client, "close"):
        await brief_graph_client.close()
    try:
        from yoda_api.dependencies import get_cache
        cache = get_cache()
        await cache.close()
    except Exception:
        pass
    engine = get_engine()
    if engine is not None:
        await engine.dispose()
    logger.info("YODA API shut down")


app = FastAPI(
    title="YODA API",
    description="Unified Teams Meeting Assistant API",
    version="1.0.0",
    lifespan=lifespan,
    root_path="/yoda-api",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_settings().CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Correlation-Id"],
)

# ── Health (unified) ─────────────────────────────────────────────────
from fastapi import APIRouter

health_router = APIRouter()


@health_router.get("/health")
async def health():
    return {"status": "healthy", "service": "yoda-api"}


app.include_router(health_router, tags=["health"])

# ── Meeting routes ───────────────────────────────────────────────────
from yoda_api.meetings.routes.meetings import router as meetings_router  # noqa: E402
from yoda_api.meetings.routes.action_items import router as action_items_router  # noqa: E402
from yoda_api.meetings.routes.webhooks import router as webhooks_router  # noqa: E402
from yoda_api.meetings.routes.admin import router as admin_router  # noqa: E402
from yoda_api.meetings.routes.bot_events import router as bot_events_router  # noqa: E402
from yoda_api.meetings.routes.sse import router as sse_router  # noqa: E402

app.include_router(webhooks_router, prefix="/webhooks", tags=["webhooks"])
app.include_router(meetings_router, prefix="/api/meetings", tags=["meetings"])
app.include_router(action_items_router, prefix="/api/action-items", tags=["action-items"])
app.include_router(admin_router, prefix="/api/admin/users", tags=["admin"])
app.include_router(bot_events_router, prefix="/api/bot-events", tags=["bot-events"])
app.include_router(sse_router, tags=["sse"])

# ── Document routes ──────────────────────────────────────────────────
from yoda_api.documents.routes.documents import router as documents_router  # noqa: E402

app.include_router(documents_router, prefix="/api/documents", tags=["documents"])

# ── Chat routes ──────────────────────────────────────────────────────
from yoda_api.chat.routes.chat import router as chat_router  # noqa: E402

app.include_router(chat_router, prefix="/api/chat", tags=["chat"])

# ── Dashboard routes ─────────────────────────────────────────────────
from yoda_api.dashboard.routes.dashboard import router as dashboard_router  # noqa: E402
from yoda_api.dashboard.routes.insights import router as insights_router  # noqa: E402
from yoda_api.dashboard.routes.notifications import router as notifications_router  # noqa: E402
from yoda_api.dashboard.routes.search import router as search_router  # noqa: E402
from yoda_api.dashboard.routes.user_settings import router as user_settings_router  # noqa: E402

app.include_router(dashboard_router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(insights_router, prefix="/api/insights", tags=["insights"])
app.include_router(notifications_router, prefix="/api/notifications", tags=["notifications"])
app.include_router(search_router, prefix="/api/search", tags=["search"])
app.include_router(user_settings_router, prefix="/api/settings", tags=["settings"])

# ── Brief routes ─────────────────────────────────────────────────────
from yoda_api.briefs.routes.briefs import router as briefs_router  # noqa: E402

app.include_router(briefs_router, tags=["briefs"])
