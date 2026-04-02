"""Weekly digest service -- FastAPI application entry point with APScheduler."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import FastAPI

from yoda_worker.config import Settings
from yoda_worker.dependencies import async_session_factory, engine
from yoda_worker.routes.health import router as health_router
from yoda_worker.routes.digests import router as digests_router

logger = logging.getLogger(__name__)


@lru_cache
def _get_settings() -> Settings:
    return Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle.

    Startup:
    1. Initialize logging
    2. Optionally initialize AI connector and delivery service
    3. Start APScheduler for weekly auto-generation (Friday afternoons)

    Shutdown:
    1. Stop scheduler
    2. Close DB connections
    """
    settings = Settings()
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    logger.info("Starting %s v%s on port %d", settings.APP_NAME, settings.APP_VERSION, settings.PORT)

    app.state.settings = settings

    # Optional: AI connector for digest text generation
    ai_connector = None
    try:
        if settings.AI_FOUNDRY_ENDPOINT and settings.AI_FOUNDRY_API_KEY:
            from yoda_foundation.data_access.connectors.ai_foundry_connector import AIFoundryConnector
            from yoda_foundation.data_access.base.connector import ConnectorConfig

            connector_config = ConnectorConfig(name="ai-foundry-digest")
            ai_connector = AIFoundryConnector(
                config=connector_config,
                endpoint=settings.AI_FOUNDRY_ENDPOINT,
                api_key=settings.AI_FOUNDRY_API_KEY,
            )
            app.state.ai_connector = ai_connector
            logger.info("AI connector initialized")
    except Exception:
        logger.warning("AI connector not available")

    # Optional: delivery service (requires Graph client)
    delivery_service = None
    try:
        from yoda_foundation.utils.auth.token_provider import TokenProvider

        if settings.AZURE_TENANT_ID and settings.AZURE_CLIENT_ID:
            token_provider = TokenProvider(
                tenant_id=settings.AZURE_TENANT_ID,
                client_id=settings.AZURE_CLIENT_ID,
                client_secret=settings.AZURE_CLIENT_SECRET,
            )
            # Store for potential use by routes
            app.state.token_provider = token_provider
            logger.info("Token provider initialized for delivery")
    except Exception:
        logger.warning("Delivery service not available (missing Azure credentials)")

    app.state.ai_connector = ai_connector
    app.state.delivery_service = delivery_service

    # APScheduler for weekly auto-generation
    scheduler = None
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger
        from yoda_worker.services.weekly_digest_service import WeeklyDigestService

        scheduler = AsyncIOScheduler()
        app.state.scheduler = scheduler

        user_ids = [
            uid.strip()
            for uid in settings.DIGEST_USER_IDS.split(",")
            if uid.strip()
        ]

        if user_ids:
            async def _scheduled_digest_generation():
                """Generate digests for all configured users."""
                svc = WeeklyDigestService(
                    ai_connector=ai_connector,
                    delivery_service=delivery_service,
                    db_session_factory=async_session_factory,
                )
                for uid in user_ids:
                    try:
                        digest = await svc.generate_digest(user_id=uid)
                        logger.info(
                            "Scheduled digest generated for %s (id=%s)", uid, digest.id
                        )
                    except Exception:
                        logger.exception("Failed to generate scheduled digest for %s", uid)

            scheduler.add_job(
                _scheduled_digest_generation,
                CronTrigger(
                    day_of_week=settings.DIGEST_SCHEDULE_DAY,
                    hour=settings.DIGEST_SCHEDULE_HOUR,
                    minute=settings.DIGEST_SCHEDULE_MINUTE,
                ),
                id="weekly_digest_generation",
                replace_existing=True,
            )
            logger.info(
                "Weekly digest scheduled: %s at %02d:%02d UTC for %d user(s)",
                settings.DIGEST_SCHEDULE_DAY,
                settings.DIGEST_SCHEDULE_HOUR,
                settings.DIGEST_SCHEDULE_MINUTE,
                len(user_ids),
            )

        scheduler.start()
        logger.info("APScheduler started")

    except ImportError:
        logger.warning("APScheduler not available; scheduled digest generation disabled")
    except Exception:
        logger.exception("Failed to initialize scheduler")

    yield

    # Shutdown
    if scheduler is not None:
        try:
            scheduler.shutdown(wait=False)
        except Exception:
            pass
    await engine.dispose()
    logger.info("%s shut down", settings.APP_NAME)


app = FastAPI(
    title="YODA Worker",
    version="1.0.0",
    lifespan=lifespan,
    root_path="/yoda-worker",
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
app.include_router(digests_router, tags=["digests"])
