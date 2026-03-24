"""Pre-meeting brief service -- FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import FastAPI

from pre_meeting_brief_service.config import Settings
from pre_meeting_brief_service.dependencies import async_session_factory, engine
from pre_meeting_brief_service.routes.health import router as health_router
from pre_meeting_brief_service.routes.briefs import router as briefs_router

logger = logging.getLogger(__name__)


@lru_cache
def _get_settings() -> Settings:
    return Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle.

    Startup:
    1. Initialize logging
    2. Optionally initialize Graph client, AI connector, and cache
    3. Store on app.state for route access

    Shutdown:
    1. Close DB connections
    2. Close HTTP sessions
    """
    settings = Settings()
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    logger.info("Starting %s v%s on port %d", settings.APP_NAME, settings.APP_VERSION, settings.PORT)

    app.state.settings = settings

    # Optional: Graph client for user profiles, docs, emails
    graph_client = None
    try:
        from yoda_foundation.utils.auth.token_provider import TokenProvider
        from pre_meeting_brief_service.services.graph_client import GraphClient

        if settings.AZURE_TENANT_ID and settings.AZURE_CLIENT_ID:
            token_provider = TokenProvider(
                tenant_id=settings.AZURE_TENANT_ID,
                client_id=settings.AZURE_CLIENT_ID,
                client_secret=settings.AZURE_CLIENT_SECRET,
            )
            graph_client = GraphClient(token_provider=token_provider)
            app.state.graph_client = graph_client
            logger.info("Graph client initialized")
    except Exception:
        logger.warning("Graph client not available (missing Azure credentials)")

    # Optional: AI connector for question generation
    ai_connector = None
    try:
        if settings.AI_FOUNDRY_ENDPOINT and settings.AI_FOUNDRY_API_KEY:
            from yoda_foundation.data_access.connectors.ai_foundry_connector import AIFoundryConnector
            from yoda_foundation.data_access.base.connector import ConnectorConfig

            connector_config = ConnectorConfig(name="ai-foundry-briefs")
            ai_connector = AIFoundryConnector(
                config=connector_config,
                endpoint=settings.AI_FOUNDRY_ENDPOINT,
                api_key=settings.AI_FOUNDRY_API_KEY,
            )
            app.state.ai_connector = ai_connector
            logger.info("AI connector initialized")
    except Exception:
        logger.warning("AI connector not available")

    # Optional: cache
    cache = None
    try:
        if settings.REDIS_URL:
            from yoda_foundation.utils.caching import RedisCache, CacheConfig

            cache = RedisCache(
                config=CacheConfig(
                    default_ttl_seconds=settings.BRIEF_CACHE_TTL_SECONDS,
                    key_prefix="brief",
                ),
                redis_url=settings.REDIS_URL,
            )
            await cache._client.ping()
            app.state.cache = cache
            logger.info("Redis cache initialized")
    except Exception:
        logger.warning("Redis cache not available, briefs will not be cached")

    app.state.graph_client = graph_client
    app.state.ai_connector = ai_connector
    app.state.cache = cache

    yield

    # Shutdown
    if graph_client and hasattr(graph_client, "close"):
        await graph_client.close()
    await engine.dispose()
    logger.info("%s shut down", settings.APP_NAME)


app = FastAPI(
    title="Pre-Meeting Brief Service",
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
app.include_router(briefs_router, tags=["briefs"])
