"""Pytest fixtures for the Chat Service test suite.

Provides:
- test_settings: Settings object with test-safe values (SQLite in-memory DB)
- async_session / session_factory: Async SQLAlchemy session using in-memory SQLite
- mock_ai_connector: AsyncMock for AI Foundry completions
- mock_rag_pipeline: AsyncMock for the RAG pipeline
- test_client: httpx.AsyncClient wired to the FastAPI app
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import StaticPool
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# ---------------------------------------------------------------------------
# Settings fixture -- overrides real settings with test-safe values
# ---------------------------------------------------------------------------

_TEST_ENV = {
    "BASE_URL": "https://test.example.com",
    "DATABASE_URL": "sqlite+aiosqlite://",
    "AZURE_TENANT_ID": "test-tenant-id",
    "AZURE_CLIENT_ID": "test-client-id",
    "AZURE_CLIENT_SECRET": "test-client-secret",
    "AI_FOUNDRY_ENDPOINT": "https://test-ai.openai.azure.com/",
    "AI_FOUNDRY_API_KEY": "test-api-key",
    "AI_FOUNDRY_DEPLOYMENT_NAME": "gpt-4o-mini",
    "REDIS_URL": "redis://localhost:6379/0",
    "DEBUG": "false",
    "REQUIRE_AUTH": "false",
}


@pytest.fixture
def test_settings():
    """Return a Settings instance with test values (in-memory SQLite DB)."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from chat_service.config import Settings

        return Settings()


# ---------------------------------------------------------------------------
# Async database session (in-memory SQLite with aiosqlite)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def async_engine():
    """Create an in-memory SQLite async engine with tables."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    from yoda_foundation.models.base import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture
async def async_session(async_engine) -> AsyncGenerator[AsyncSession, None]:
    """Yield an async DB session backed by in-memory SQLite."""
    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def session_factory(async_engine) -> async_sessionmaker[AsyncSession]:
    """Return an async session factory backed by in-memory SQLite."""
    return async_sessionmaker(async_engine, expire_on_commit=False)


# ---------------------------------------------------------------------------
# Mock external services
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_ai_connector() -> AsyncMock:
    """AsyncMock for AI Foundry connector (LLM completions)."""
    connector = AsyncMock()
    connector.complete = AsyncMock(return_value="This is an AI-generated response about meetings.")
    return connector


@pytest.fixture
def mock_rag_pipeline() -> AsyncMock:
    """AsyncMock for the RAG pipeline."""
    pipeline = AsyncMock()

    # Build a mock RAGResult
    mock_source = MagicMock()
    mock_source.title = "Sprint Planning Notes"
    mock_source.url = "https://example.com/doc/1"
    mock_source.document_id = str(uuid.uuid4())
    mock_source.metadata = {"model": "gpt-4o"}

    mock_citation = MagicMock()
    mock_citation.source = mock_source
    mock_citation.text_snippet = "We agreed to prioritize the auth refactor."
    mock_citation.relevance_score = 0.95

    mock_result = MagicMock()
    mock_result.answer = "Based on the meeting notes, the team decided to prioritize the auth refactor."
    mock_result.citations = [mock_citation]
    mock_result.sources = [mock_source]

    pipeline.query = AsyncMock(return_value=mock_result)
    return pipeline


# ---------------------------------------------------------------------------
# FastAPI test client
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def test_client(async_session: AsyncSession):
    """httpx.AsyncClient wired to the FastAPI app with mocked dependencies.

    Overrides:
    - get_db -> yields the test async_session
    - Auth disabled via REQUIRE_AUTH=false
    - Skips the real lifespan (service initialization)
    """
    from httpx import ASGITransport, AsyncClient
    from fastapi import FastAPI

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from chat_service.routes.health import router as health_router
        from chat_service.routes.chat import router as chat_router
        from chat_service.dependencies import get_db

        test_app = FastAPI(title="Test Chat Service")
        test_app.include_router(health_router, tags=["health"])
        test_app.include_router(chat_router, prefix="/api/chat", tags=["chat"])

        # Override the DB dependency to return the test session
        async def override_get_db():
            yield async_session

        test_app.dependency_overrides[get_db] = override_get_db

        transport = ASGITransport(app=test_app)
        async with AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            yield client
