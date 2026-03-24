"""FastAPI entry point for the dashboard service."""

import logging
from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import FastAPI

from dashboard_service.config import Settings
from dashboard_service.dependencies import engine
from dashboard_service.routes.health import router as health_router
from dashboard_service.routes.dashboard import router as dashboard_router
from dashboard_service.routes.insights import router as insights_router
from dashboard_service.routes.notifications import router as notifications_router
from dashboard_service.routes.search import router as search_router
from dashboard_service.routes.user_settings import router as user_settings_router

logger = logging.getLogger(__name__)


@lru_cache
def _get_settings() -> Settings:
    return Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    settings = Settings()
    logging.basicConfig(
        level=logging.DEBUG if settings.DEBUG else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    logger.info("Starting Dashboard Service on port %s", settings.PORT)
    app.state.settings = settings
    yield
    await engine.dispose()
    logger.info("Dashboard Service shut down")


app = FastAPI(
    title="Dashboard Service",
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
app.include_router(dashboard_router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(insights_router, prefix="/api/insights", tags=["insights"])
app.include_router(notifications_router, prefix="/api/notifications", tags=["notifications"])
app.include_router(search_router, prefix="/api/search", tags=["search"])
app.include_router(user_settings_router, prefix="/api/settings", tags=["settings"])
