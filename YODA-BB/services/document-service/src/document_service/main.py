"""FastAPI entry point for the Document Service."""

import logging
from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import FastAPI

from document_service.config import Settings
from document_service.dependencies import get_engine, get_session_factory, init_db
from document_service.routes.documents import router as documents_router
from document_service.routes.health import router as health_router
from document_service.utils.logging_config import setup_logging

logger = logging.getLogger(__name__)


@lru_cache
def _get_settings() -> Settings:
    return Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle.

    Startup:
    1. Initialize structured logging
    2. Initialize DB connection pool
    3. Store service instances on app.state

    Shutdown:
    1. Dispose DB engine
    """
    settings = Settings()
    setup_logging(debug=settings.DEBUG)
    logger.info("Starting Document Service")

    # Initialize database
    init_db(settings)

    # Store settings and session factory on app.state for route access
    app.state.settings = settings
    app.state.session_factory = get_session_factory()

    # Initialize Graph connector for SharePoint / OneDrive integration.
    # If Azure credentials are not configured, the connector is set to None
    # and document sync features will be unavailable.
    from yoda_foundation.data_access.connectors.graph_connector import GraphConnector
    from yoda_foundation.data_access.base.connector import ConnectorConfig

    graph_connector = None
    if settings.AZURE_TENANT_ID and settings.AZURE_CLIENT_ID and settings.AZURE_CLIENT_SECRET:
        from yoda_foundation.utils.auth.token_provider import TokenProvider

        token_provider = TokenProvider(
            tenant_id=settings.AZURE_TENANT_ID,
            client_id=settings.AZURE_CLIENT_ID,
            client_secret=settings.AZURE_CLIENT_SECRET,
        )
        graph_config = ConnectorConfig(timeout=30.0, retry_attempts=3)
        graph_connector = GraphConnector(config=graph_config, token_provider=token_provider)
        logger.info("GraphConnector initialized for document sync")
    else:
        logger.warning(
            "Azure credentials not configured; Graph-based document sync disabled"
        )

    # Pre-initialize the document service (lazy singletons will be created on
    # first request for RAG components)
    from document_service.services.document_service import DocumentService

    app.state.document_service = DocumentService(
        graph_connector=graph_connector,
        db_session_factory=get_session_factory(),
        ingestion_pipeline=None,  # Will be lazy-loaded on first use
    )

    logger.info("Document Service started on port %s", settings.PORT)

    yield

    # Shutdown
    engine = get_engine()
    if engine is not None:
        await engine.dispose()
    logger.info("Document Service shut down")


app = FastAPI(
    title="Document Service",
    description="Document management, ingestion, and semantic search",
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
app.include_router(documents_router, prefix="/api/documents", tags=["documents"])
