"""Shared fixtures for document-service tests."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytest_plugins = []


# ---------------------------------------------------------------------------
# Fake Document for tests (avoids needing real ORM + pgvector)
# ---------------------------------------------------------------------------
class FakeDocument:
    """Minimal stand-in for Document ORM model."""

    def __init__(self, **kwargs: Any) -> None:
        self.id = kwargs.get("id", uuid.uuid4())
        self.meeting_id = kwargs.get("meeting_id")
        self.title = kwargs.get("title", "Test Doc")
        self.source = kwargs.get("source", "upload")
        self.source_url = kwargs.get("source_url")
        self.content_type = kwargs.get("content_type", "application/pdf")
        self.content_hash = kwargs.get("content_hash")
        self.extracted_text = kwargs.get("extracted_text")
        self.embedding_id = kwargs.get("embedding_id")
        self.status = kwargs.get("status", "pending")
        self.uploaded_by = kwargs.get("uploaded_by", "user-1")
        self.file_size_bytes = kwargs.get("file_size_bytes", 1024)
        self.review_status = kwargs.get("review_status", "none")
        # Wireframe-driven fields
        self.folder_path = kwargs.get("folder_path")
        self.page_count = kwargs.get("page_count")
        self.shared_by = kwargs.get("shared_by")
        self.shared_at = kwargs.get("shared_at")
        self.priority = kwargs.get("priority")
        self.last_modified_by = kwargs.get("last_modified_by")
        self.graph_item_id = kwargs.get("graph_item_id")
        # Classification fields
        self.category = kwargs.get("category")
        self.classification_confidence = kwargs.get("classification_confidence")
        self.suggested_tags = kwargs.get("suggested_tags")
        # Timestamps
        self.created_at = kwargs.get("created_at", datetime.now(timezone.utc))
        self.updated_at = kwargs.get("updated_at", datetime.now(timezone.utc))


@pytest.fixture
def fake_document() -> FakeDocument:
    """Return a single FakeDocument instance."""
    return FakeDocument(
        id=uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
        title="Quarterly Report.pdf",
        source="upload",
        content_type="application/pdf",
        status="processed",
    )


@pytest.fixture
def fake_documents() -> list[FakeDocument]:
    """Return a list of FakeDocument instances."""
    return [
        FakeDocument(title="Doc A", status="processed"),
        FakeDocument(title="Doc B", status="pending"),
    ]


# ---------------------------------------------------------------------------
# Mock DB session
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_db_session() -> AsyncMock:
    """Return a mocked AsyncSession."""
    session = AsyncMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    return session


# ---------------------------------------------------------------------------
# Mock DocumentService for route tests
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_document_service() -> AsyncMock:
    """Return a mocked DocumentService with all methods as AsyncMock."""
    service = AsyncMock()
    service.sync_from_graph = AsyncMock(return_value=[])
    service.get_shared_with_me = AsyncMock(return_value=[])
    service.get_needs_review = AsyncMock(return_value=[])
    service.get_meeting_documents_for_today = AsyncMock(return_value=[])
    service.get_recently_updated = AsyncMock(return_value=[])
    service.index_emails = AsyncMock(return_value=[])
    return service


# ---------------------------------------------------------------------------
# FastAPI test client with mocked dependencies
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def client(
    mock_db_session: AsyncMock,
    mock_document_service: AsyncMock,
) -> AsyncGenerator[AsyncClient, None]:
    """Create an HTTPX async test client with mocked DB, auth, and service."""
    from document_service.main import app
    from document_service.dependencies import get_db, get_document_service

    # Mock get_db to yield our mock session
    async def _mock_get_db():
        yield mock_db_session

    app.dependency_overrides[get_db] = _mock_get_db

    # Mock get_document_service to return our mock
    def _mock_get_document_service(request=None):
        return mock_document_service

    app.dependency_overrides[get_document_service] = _mock_get_document_service

    # Mock auth to return a fake SecurityContext
    from yoda_foundation.security.auth_dependency import get_current_user

    mock_ctx = MagicMock()
    mock_ctx.user_id = "test-user-id"
    mock_ctx.tenant_id = "test-tenant"

    async def _mock_auth():
        return mock_ctx

    app.dependency_overrides[get_current_user] = _mock_auth

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
