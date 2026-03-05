"""Tests for the bot events route (transcript ingest + lifecycle events)."""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import _TEST_ENV

pytestmark = pytest.mark.asyncio


def _make_hmac_headers(
    method: str, path: str, body: bytes, key: str = "test-hmac-key-for-testing"
) -> dict[str, str]:
    """Generate HMAC auth headers for a request."""
    timestamp = str(int(time.time()))
    body_hash = hashlib.sha256(body).hexdigest()
    payload = f"{timestamp}{method}{path}{body_hash}"
    sig = hmac.new(key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return {
        "X-Request-Timestamp": timestamp,
        "X-Request-Signature": sig,
    }


# ---------------------------------------------------------------------------
# Test: Transcript ingest
# ---------------------------------------------------------------------------


async def test_transcript_ingest_stores_segments(test_client, sample_meeting):
    """POST /api/bot-events/transcript should store transcript segments in the DB."""
    body = {
        "meeting_id": str(sample_meeting.id),
        "bot_instance_id": "test-bot",
        "segments": [
            {
                "sequence": 0,
                "speaker_id": "aad-user-001",
                "speaker_name": "Alice Johnson",
                "text": "Hello everyone, let's get started.",
                "start_time_sec": 0.0,
                "end_time_sec": 3.5,
                "confidence": 0.95,
                "is_final": True,
            },
            {
                "sequence": 1,
                "speaker_id": "aad-user-002",
                "speaker_name": "Bob Williams",
                "text": "Sounds good, I have updates on the auth refactor.",
                "start_time_sec": 4.0,
                "end_time_sec": 8.0,
                "confidence": 0.93,
                "is_final": True,
            },
        ],
    }

    import json

    body_bytes = json.dumps(body).encode()
    headers = _make_hmac_headers("POST", "/api/bot-events/transcript", body_bytes)

    headers["Content-Type"] = "application/json"
    response = await test_client.post(
        "/api/bot-events/transcript", content=body_bytes, headers=headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["received"] == 2


async def test_transcript_ingest_skips_non_final(test_client, sample_meeting):
    """Non-final segments should be skipped."""
    body = {
        "meeting_id": str(sample_meeting.id),
        "bot_instance_id": "test-bot",
        "segments": [
            {
                "sequence": 0,
                "speaker_name": "Alice",
                "text": "Partial...",
                "start_time_sec": 0.0,
                "end_time_sec": 1.0,
                "is_final": False,
            },
        ],
    }

    import json

    body_bytes = json.dumps(body).encode()
    headers = _make_hmac_headers("POST", "/api/bot-events/transcript", body_bytes)

    headers["Content-Type"] = "application/json"
    response = await test_client.post(
        "/api/bot-events/transcript", content=body_bytes, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["received"] == 0


# ---------------------------------------------------------------------------
# Test: Lifecycle events
# ---------------------------------------------------------------------------


async def test_lifecycle_bot_joined(test_client, sample_meeting, async_session):
    """bot_joined event should set meeting status to in_progress."""
    # Reset meeting to scheduled
    sample_meeting.status = "scheduled"
    sample_meeting.actual_start = None
    await async_session.commit()

    body = {
        "meeting_id": str(sample_meeting.id),
        "bot_instance_id": "test-bot",
        "event_type": "bot_joined",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    import json

    body_bytes = json.dumps(body).encode()
    headers = _make_hmac_headers("POST", "/api/bot-events/lifecycle", body_bytes)

    headers["Content-Type"] = "application/json"
    response = await test_client.post(
        "/api/bot-events/lifecycle", content=body_bytes, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    await async_session.refresh(sample_meeting)
    assert sample_meeting.status == "in_progress"
    assert sample_meeting.actual_start is not None


async def test_lifecycle_meeting_ended(test_client, sample_meeting, async_session):
    """meeting_ended event should set meeting status to completed."""
    sample_meeting.status = "in_progress"
    sample_meeting.actual_end = None
    await async_session.commit()

    body = {
        "meeting_id": str(sample_meeting.id),
        "bot_instance_id": "test-bot",
        "event_type": "meeting_ended",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    import json

    body_bytes = json.dumps(body).encode()
    headers = _make_hmac_headers("POST", "/api/bot-events/lifecycle", body_bytes)

    headers["Content-Type"] = "application/json"
    response = await test_client.post(
        "/api/bot-events/lifecycle", content=body_bytes, headers=headers
    )
    assert response.status_code == 200

    await async_session.refresh(sample_meeting)
    assert sample_meeting.status == "completed"
    assert sample_meeting.actual_end is not None


async def test_lifecycle_participants_updated(
    test_client, sample_meeting, async_session
):
    """participants_updated event should add participants to the DB."""
    sample_meeting.status = "in_progress"
    sample_meeting.participant_count = 0
    await async_session.commit()

    body = {
        "meeting_id": str(sample_meeting.id),
        "bot_instance_id": "test-bot",
        "event_type": "participants_updated",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": {
            "participants": [
                {"id": "aad-user-p1", "displayName": "Participant One"},
                {"id": "aad-user-p2", "displayName": "Participant Two"},
            ]
        },
    }

    import json

    body_bytes = json.dumps(body).encode()
    headers = _make_hmac_headers("POST", "/api/bot-events/lifecycle", body_bytes)

    headers["Content-Type"] = "application/json"
    response = await test_client.post(
        "/api/bot-events/lifecycle", content=body_bytes, headers=headers
    )
    assert response.status_code == 200

    from app.models.meeting import MeetingParticipant

    result = await async_session.execute(
        select(MeetingParticipant).where(
            MeetingParticipant.meeting_id == sample_meeting.id
        )
    )
    participants = result.scalars().all()
    assert len(participants) == 2

    await async_session.refresh(sample_meeting)
    assert sample_meeting.participant_count == 2


async def test_lifecycle_unknown_meeting(test_client):
    """Lifecycle event for unknown meeting should return meeting_not_found."""
    body = {
        "meeting_id": str(uuid.uuid4()),
        "bot_instance_id": "test-bot",
        "event_type": "bot_joined",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    import json

    body_bytes = json.dumps(body).encode()
    headers = _make_hmac_headers("POST", "/api/bot-events/lifecycle", body_bytes)

    headers["Content-Type"] = "application/json"
    response = await test_client.post(
        "/api/bot-events/lifecycle", content=body_bytes, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["status"] == "meeting_not_found"
