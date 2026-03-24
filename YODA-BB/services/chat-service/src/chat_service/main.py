"""Chat Service -- FastAPI application entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from functools import lru_cache

from fastapi import FastAPI

from chat_service.config import Settings
from chat_service.dependencies import init_db, init_cache, get_settings, get_cache
from chat_service.routes.health import router as health_router
from chat_service.routes.chat import router as chat_router

logger = logging.getLogger(__name__)


@lru_cache
def _get_cached_settings() -> Settings:
    return Settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup / shutdown lifecycle for the chat service."""
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.info("Starting %s v%s", settings.APP_NAME, settings.APP_VERSION)

    # Database
    init_db(settings)
    logger.info("Database engine initialized")

    # Cache (Redis with MemoryCache fallback)
    await init_cache(settings)
    logger.info("Cache initialized")

    yield

    # Shutdown
    try:
        cache = get_cache()
        await cache.close()
    except Exception:
        pass
    logger.info("Shutting down %s", settings.APP_NAME)


app = FastAPI(
    title="Chat Service",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS for browser-based frontend
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_cached_settings().CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Correlation-Id"],
)

# Include routers
app.include_router(health_router, tags=["health"])
app.include_router(chat_router, prefix="/api/chat", tags=["chat"])
