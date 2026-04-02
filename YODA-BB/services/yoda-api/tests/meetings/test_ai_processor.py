"""Tests for the AI Processor service.

Covers:
- Short meetings use gpt-4o-mini model
- Long meetings use chunked processing with gpt-4o
- Malformed LLM response handled gracefully (returns empty result)
- JSON parsing of well-formed extraction results
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from tests.conftest import _TEST_ENV

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_meeting(duration_minutes: float = 30):
    """Create a mock Meeting object with the given duration."""
    now = datetime.now(timezone.utc)
    meeting = MagicMock()
    meeting.id = uuid.uuid4()
    meeting.subject = "Test Meeting"
    meeting.scheduled_start = now - timedelta(minutes=duration_minutes)
    meeting.scheduled_end = now
    meeting.actual_start = now - timedelta(minutes=duration_minutes)
    meeting.actual_end = now

    # Participants as mock objects with display_name
    p1 = MagicMock()
    p1.display_name = "Alice Johnson"
    p2 = MagicMock()
    p2.display_name = "Bob Williams"
    meeting.participants = [p1, p2]

    return meeting


def _make_segments(count: int = 5, start_time_offset: float = 0.0):
    """Create mock TranscriptSegment objects."""
    segments = []
    for i in range(count):
        seg = MagicMock()
        seg.speaker_name = "Alice Johnson" if i % 2 == 0 else "Bob Williams"
        seg.start_time = start_time_offset + i * 10.0
        seg.end_time = start_time_offset + i * 10.0 + 8.0
        seg.text = f"Transcript line {i + 1}: discussing item {i + 1}."
        seg.sequence_number = i
        segments.append(seg)
    return segments


_VALID_LLM_RESPONSE = json.dumps({
    "summary": "This meeting covered sprint planning tasks.",
    "action_items": [
        {
            "description": "Complete auth refactor",
            "assigned_to": "Bob Williams",
            "deadline": "2026-03-10",
            "priority": "high",
            "source_quote": "Bob, can you take the lead on the auth refactor?",
        }
    ],
    "decisions": [
        {
            "decision": "Use URL-based API versioning",
            "context": "Chosen for explicitness and easier testing.",
        }
    ],
    "key_topics": [
        {
            "topic": "Auth Refactor",
            "timestamp": "00:05",
            "detail": "Discussed prioritization and assignment.",
        }
    ],
    "unresolved_questions": [
        "What specific staging environment access does Bob need?"
    ],
})


# ---------------------------------------------------------------------------
# Test: Short meeting uses mini model
# ---------------------------------------------------------------------------

async def test_short_meeting_uses_mini_model():
    """A meeting under LONG_MEETING_THRESHOLD_MINUTES should use gpt-4o-mini."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from meeting_service.config import Settings
        from meeting_service.services.ai_processor import AIProcessor

        settings = Settings()
        processor = AIProcessor(settings=settings)

        meeting = _make_meeting(duration_minutes=30)  # short meeting
        segments = _make_segments(5)

        # Mock the LLM call
        processor._call_llm = AsyncMock(return_value=_VALID_LLM_RESPONSE)

        result = await processor.process_meeting(meeting, segments)

        # Should have used the mini model (single-pass, not chunked)
        assert result["model_used"] == "gpt-4o-mini"
        assert result["summary"] == "This meeting covered sprint planning tasks."
        assert len(result["action_items"]) == 1
        assert len(result["decisions"]) == 1

        # Verify _call_llm was called with the mini model
        call_args = processor._call_llm.call_args
        assert call_args[0][2] == "gpt-4o-mini"  # third positional arg is model


# ---------------------------------------------------------------------------
# Test: Long meeting uses chunked processing
# ---------------------------------------------------------------------------

async def test_long_meeting_uses_chunked_processing():
    """A meeting >= LONG_MEETING_THRESHOLD_MINUTES should use chunked processing."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from meeting_service.config import Settings
        from meeting_service.services.ai_processor import AIProcessor

        settings = Settings()
        processor = AIProcessor(settings=settings)

        # Create a 3-hour meeting (180 minutes, above the 120-minute threshold)
        meeting = _make_meeting(duration_minutes=180)

        # Create segments spanning 3 hours (180 * 60 = 10800 seconds)
        # We need segments that span multiple 30-minute chunks
        segments = []
        for i in range(60):  # 60 segments, roughly 1 every 3 minutes
            seg = MagicMock()
            seg.speaker_name = "Alice Johnson" if i % 2 == 0 else "Bob Williams"
            seg.start_time = i * 180.0  # every 3 minutes
            seg.end_time = i * 180.0 + 120.0
            seg.text = f"Discussion point {i + 1} in chunk."
            seg.sequence_number = i
            segments.append(seg)

        # Mock _call_llm to return valid JSON for each chunk + final summary
        chunk_response = json.dumps({
            "summary": "Chunk summary of discussion.",
            "action_items": [
                {
                    "description": "Chunk action item",
                    "assigned_to": "Bob",
                    "deadline": None,
                    "priority": "medium",
                    "source_quote": "Some quote",
                }
            ],
            "decisions": [],
            "key_topics": [
                {"topic": "Topic A", "timestamp": "00:00", "detail": "Details."}
            ],
            "unresolved_questions": [],
        })

        final_summary_response = json.dumps({
            "summary": "Cohesive final summary of the entire 3-hour meeting.",
        })

        # The chunked processor calls _call_llm once per chunk + once for final summary
        call_count = 0

        async def mock_llm(system, user, model):
            nonlocal call_count
            call_count += 1
            # All chunk calls use gpt-4o, final call also uses gpt-4o
            assert model == "gpt-4o", f"Expected gpt-4o, got {model}"
            if "Chunk Summaries" in user:
                return final_summary_response
            return chunk_response

        processor._call_llm = mock_llm

        result = await processor.process_meeting(meeting, segments)

        # Should use the complex model
        assert result["model_used"] == "gpt-4o"
        assert "Cohesive final summary" in result["summary"]
        # Should have some action items from chunks
        assert len(result["action_items"]) >= 1
        # The LLM should have been called multiple times (chunks + final)
        assert call_count >= 2


# ---------------------------------------------------------------------------
# Test: Malformed LLM response handled gracefully
# ---------------------------------------------------------------------------

async def test_malformed_llm_response_handled_gracefully():
    """If the LLM returns non-JSON, the processor should return empty defaults."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from meeting_service.config import Settings
        from meeting_service.services.ai_processor import AIProcessor

        settings = Settings()
        processor = AIProcessor(settings=settings)

        meeting = _make_meeting(duration_minutes=30)
        segments = _make_segments(3)

        # Return garbage from the LLM
        processor._call_llm = AsyncMock(
            return_value="This is not valid JSON at all! <html>Error</html>"
        )

        result = await processor.process_meeting(meeting, segments)

        # Should return empty defaults instead of crashing
        assert result["summary"] == ""
        assert result["action_items"] == []
        assert result["decisions"] == []
        assert result["key_topics"] == []
        assert result["unresolved_questions"] == []
        assert "processing_time_seconds" in result


# ---------------------------------------------------------------------------
# Test: JSON parsing of extraction result
# ---------------------------------------------------------------------------

async def test_json_parsing_of_extraction_result():
    """The processor should correctly parse a well-formed LLM JSON response."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from meeting_service.config import Settings
        from meeting_service.services.ai_processor import AIProcessor

        settings = Settings()
        processor = AIProcessor(settings=settings)

        meeting = _make_meeting(duration_minutes=45)
        segments = _make_segments(5)

        # LLM returns valid JSON with markdown code fences (common LLM behavior)
        response_with_fences = (
            "```json\n"
            + _VALID_LLM_RESPONSE
            + "\n```"
        )
        processor._call_llm = AsyncMock(return_value=response_with_fences)

        result = await processor.process_meeting(meeting, segments)

        # Verify all fields were parsed correctly
        assert result["summary"] == "This meeting covered sprint planning tasks."

        assert len(result["action_items"]) == 1
        ai = result["action_items"][0]
        assert ai["description"] == "Complete auth refactor"
        assert ai["assigned_to"] == "Bob Williams"
        assert ai["priority"] == "high"
        assert ai["source_quote"] == "Bob, can you take the lead on the auth refactor?"

        assert len(result["decisions"]) == 1
        assert result["decisions"][0]["decision"] == "Use URL-based API versioning"

        assert len(result["key_topics"]) == 1
        assert result["key_topics"][0]["topic"] == "Auth Refactor"

        assert len(result["unresolved_questions"]) == 1
        assert "staging environment" in result["unresolved_questions"][0]
