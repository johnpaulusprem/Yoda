"""FastAPI entry point for the meeting service.

Creates the FastAPI application, wires up the async lifespan (DB engine,
Graph client, APScheduler for nudges and subscription renewal, calendar
watcher), registers CORS middleware, and mounts all route modules. Services
are instantiated during lifespan startup and stored on ``app.state`` for
dependency injection.
"""

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from functools import lru_cache

from fastapi import FastAPI

from meeting_service.config import Settings
from meeting_service.dependencies import async_session_factory, engine
from meeting_service.routes.health import router as health_router
from meeting_service.utils.logging_config import setup_logging

logger = logging.getLogger(__name__)


@lru_cache
def _get_settings() -> Settings:
    return Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup:
    1. Initialize DB connection pool
    2. Initialize service instances
    3. Start APScheduler for nudges + subscription renewal
    4. Set up calendar subscriptions

    Shutdown:
    1. Stop scheduler
    2. Leave active meetings
    3. Close DB connections
    4. Close HTTP sessions
    """
    settings = _get_settings()
    setup_logging(debug=settings.DEBUG)

    from meeting_service.utils.telemetry import setup_telemetry
    setup_telemetry(app)

    # H1: Warn if auth is expected but AZURE_AD_AUDIENCE is empty (grants Admin to all)
    if settings.REQUIRE_AUTH and not settings.AZURE_AD_AUDIENCE:
        logger.critical(
            "SECURITY: AZURE_AD_AUDIENCE is empty while REQUIRE_AUTH is True. "
            "All requests will bypass JWT validation and receive Admin role. "
            "Set AZURE_AD_AUDIENCE to your App ID URI or client_id, or set "
            "REQUIRE_AUTH=false to acknowledge dev mode."
        )

    # H2: Tech-debt warning — dual auth implementations
    logger.warning(
        "TECH-DEBT: meeting-service uses its own utils/azure_ad_auth.py for JWT "
        "validation. The foundation library provides a more complete implementation "
        "at yoda_foundation.security.auth_dependency (supports RBAC, SecurityContext, "
        "REQUIRE_AUTH flag). Plan to migrate to the foundation auth dependency."
    )

    logger.info("Starting Teams Meeting Assistant")

    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    from meeting_service.services.ai_processor import AIProcessor
    from meeting_service.services.bot_commander import BotCommander
    from meeting_service.services.post_processing import PostProcessingService
    from meeting_service.services.calendar_watcher import CalendarWatcher
    from meeting_service.services.delivery import DeliveryService
    from meeting_service.services.graph_client import GraphClient
    from meeting_service.services.nudge_scheduler import NudgeScheduler
    from meeting_service.services.owner_resolver import OwnerResolver
    from yoda_foundation.utils.auth.token_provider import TokenProvider

    # Initialize services — skip Azure-dependent components when credentials
    # are not configured (local dev without Azure).
    token_provider = None
    if settings.AZURE_TENANT_ID and settings.AZURE_CLIENT_ID and settings.AZURE_CLIENT_SECRET:
        token_provider = TokenProvider(
            tenant_id=settings.AZURE_TENANT_ID,
            client_id=settings.AZURE_CLIENT_ID,
            client_secret=settings.AZURE_CLIENT_SECRET,
        )
    else:
        logger.warning(
            "Azure credentials not configured; Graph/ACS integrations disabled"
        )
    graph_client = GraphClient(token_provider=token_provider)

    scheduler = AsyncIOScheduler()

    # Shared BotCommander — reuses connections across scheduled bot joins
    from meeting_service.services.bot_commander import set_shared_bot_commander

    bot_commander = BotCommander(settings=settings)
    set_shared_bot_commander(bot_commander)

    # Store services on app.state for dependency injection
    app.state.settings = settings
    app.state.token_provider = token_provider
    app.state.graph_client = graph_client
    app.state.scheduler = scheduler
    app.state.bot_commander = bot_commander

    subscription_task: asyncio.Task[None] | None = None

    ai_processor = AIProcessor(settings=settings)
    app.state.ai_processor = ai_processor

    owner_resolver = OwnerResolver(graph_client=graph_client)
    app.state.owner_resolver = owner_resolver

    delivery_service = DeliveryService(
        graph_client=graph_client, settings=settings
    )
    app.state.delivery_service = delivery_service

    # Post-processing pipeline (AI summary, owner resolution, delivery)
    # Pass the session factory so each run() creates its own short-lived session.
    post_processing = PostProcessingService(session_factory=async_session_factory)
    post_processing.ai_processor = ai_processor
    post_processing.owner_resolver = owner_resolver
    post_processing.delivery_service = delivery_service
    app.state.post_processing = post_processing

    calendar_watcher = CalendarWatcher(
        graph_client=graph_client,
        session_factory=async_session_factory,
        scheduler=scheduler,
        settings=settings,
    )
    app.state.calendar_watcher = calendar_watcher

    nudge_scheduler = NudgeScheduler(
        delivery=delivery_service,
        session_factory=async_session_factory,
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

    # Set up calendar subscriptions for opted-in users.
    #
    # This can involve DB + external Graph calls and may hang if the DB isn't
    # reachable in local dev. Run it in the background so the API can still
    # come up (e.g. /health) and we can inspect logs/config.
    async def _setup_calendar_subscriptions() -> None:
        try:
            await asyncio.wait_for(
                calendar_watcher.setup_subscriptions(),
                timeout=30,
            )
            logger.info("Calendar subscriptions initialized")
        except asyncio.TimeoutError:
            logger.warning(
                "Calendar subscription setup timed out; continuing startup"
            )
        except Exception:
            logger.exception("Failed to set up calendar subscriptions")

    subscription_task = asyncio.create_task(
        _setup_calendar_subscriptions()
    )

    yield

    # Shutdown
    scheduler.shutdown(wait=False)
    if subscription_task is not None and not subscription_task.done():
        subscription_task.cancel()
        with suppress(asyncio.CancelledError):
            await subscription_task
    set_shared_bot_commander(None)
    await bot_commander.close()
    await graph_client.close()
    await engine.dispose()
    logger.info("Teams Meeting Assistant shut down")


app = FastAPI(
    title="Teams Meeting Assistant",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS for browser-based frontend
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_settings().CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Correlation-Id"],
)

# Include routers
app.include_router(health_router, tags=["health"])

from meeting_service.routes.action_items import router as action_items_router  # noqa: E402
from meeting_service.routes.meetings import router as meetings_router  # noqa: E402
from meeting_service.routes.webhooks import router as webhooks_router  # noqa: E402

app.include_router(webhooks_router, prefix="/webhooks", tags=["webhooks"])
app.include_router(meetings_router, prefix="/api/meetings", tags=["meetings"])
app.include_router(action_items_router, prefix="/api/action-items", tags=["action-items"])

from meeting_service.routes.admin import router as admin_router  # noqa: E402
from meeting_service.routes.bot_events import router as bot_events_router  # noqa: E402
from meeting_service.routes.sse import router as sse_router  # noqa: E402

app.include_router(admin_router, prefix="/api/admin/users", tags=["admin"])
app.include_router(bot_events_router, prefix="/api/bot-events", tags=["bot-events"])
app.include_router(sse_router, tags=["sse"])
