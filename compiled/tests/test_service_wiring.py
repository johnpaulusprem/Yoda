"""Tests for service wiring and pipeline connectivity.

Covers:
- Webhook method name correctness (handle_webhook, not handle_notification)
- Webhook URL correctness in CalendarWatcher (/api/webhooks/graph)
- ACS callback URL matches route (/api/callbacks/acs/events)
- NUDGE_ESCALATION_THRESHOLD exists in Settings
- DeliveryService requires graph_client
- Post-processing pipeline has all services wired
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


@pytest_asyncio.fixture()
async def async_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    from cxo_ai_companion.models.base import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture()
async def session_factory(async_engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture()
async def async_session(session_factory) -> AsyncSession:
    async with session_factory() as session:
        yield session
        await session.rollback()


# ---------------------------------------------------------------------------
# Webhook method name
# ---------------------------------------------------------------------------


class TestWebhookMethodName:
    def test_webhook_route_calls_handle_webhook(self):
        """webhooks.py must call handle_webhook, not handle_notification."""
        import inspect
        from cxo_ai_companion.api.rest.routes import webhooks

        # handle_webhook is called in _process_notification (background task)
        module_source = inspect.getsource(webhooks)
        assert "handle_webhook" in module_source
        assert "handle_notification" not in module_source
        # graph_webhook dispatches via BackgroundTasks for 3-second timeout compliance
        route_source = inspect.getsource(webhooks.graph_webhook)
        assert "background_tasks" in route_source

    def test_calendar_watcher_has_handle_webhook(self):
        """CalendarWatcher must have handle_webhook method."""
        from cxo_ai_companion.services.calendar_watcher import CalendarWatcher

        assert hasattr(CalendarWatcher, "handle_webhook")
        assert callable(getattr(CalendarWatcher, "handle_webhook"))


# ---------------------------------------------------------------------------
# Webhook URL correctness
# ---------------------------------------------------------------------------


class TestWebhookURLs:
    def test_calendar_watcher_uses_api_prefix_for_webhook_url(self):
        """CalendarWatcher subscription URL must include /api/ prefix."""
        import inspect
        from cxo_ai_companion.services.calendar_watcher import CalendarWatcher

        source = inspect.getsource(CalendarWatcher.setup_subscriptions)
        assert "/api/webhooks/graph" in source

    def test_calendar_watcher_renewal_uses_api_prefix(self):
        """CalendarWatcher renewal URL must include /api/ prefix."""
        import inspect
        from cxo_ai_companion.services.calendar_watcher import CalendarWatcher

        source = inspect.getsource(CalendarWatcher.renew_subscriptions)
        assert "/api/webhooks/graph" in source

    def test_acs_callback_url_uses_full_path(self):
        """ACS callback URL must be /api/callbacks/acs/events."""
        import inspect
        from cxo_ai_companion.services.acs_call_service import ACSCallService

        source = inspect.getsource(ACSCallService.join_meeting)
        assert "/api/callbacks/acs/events" in source


# ---------------------------------------------------------------------------
# Settings completeness
# ---------------------------------------------------------------------------


class TestSettings:
    def test_nudge_escalation_threshold_exists(self):
        """NUDGE_ESCALATION_THRESHOLD must be in Settings."""
        from cxo_ai_companion.config.settings import Settings

        s = Settings(
            DATABASE_URL="sqlite:///:memory:",
            AZURE_TENANT_ID="test",
            AZURE_CLIENT_ID="test",
            AZURE_CLIENT_SECRET="test",
        )
        assert hasattr(s, "NUDGE_ESCALATION_THRESHOLD")
        assert isinstance(s.NUDGE_ESCALATION_THRESHOLD, int)
        assert s.NUDGE_ESCALATION_THRESHOLD > 0


# ---------------------------------------------------------------------------
# DeliveryService wiring
# ---------------------------------------------------------------------------


class TestDeliveryService:
    def test_delivery_service_requires_graph_client(self):
        """DeliveryService must accept a graph_client."""
        from cxo_ai_companion.services.delivery import DeliveryService

        mock_graph = MagicMock()
        mock_settings = MagicMock()
        service = DeliveryService(graph_client=mock_graph, settings=mock_settings)
        assert service.graph is mock_graph

    @pytest.mark.asyncio
    async def test_deliver_summary_calls_graph_send(self):
        """deliver_summary must call graph.send_chat_message."""
        from cxo_ai_companion.services.delivery import DeliveryService

        mock_graph = MagicMock()
        mock_graph.send_chat_message = AsyncMock()
        mock_settings = MagicMock()
        mock_settings.BASE_URL = "https://test.example.com"
        service = DeliveryService(graph_client=mock_graph, settings=mock_settings)

        meeting = MagicMock()
        meeting.id = uuid.uuid4()
        meeting.subject = "Test Meeting"
        meeting.thread_id = "thread-123"
        meeting.scheduled_start = datetime.now(timezone.utc)
        meeting.scheduled_end = datetime.now(timezone.utc) + timedelta(hours=1)
        meeting.actual_start = datetime.now(timezone.utc)
        meeting.actual_end = datetime.now(timezone.utc) + timedelta(minutes=45)
        meeting.participant_count = 5

        summary = MagicMock()
        summary.summary_text = "Test summary"
        summary.decisions = []
        summary.key_topics = []
        summary.unresolved_questions = []
        summary.model_used = "gpt-4o-mini"
        summary.delivered = False
        summary.delivered_at = None

        await service.deliver_summary(meeting, summary, [])
        mock_graph.send_chat_message.assert_called_once()


# ---------------------------------------------------------------------------
# Post-processing wiring
# ---------------------------------------------------------------------------


class TestPostProcessingWiring:
    @pytest.mark.asyncio
    async def test_acs_service_accepts_downstream_services(self, session_factory):
        """ACSCallService must accept ai_processor, delivery_service, owner_resolver."""
        from cxo_ai_companion.services.acs_call_service import ACSCallService

        class MockSettings:
            ACS_CONNECTION_STRING = "endpoint=https://test.communication.azure.com/;accesskey=dGVzdA=="
            BASE_URL = "https://test.example.com"

        service = ACSCallService(MockSettings(), session_factory)

        mock_ai = MagicMock()
        mock_delivery = MagicMock()
        mock_owner = MagicMock()

        service.ai_processor = mock_ai
        service.delivery_service = mock_delivery
        service.owner_resolver = mock_owner

        assert service.ai_processor is mock_ai
        assert service.delivery_service is mock_delivery
        assert service.owner_resolver is mock_owner


# ---------------------------------------------------------------------------
# NudgeScheduler
# ---------------------------------------------------------------------------


class TestNudgeScheduler:
    @pytest.mark.asyncio
    async def test_nudge_scheduler_run_with_no_items(self, async_session):
        """NudgeScheduler.run() should complete cleanly with no eligible items."""
        from cxo_ai_companion.services.nudge_scheduler import NudgeScheduler

        mock_delivery = MagicMock()
        mock_settings = MagicMock()
        mock_settings.NUDGE_ESCALATION_THRESHOLD = 3

        scheduler = NudgeScheduler(
            delivery=mock_delivery,
            db=async_session,
            settings=mock_settings,
        )

        # Should not raise
        await scheduler.run()

    def test_nudge_scheduler_requires_delivery_service(self):
        """NudgeScheduler must accept a DeliveryService."""
        from cxo_ai_companion.services.nudge_scheduler import NudgeScheduler

        mock_delivery = MagicMock()
        mock_db = MagicMock()
        mock_settings = MagicMock()

        scheduler = NudgeScheduler(delivery=mock_delivery, db=mock_db, settings=mock_settings)
        assert scheduler.delivery is mock_delivery


# ---------------------------------------------------------------------------
# Lifespan wiring (structural checks)
# ---------------------------------------------------------------------------


class TestLifespanWiring:
    def test_lifespan_imports_all_services(self):
        """main.py lifespan must import and wire all critical services."""
        import inspect
        from cxo_ai_companion.main import lifespan

        source = inspect.getsource(lifespan)

        # TokenProvider → GraphClient
        assert "TokenProvider" in source
        assert "GraphClient" in source

        # AI Processor
        assert "AIProcessor" in source

        # Delivery
        assert "DeliveryService" in source

        # Owner resolver
        assert "OwnerResolver" in source

        # ACS service wiring
        assert "acs_service.ai_processor" in source
        assert "acs_service.delivery_service" in source
        assert "acs_service.owner_resolver" in source

        # Subscription initialization
        assert "setup_subscriptions" in source

        # Subscription renewal scheduling
        assert "renew_subscriptions" in source

        # Nudge scheduler
        assert "NudgeScheduler" in source
        assert "nudge_scheduler" in source

    def test_lifespan_uses_session_factory_not_session(self):
        """main.py should pass session_factory to services, not bare sessions."""
        import inspect
        from cxo_ai_companion.main import lifespan

        source = inspect.getsource(lifespan)

        # ACS service should use get_session_factory() (not bare _async_session_factory)
        assert "get_session_factory()" in source

    def test_lifespan_has_startup_validation(self):
        """main.py lifespan should validate required settings on startup."""
        import inspect
        from cxo_ai_companion.main import lifespan

        source = inspect.getsource(lifespan)

        assert "ACS_CONNECTION_STRING" in source
        assert "HTTPS" in source or "https://" in source
