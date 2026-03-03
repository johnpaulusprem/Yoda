"""CXO AI Companion — FastAPI application entry point."""
from __future__ import annotations
import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from cxo_ai_companion.config import Settings
from cxo_ai_companion.dependencies import init_db, get_settings, _async_session_factory
from cxo_ai_companion.observability.logging import configure_logging
from cxo_ai_companion.api.rest.middleware import ErrorHandlerMiddleware, RequestLoggingMiddleware, CorrelationIdMiddleware
from cxo_ai_companion.api.rest.routes import (
    health_router, meetings_router, action_items_router, dashboard_router,
    chat_router, documents_router, insights_router, webhooks_router, acs_callbacks_router,
    notifications_router, search_router, projects_router,
)
from cxo_ai_companion.api.websocket.transcription import handle_transcription_ws

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    configure_logging(level=settings.LOG_LEVEL, json_format=settings.LOG_JSON, service_name=settings.OTEL_SERVICE_NAME)
    logger.info("Starting %s v%s", settings.APP_NAME, settings.APP_VERSION)
    init_db(settings)
    logger.info("Database engine initialized")
    # Service wiring happens here in production:
    # app.state.acs_service = ACSCallService(...)
    # app.state.calendar_watcher = CalendarWatcher(...)
    # app.state.nudge_scheduler = NudgeScheduler(...)
    yield
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
        await handle_transcription_ws(websocket, meeting_id, _async_session_factory)

    return app

app = create_app()
