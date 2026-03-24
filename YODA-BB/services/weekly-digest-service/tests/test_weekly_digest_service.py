"""Tests for WeeklyDigestService."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from weekly_digest_service.services.weekly_digest_service import WeeklyDigestService
from yoda_foundation.models.insight import WeeklyDigest


# ---------------------------------------------------------------------------
# generate_digest
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_digest_empty_week(async_session_factory):
    """Generates a digest even with no meetings or action items."""
    service = WeeklyDigestService(
        ai_connector=None,
        delivery_service=None,
        db_session_factory=async_session_factory,
    )

    digest = await service.generate_digest(user_id="aad-user-001")

    assert digest.user_id == "aad-user-001"
    assert digest.total_meetings == 0
    assert digest.total_action_items == 0
    assert digest.completion_rate == 0.0
    assert digest.delivered is False
    assert "Meetings: 0" in digest.digest_text


@pytest.mark.asyncio
async def test_generate_digest_with_data(
    async_session_factory,
    seed_weekly_data,
):
    """Generates a digest reflecting the seeded weekly data."""
    service = WeeklyDigestService(
        ai_connector=None,
        delivery_service=None,
        db_session_factory=async_session_factory,
    )

    digest = await service.generate_digest(user_id="aad-user-001")

    assert digest.total_meetings == 3
    assert digest.total_action_items == 3
    # 1 out of 3 is completed => 33.3%
    assert 33.0 <= digest.completion_rate <= 34.0
    assert len(digest.key_decisions) >= 1
    assert digest.delivered is False


@pytest.mark.asyncio
async def test_generate_digest_with_ai(
    async_session_factory,
    seed_weekly_data,
    mock_ai_connector: AsyncMock,
):
    """AI connector produces the digest narrative text."""
    service = WeeklyDigestService(
        ai_connector=mock_ai_connector,
        delivery_service=None,
        db_session_factory=async_session_factory,
    )

    digest = await service.generate_digest(user_id="aad-user-001")

    assert "productive meetings" in digest.digest_text
    mock_ai_connector.complete.assert_called_once()


@pytest.mark.asyncio
async def test_generate_digest_ai_failure_fallback(
    async_session_factory,
    seed_weekly_data,
):
    """AI failure falls back to a simple stats-based digest text."""
    failing_ai = AsyncMock()
    failing_ai.complete = AsyncMock(side_effect=RuntimeError("AI unavailable"))

    service = WeeklyDigestService(
        ai_connector=failing_ai,
        delivery_service=None,
        db_session_factory=async_session_factory,
    )

    digest = await service.generate_digest(user_id="aad-user-001")

    # Fallback text should contain basic stats
    assert "Meetings: 3" in digest.digest_text
    assert digest.total_meetings == 3


@pytest.mark.asyncio
async def test_generate_digest_persists(
    async_session_factory,
    async_session: AsyncSession,
    seed_weekly_data,
):
    """Digest is persisted to the database."""
    service = WeeklyDigestService(
        ai_connector=None,
        delivery_service=None,
        db_session_factory=async_session_factory,
    )

    digest = await service.generate_digest(user_id="aad-user-001")

    # Verify it exists in DB
    result = await async_session.execute(
        select(WeeklyDigest).where(WeeklyDigest.id == digest.id)
    )
    db_digest = result.scalar_one_or_none()
    assert db_digest is not None
    assert db_digest.user_id == "aad-user-001"
    assert db_digest.total_meetings == 3


# ---------------------------------------------------------------------------
# deliver_digest
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deliver_digest(
    async_session_factory,
    seed_weekly_data,
):
    """Delivering a digest marks it as delivered."""
    service = WeeklyDigestService(
        ai_connector=None,
        delivery_service=None,
        db_session_factory=async_session_factory,
    )

    digest = await service.generate_digest(user_id="aad-user-001")
    assert digest.delivered is False

    await service.deliver_digest(digest.id)

    # Verify delivered flag
    async with async_session_factory() as db:
        result = await db.execute(
            select(WeeklyDigest).where(WeeklyDigest.id == digest.id)
        )
        updated = result.scalar_one()
        assert updated.delivered is True
        assert updated.delivered_at is not None


@pytest.mark.asyncio
async def test_deliver_digest_nonexistent(async_session_factory):
    """Delivering a non-existent digest is a no-op."""
    service = WeeklyDigestService(
        ai_connector=None,
        delivery_service=None,
        db_session_factory=async_session_factory,
    )

    # Should not raise
    await service.deliver_digest(uuid.uuid4())


@pytest.mark.asyncio
async def test_deliver_digest_already_delivered(
    async_session_factory,
    seed_weekly_data,
):
    """Re-delivering an already-delivered digest is a no-op."""
    service = WeeklyDigestService(
        ai_connector=None,
        delivery_service=None,
        db_session_factory=async_session_factory,
    )

    digest = await service.generate_digest(user_id="aad-user-001")
    await service.deliver_digest(digest.id)
    # Deliver again -- should be a no-op
    await service.deliver_digest(digest.id)

    async with async_session_factory() as db:
        result = await db.execute(
            select(WeeklyDigest).where(WeeklyDigest.id == digest.id)
        )
        updated = result.scalar_one()
        assert updated.delivered is True


# ---------------------------------------------------------------------------
# People notes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_people_notes_populated(
    async_session_factory,
    seed_weekly_data,
):
    """People notes include participants from this week's meetings."""
    service = WeeklyDigestService(
        ai_connector=None,
        delivery_service=None,
        db_session_factory=async_session_factory,
    )

    digest = await service.generate_digest(user_id="aad-user-001")

    assert len(digest.people_notes) >= 1
    names = [n["display_name"] for n in digest.people_notes]
    assert "Alice Johnson" in names or "Bob Williams" in names


@pytest.mark.asyncio
async def test_follow_ups_populated(
    async_session_factory,
    seed_weekly_data,
):
    """Follow-ups include pending action items."""
    service = WeeklyDigestService(
        ai_connector=None,
        delivery_service=None,
        db_session_factory=async_session_factory,
    )

    digest = await service.generate_digest(user_id="aad-user-001")

    # We seeded 1 pending action item
    assert len(digest.follow_ups) >= 1
    pending_descriptions = [f["description"] for f in digest.follow_ups]
    assert any("Action item" in d for d in pending_descriptions)
