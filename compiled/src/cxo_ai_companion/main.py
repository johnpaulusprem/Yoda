"""CXO AI Companion — FastAPI application entry point."""
from __future__ import annotations
import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from uuid import UUID as UUID_type
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from cxo_ai_companion.config import Settings
from cxo_ai_companion.dependencies import init_db, init_cache, get_settings, get_cache, get_llm_adapter, get_session_factory
from cxo_ai_companion.observability.logging import configure_logging
from cxo_ai_companion.api.rest.middleware import ErrorHandlerMiddleware, RequestLoggingMiddleware, CorrelationIdMiddleware, SecurityHeadersMiddleware, RateLimiterMiddleware
from cxo_ai_companion.api.rest.routes import (
    health_router, meetings_router, action_items_router, dashboard_router,
    chat_router, documents_router, insights_router, webhooks_router, acs_callbacks_router,
    notifications_router, search_router, projects_router,
)
from cxo_ai_companion.services.transcription import TranscriptionHandler

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    configure_logging(level=settings.LOG_LEVEL, json_format=settings.LOG_JSON, service_name=settings.OTEL_SERVICE_NAME)
    logger.info("Starting %s v%s", settings.APP_NAME, settings.APP_VERSION)

    # ------------------------------------------------------------------
    # Startup validation
    # ------------------------------------------------------------------
    if not settings.ACS_CONNECTION_STRING:
        logger.warning("ACS_CONNECTION_STRING not set — ACS call service will not be available")
    if not settings.AZURE_TENANT_ID or not settings.AZURE_CLIENT_ID:
        logger.warning("Azure credentials not fully configured — Graph API features will be limited")
    if not settings.DEBUG and not settings.BASE_URL.startswith("https://"):
        logger.warning("BASE_URL should use HTTPS in production (current: %s)", settings.BASE_URL)

    init_db(settings)
    logger.info("Database engine initialized")
    await init_cache(settings)
    logger.info("Cache initialized")
    # ------------------------------------------------------------------
    # Service wiring — builds the full meeting pipeline
    # ------------------------------------------------------------------
    graph_client = None
    scheduler = None

    try:
        from cxo_ai_companion.utilities.auth.token_provider import TokenProvider
        from cxo_ai_companion.services.graph_client import GraphClient

        token_provider = TokenProvider(
            tenant_id=settings.AZURE_TENANT_ID,
            client_id=settings.AZURE_CLIENT_ID,
            client_secret=settings.AZURE_CLIENT_SECRET,
        )
        graph_client = GraphClient(token_provider)
        logger.info("Graph client initialized")
    except Exception:
        logger.warning("Graph client not available (missing Azure credentials?)")

    # AI Processor for post-meeting summarization
    ai_processor = None
    try:
        from cxo_ai_companion.services.ai_processor import AIProcessor

        ai_processor = AIProcessor(settings, dspy_adapter=get_llm_adapter() if settings.DSPY_CACHE_ENABLED else None)
        logger.info("AI Processor initialized")
    except Exception:
        logger.warning("AI Processor not available (missing AI Foundry credentials?)")

    # Delivery service for sending summaries to Teams
    delivery_service = None
    if graph_client:
        from cxo_ai_companion.services.delivery import DeliveryService

        delivery_service = DeliveryService(graph_client=graph_client, settings=settings)
        app.state.delivery_service = delivery_service
        logger.info("Delivery service initialized")

    # Owner resolver for action item assignment
    owner_resolver = None
    if graph_client:
        from cxo_ai_companion.services.owner_resolver import OwnerResolver

        owner_resolver = OwnerResolver(graph_client=graph_client)
        logger.info("Owner resolver initialized")

    # ACS Call Automation service — uses session_factory (no session lifecycle issues)
    if settings.ACS_CONNECTION_STRING:
        from cxo_ai_companion.services.acs_call_service import ACSCallService

        acs_service = ACSCallService(settings, get_session_factory())
        acs_service.ai_processor = ai_processor
        acs_service.delivery_service = delivery_service
        acs_service.owner_resolver = owner_resolver
        app.state.acs_service = acs_service
        logger.info(
            "ACS service initialized (ai=%s, delivery=%s, owner=%s)",
            ai_processor is not None,
            delivery_service is not None,
            owner_resolver is not None,
        )

    # APScheduler + Calendar Watcher + Nudge Scheduler
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.interval import IntervalTrigger
        from cxo_ai_companion.services.calendar_watcher import CalendarWatcher

        scheduler = AsyncIOScheduler()
        scheduler.start()
        app.state.scheduler = scheduler

        if graph_client:
            calendar_watcher = CalendarWatcher(
                graph_client=graph_client,
                session_factory=get_session_factory(),
                scheduler=scheduler,
                settings=settings,
            )
            app.state.calendar_watcher = calendar_watcher

            # Initialize subscriptions on startup
            try:
                await calendar_watcher.setup_subscriptions()
                logger.info("Graph calendar subscriptions initialized")
            except Exception:
                logger.exception("Failed to setup Graph subscriptions (will retry on renewal)")

            # Schedule subscription renewal every 12 hours
            async def _renew_subscriptions_job():
                watcher = CalendarWatcher(
                    graph_client=graph_client,
                    session_factory=get_session_factory(),
                    scheduler=scheduler,
                    settings=settings,
                )
                await watcher.renew_subscriptions()

            scheduler.add_job(
                _renew_subscriptions_job,
                IntervalTrigger(hours=12),
                id="renew_graph_subscriptions",
                replace_existing=True,
            )
            logger.info("Subscription renewal job scheduled (every 12h)")

        # Nudge scheduler for action item follow-ups
        if delivery_service:
            from cxo_ai_companion.services.nudge_scheduler import NudgeScheduler

            async def _nudge_scheduler_job():
                async with get_session_factory()() as db:
                    nudge_svc = NudgeScheduler(
                        delivery=delivery_service,
                        db=db,
                        settings=settings,
                    )
                    await nudge_svc.run()

            scheduler.add_job(
                _nudge_scheduler_job,
                IntervalTrigger(minutes=settings.NUDGE_CHECK_INTERVAL_MINUTES),
                id="nudge_scheduler",
                replace_existing=True,
            )
            logger.info("Nudge scheduler job scheduled (every %dm)", settings.NUDGE_CHECK_INTERVAL_MINUTES)

    except ImportError:
        logger.warning("APScheduler not available; calendar watcher and nudge scheduler disabled")
    except Exception:
        logger.exception("Failed to initialize scheduler services")

    yield

    # Shutdown scheduler if running
    if scheduler is not None:
        try:
            scheduler.shutdown(wait=False)
        except Exception:
            pass
    try:
        cache = get_cache()
        await cache.close()
    except Exception:
        pass
    logger.info("Shutting down %s", settings.APP_NAME)

def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.APP_NAME, version=settings.APP_VERSION,
        lifespan=lifespan, docs_url="/docs" if settings.DEBUG else None,
    )

    # Middleware (order matters: outermost first)
    app.add_middleware(ErrorHandlerMiddleware)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RateLimiterMiddleware, rpm=settings.RATE_LIMIT_RPM, burst=settings.RATE_LIMIT_BURST)
    app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ALLOWED_ORIGINS, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

    # Routes
    app.include_router(health_router, tags=["Health"])
    app.include_router(meetings_router, prefix="/api/meetings", tags=["Meetings"])
    app.include_router(action_items_router, prefix="/api/action-items", tags=["Action Items"])
    app.include_router(dashboard_router, prefix="/api/dashboard", tags=["Dashboard"])
    app.include_router(chat_router, prefix="/api/chat", tags=["Chat"])
    app.include_router(documents_router, prefix="/api/documents", tags=["Documents"])
    app.include_router(insights_router, prefix="/api/insights", tags=["Insights"])
    app.include_router(webhooks_router, prefix="/api/webhooks", tags=["Webhooks"])
    app.include_router(acs_callbacks_router, prefix="/api/callbacks", tags=["Callbacks"])
    app.include_router(notifications_router, prefix="/api/notifications", tags=["Notifications"])
    app.include_router(search_router, prefix="/api/search", tags=["Search"])
    app.include_router(projects_router, prefix="/api/projects", tags=["Projects"])

    @app.websocket("/ws/transcription/{meeting_id}")
    async def transcription_ws(websocket: WebSocket, meeting_id: str):
        """WebSocket endpoint for ACS real-time transcription.

        ACS connects to this URL (configured in transcriptionOptions.transportUrl
        when joining the meeting). Per ACS documentation, WebSocket connections
        from ACS are unauthenticated — ACS does not send JWT tokens on WebSocket
        connections. Security relies on:
        - Meeting UUID not being guessable
        - Meeting must exist and be in active state
        - WSS transport (enforced by ACS in production)
        """
        # Validate meeting_id is UUID
        try:
            meeting_uuid = UUID_type(meeting_id)
        except ValueError:
            await websocket.close(code=1008, reason="Invalid meeting_id")
            return

        # Validate meeting exists and is active
        # (ACS connects to URLs we configure — only active meetings should have
        # WebSocket URLs registered with ACS)
        async with get_session_factory()() as db:
            from cxo_ai_companion.models.meeting import Meeting
            stmt = select(Meeting.status).where(Meeting.id == meeting_uuid)
            result = await db.execute(stmt)
            row = result.one_or_none()
            if row is None or row.status not in ("scheduled", "in_progress"):
                await websocket.close(code=1008, reason="Meeting not active")
                return

        async with get_session_factory()() as db:
            handler = TranscriptionHandler(db=db)
            await handler.handle_connection(websocket, meeting_id)

    @app.websocket("/ws/audio/{meeting_id}")
    async def audio_ws(websocket: WebSocket, meeting_id: str):
        """WebSocket endpoint for ACS media streaming (audio).

        ACS pushes unmixed audio frames here. Currently accepts and
        discards the stream — a future iteration can pipe it to a
        custom speech model or real-time analysis.

        Same auth model as transcription WS: meeting-context validation
        (ACS WebSockets are unauthenticated by design per ACS docs).
        """
        try:
            meeting_uuid = UUID_type(meeting_id)
        except ValueError:
            await websocket.close(code=1008, reason="Invalid meeting_id")
            return

        # Validate meeting exists and is active
        async with get_session_factory()() as db:
            from cxo_ai_companion.models.meeting import Meeting
            stmt = select(Meeting.status).where(Meeting.id == meeting_uuid)
            result = await db.execute(stmt)
            row = result.one_or_none()
            if row is None or row.status not in ("scheduled", "in_progress"):
                await websocket.close(code=1008, reason="Meeting not active")
                return

        await websocket.accept()
        logger.info("Audio WS connected for meeting %s", meeting_id)
        try:
            while True:
                await websocket.receive_bytes()
        except WebSocketDisconnect:
            logger.info("Audio WS disconnected for meeting %s", meeting_id)
        except Exception:
            logger.debug("Audio WS error for meeting %s", meeting_id)

    return app

app = create_app()
