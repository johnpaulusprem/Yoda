import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket

from app.config import Settings
from app.dependencies import async_session_factory, engine
from app.routes.health import router as health_router
from app.utils.logging_config import setup_logging

logger = logging.getLogger(__name__)


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
    settings = Settings()
    setup_logging(debug=settings.DEBUG)
    logger.info("Starting Teams Meeting Assistant")

    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    from app.services.acs_call_service import ACSCallService
    from app.services.ai_processor import AIProcessor
    from app.services.bot_commander import BotCommander
    from app.services.calendar_watcher import CalendarWatcher
    from app.services.delivery import DeliveryService
    from app.services.graph_client import GraphClient
    from app.services.nudge_scheduler import NudgeScheduler
    from app.services.owner_resolver import OwnerResolver
    from app.utils.auth import TokenProvider

    # Initialize services
    token_provider = TokenProvider(
        tenant_id=settings.AZURE_TENANT_ID,
        client_id=settings.AZURE_CLIENT_ID,
        client_secret=settings.AZURE_CLIENT_SECRET,
    )
    graph_client = GraphClient(token_provider=token_provider)

    scheduler = AsyncIOScheduler()

    # Shared BotCommander — reuses connections across scheduled bot joins
    from app.services.bot_commander import set_shared_bot_commander

    bot_commander = BotCommander(settings=settings)
    set_shared_bot_commander(bot_commander)

    # Store services on app.state for dependency injection
    app.state.settings = settings
    app.state.token_provider = token_provider
    app.state.graph_client = graph_client
    app.state.scheduler = scheduler
    app.state.bot_commander = bot_commander

    async with async_session_factory() as db:
        acs_service = ACSCallService(settings=settings, db=db)
        app.state.acs_service = acs_service

        ai_processor = AIProcessor(settings=settings)
        app.state.ai_processor = ai_processor

        owner_resolver = OwnerResolver(graph_client=graph_client)
        app.state.owner_resolver = owner_resolver

        delivery_service = DeliveryService(
            graph_client=graph_client, settings=settings
        )
        app.state.delivery_service = delivery_service

        # Wire downstream services into ACS service for post-meeting pipeline
        acs_service.ai_processor = ai_processor
        acs_service.owner_resolver = owner_resolver
        acs_service.delivery_service = delivery_service

        calendar_watcher = CalendarWatcher(
            graph_client=graph_client,
            db=db,
            scheduler=scheduler,
            settings=settings,
        )
        app.state.calendar_watcher = calendar_watcher

        nudge_scheduler = NudgeScheduler(
            delivery=delivery_service, db=db, settings=settings
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

        # Set up calendar subscriptions for opted-in users
        try:
            await calendar_watcher.setup_subscriptions()
            logger.info("Calendar subscriptions initialized")
        except Exception:
            logger.exception("Failed to set up calendar subscriptions")

        yield

        # Shutdown
        scheduler.shutdown(wait=False)
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

# Include routers
app.include_router(health_router, tags=["health"])

from app.routes.acs_callbacks import router as acs_callbacks_router  # noqa: E402
from app.routes.action_items import router as action_items_router  # noqa: E402
from app.routes.meetings import router as meetings_router  # noqa: E402
from app.routes.webhooks import router as webhooks_router  # noqa: E402

app.include_router(webhooks_router, prefix="/webhooks", tags=["webhooks"])
app.include_router(acs_callbacks_router, prefix="/callbacks", tags=["acs"])
app.include_router(meetings_router, prefix="/api/meetings", tags=["meetings"])
app.include_router(action_items_router, prefix="/api/action-items", tags=["action-items"])

from app.routes.bot_events import router as bot_events_router  # noqa: E402

app.include_router(bot_events_router, prefix="/api/bot-events", tags=["bot-events"])


@app.websocket("/ws/transcription/{meeting_id}")
async def transcription_ws(websocket: WebSocket, meeting_id: str):
    """WebSocket endpoint that ACS connects to for streaming transcription data."""
    from app.dependencies import get_db
    from app.services.transcription import TranscriptionHandler

    await websocket.accept()
    async for db in get_db():
        handler = TranscriptionHandler(db=db)
        await handler.handle_connection(websocket, meeting_id)
