"""Enterprise test fixtures for CXO AI Companion.

Provides:
- Async SQLite in-memory database engine and sessions for fast unit tests
- Mock settings with safe placeholder values
- Mock TokenProvider for MSAL authentication
- Mock GraphConnector for Microsoft Graph API calls
- Mock ACS service for Azure Communication Services
- SecurityContext factory for authorization testing
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# ---------------------------------------------------------------------------
# Async Database Engine — in-memory SQLite for unit tests
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def async_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Create an async SQLite in-memory engine for test isolation.

    Each test gets a fresh database with all tables created from the
    SQLAlchemy metadata. The engine is disposed after the test completes.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        future=True,
    )

    # Import Base here to avoid circular imports at module level
    from cxo_ai_companion.models.base import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture()
async def async_session(
    async_engine: AsyncEngine,
) -> AsyncGenerator[AsyncSession, None]:
    """Provide a transactional async session that rolls back after each test.

    This ensures test isolation without needing to recreate tables between
    individual tests within the same engine lifecycle.
    """
    session_factory = async_sessionmaker(
        bind=async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        yield session
        await session.rollback()


# ---------------------------------------------------------------------------
# Test Settings — mock application configuration
# ---------------------------------------------------------------------------


class MockSettings:
    """Mock application settings with safe placeholder values.

    Mirrors the pydantic-settings config class without requiring
    real environment variables.
    """

    APP_NAME: str = "cxo-ai-companion-test"
    APP_ENV: str = "test"
    APP_DEBUG: bool = True
    LOG_LEVEL: str = "DEBUG"
    LOG_FORMAT: str = "text"
    BASE_URL: str = "https://test.example.com"

    DATABASE_URL: str = "sqlite+aiosqlite:///:memory:"
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10

    REDIS_URL: str = "redis://localhost:6379/0"

    AZURE_TENANT_ID: str = "00000000-0000-0000-0000-000000000000"
    AZURE_CLIENT_ID: str = "11111111-1111-1111-1111-111111111111"
    AZURE_CLIENT_SECRET: str = "test-client-secret"  # noqa: S105

    ACS_CONNECTION_STRING: str = "endpoint=https://test.communication.azure.com/;accesskey=dGVzdA=="
    ACS_ENDPOINT: str = "https://test.communication.azure.com"

    AI_FOUNDRY_ENDPOINT: str = "https://test.openai.azure.com/"
    AI_FOUNDRY_API_KEY: str = "test-api-key"  # noqa: S105
    AI_FOUNDRY_DEPLOYMENT_PRIMARY: str = "gpt-4o"
    AI_FOUNDRY_DEPLOYMENT_FAST: str = "gpt-4o-mini"

    GRAPH_API_BASE_URL: str = "https://graph.microsoft.com/v1.0"
    MONITORED_USERS: str = "testuser@contoso.com"

    GRAPH_WEBHOOK_SECRET: str = "test-webhook-secret"  # noqa: S105


@pytest.fixture()
def mock_settings() -> MockSettings:
    """Provide mock settings for tests."""
    return MockSettings()


# ---------------------------------------------------------------------------
# Mock TokenProvider — MSAL daemon flow authentication
# ---------------------------------------------------------------------------


class MockTokenProvider:
    """Mock MSAL token provider that returns a static test token.

    Simulates the daemon (app-only) auth flow without contacting Azure AD.
    """

    def __init__(self) -> None:
        self._token = "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.test-token"

    async def get_token(self, scopes: list[str] | None = None) -> str:
        """Return a static test token."""
        return self._token

    async def get_graph_token(self) -> str:
        """Return a static test token for Graph API calls."""
        return self._token


@pytest.fixture()
def mock_token_provider() -> MockTokenProvider:
    """Provide a mock token provider."""
    return MockTokenProvider()


# ---------------------------------------------------------------------------
# Mock GraphConnector — Microsoft Graph API client
# ---------------------------------------------------------------------------


class MockGraphConnector:
    """Mock Graph API connector for testing calendar and user operations.

    All methods are AsyncMock instances that return reasonable defaults.
    Override return_value or side_effect in individual tests as needed.
    """

    def __init__(self) -> None:
        self.get_calendar_events = AsyncMock(return_value=[])
        self.get_user_profile = AsyncMock(
            return_value={
                "id": str(uuid.uuid4()),
                "displayName": "Test User",
                "mail": "testuser@contoso.com",
                "jobTitle": "Chief Test Officer",
            }
        )
        self.create_subscription = AsyncMock(
            return_value={
                "id": str(uuid.uuid4()),
                "resource": "me/events",
                "expirationDateTime": "2099-01-01T00:00:00Z",
            }
        )
        self.renew_subscription = AsyncMock(return_value=True)
        self.send_chat_message = AsyncMock(return_value={"id": str(uuid.uuid4())})
        self.get_meeting_transcript = AsyncMock(return_value="")
        self.get_online_meeting = AsyncMock(return_value={})


@pytest.fixture()
def mock_graph_connector() -> MockGraphConnector:
    """Provide a mock Graph API connector."""
    return MockGraphConnector()


# ---------------------------------------------------------------------------
# Mock ACS Service — Azure Communication Services
# ---------------------------------------------------------------------------


class MockACSService:
    """Mock ACS Call Automation service for testing bot join/leave operations.

    All methods are AsyncMock instances returning sensible defaults.
    """

    def __init__(self) -> None:
        self.join_call = AsyncMock(
            return_value={
                "call_connection_id": str(uuid.uuid4()),
                "status": "connected",
            }
        )
        self.leave_call = AsyncMock(return_value=True)
        self.start_recording = AsyncMock(
            return_value={"recording_id": str(uuid.uuid4())}
        )
        self.stop_recording = AsyncMock(return_value=True)
        self.get_recording_status = AsyncMock(return_value="active")


@pytest.fixture()
def mock_acs_service() -> MockACSService:
    """Provide a mock ACS service."""
    return MockACSService()


# ---------------------------------------------------------------------------
# Mock AI Service — Azure AI Foundry
# ---------------------------------------------------------------------------


class MockAIService:
    """Mock AI Foundry service for testing LLM-based summarization and analysis."""

    def __init__(self) -> None:
        self.summarize_transcript = AsyncMock(
            return_value={
                "executive_summary": "Test executive summary.",
                "summary": "Test detailed summary of the meeting.",
                "key_topics": ["Topic A", "Topic B"],
                "action_items": [],
                "decisions": [],
                "unresolved_questions": [],
                "sentiment": "neutral",
            }
        )
        self.extract_action_items = AsyncMock(return_value=[])
        self.detect_conflicts = AsyncMock(return_value=[])
        self.generate_pre_meeting_brief = AsyncMock(
            return_value={
                "suggested_questions": ["What is the status of Project X?"],
                "context_summary": "Last meeting covered budget review.",
            }
        )


@pytest.fixture()
def mock_ai_service() -> MockAIService:
    """Provide a mock AI service."""
    return MockAIService()


# ---------------------------------------------------------------------------
# SecurityContext Factory — authorization context for tests
# ---------------------------------------------------------------------------


class SecurityContext:
    """Represents the security/authorization context for a request.

    In production, this is populated from the validated JWT or
    daemon credentials. In tests, use the factory fixture.
    """

    def __init__(
        self,
        user_id: str,
        tenant_id: str,
        display_name: str = "Test User",
        email: str = "testuser@contoso.com",
        roles: list[str] | None = None,
    ) -> None:
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.display_name = display_name
        self.email = email
        self.roles = roles or ["CXO.Read", "CXO.ReadWrite"]
        self.authenticated_at = datetime.now(timezone.utc)

    @property
    def is_admin(self) -> bool:
        return "CXO.Admin" in self.roles


@pytest.fixture()
def security_context_factory():
    """Factory fixture to create SecurityContext instances with custom attributes.

    Usage in tests:
        def test_something(security_context_factory):
            ctx = security_context_factory(roles=["CXO.Admin"])
            assert ctx.is_admin
    """

    def _factory(
        user_id: str | None = None,
        tenant_id: str | None = None,
        display_name: str = "Test CXO",
        email: str = "cxo@contoso.com",
        roles: list[str] | None = None,
    ) -> SecurityContext:
        return SecurityContext(
            user_id=user_id or str(uuid.uuid4()),
            tenant_id=tenant_id or "00000000-0000-0000-0000-000000000000",
            display_name=display_name,
            email=email,
            roles=roles,
        )

    return _factory


@pytest.fixture()
def default_security_context(security_context_factory: Any) -> SecurityContext:
    """Provide a default SecurityContext for simple test cases."""
    return security_context_factory()
