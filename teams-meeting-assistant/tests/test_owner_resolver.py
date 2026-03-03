"""Tests for the OwnerResolver service.

Covers:
- Exact name match against participant display names
- First-name-only match
- Fuzzy match via rapidfuzz
- No match returns (None, None)
- Graph API search as fallback
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from tests.conftest import _TEST_ENV

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_participant(
    display_name: str,
    user_id: str | None = None,
    email: str | None = None,
):
    """Create a mock MeetingParticipant."""
    p = MagicMock()
    p.display_name = display_name
    p.user_id = user_id
    p.email = email
    return p


def _standard_participants():
    """Return a standard set of meeting participants for testing."""
    return [
        _make_participant(
            "Alice Johnson",
            user_id="aad-alice-001",
            email="alice.johnson@contoso.com",
        ),
        _make_participant(
            "Bob Williams",
            user_id="aad-bob-002",
            email="bob.williams@contoso.com",
        ),
        _make_participant(
            "Carol Martinez",
            user_id="aad-carol-003",
            email="carol.martinez@contoso.com",
        ),
    ]


# ---------------------------------------------------------------------------
# Test: Exact name match
# ---------------------------------------------------------------------------

async def test_exact_name_match():
    """Exact match (case-insensitive) should return the participant's user_id and email."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from app.services.owner_resolver import OwnerResolver

        mock_graph = AsyncMock()
        resolver = OwnerResolver(graph_client=mock_graph)
        participants = _standard_participants()

        # Exact match (same case)
        user_id, email = await resolver.resolve("Alice Johnson", participants)
        assert user_id == "aad-alice-001"
        assert email == "alice.johnson@contoso.com"

        # Exact match (different case)
        user_id, email = await resolver.resolve("bob williams", participants)
        assert user_id == "aad-bob-002"
        assert email == "bob.williams@contoso.com"

        # Graph search should NOT have been called (resolved locally)
        mock_graph.search_user.assert_not_called()


# ---------------------------------------------------------------------------
# Test: First name match
# ---------------------------------------------------------------------------

async def test_first_name_match():
    """A first-name-only match should resolve to the correct participant."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from app.services.owner_resolver import OwnerResolver

        mock_graph = AsyncMock()
        resolver = OwnerResolver(graph_client=mock_graph)
        participants = _standard_participants()

        # First name only
        user_id, email = await resolver.resolve("Alice", participants)
        assert user_id == "aad-alice-001"
        assert email == "alice.johnson@contoso.com"

        user_id, email = await resolver.resolve("Bob", participants)
        assert user_id == "aad-bob-002"
        assert email == "bob.williams@contoso.com"

        # Last name should also match (partial match checks all tokens)
        user_id, email = await resolver.resolve("Martinez", participants)
        assert user_id == "aad-carol-003"
        assert email == "carol.martinez@contoso.com"

        mock_graph.search_user.assert_not_called()


# ---------------------------------------------------------------------------
# Test: Fuzzy match
# ---------------------------------------------------------------------------

async def test_fuzzy_match():
    """A slightly misspelled name should still resolve via fuzzy matching."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from app.services.owner_resolver import OwnerResolver

        mock_graph = AsyncMock()
        resolver = OwnerResolver(graph_client=mock_graph)
        participants = _standard_participants()

        # Typo: "Alce Johnson" (missing 'i') should fuzzy-match "Alice Johnson"
        user_id, email = await resolver.resolve("Alce Johnson", participants)
        assert user_id == "aad-alice-001"
        assert email == "alice.johnson@contoso.com"

        # Reversed order: "Williams Bob" should fuzzy-match "Bob Williams"
        user_id, email = await resolver.resolve("Williams Bob", participants)
        assert user_id == "aad-bob-002"
        assert email == "bob.williams@contoso.com"

        mock_graph.search_user.assert_not_called()


# ---------------------------------------------------------------------------
# Test: No match returns None
# ---------------------------------------------------------------------------

async def test_no_match_returns_none():
    """A name with no match (locally or via Graph) should return (None, None)."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from app.services.owner_resolver import OwnerResolver

        mock_graph = AsyncMock()
        mock_graph.search_user = AsyncMock(return_value=[])  # Graph also returns nothing

        resolver = OwnerResolver(graph_client=mock_graph)
        participants = _standard_participants()

        user_id, email = await resolver.resolve(
            "Completely Unknown Person", participants
        )
        assert user_id is None
        assert email is None

        # Graph search should have been called as a fallback
        mock_graph.search_user.assert_called_once_with("Completely Unknown Person")

        # Empty string should also return None
        user_id, email = await resolver.resolve("", participants)
        assert user_id is None
        assert email is None


# ---------------------------------------------------------------------------
# Test: Graph search fallback
# ---------------------------------------------------------------------------

async def test_graph_search_fallback():
    """When local matching fails, the resolver should search via Graph API."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from app.services.owner_resolver import OwnerResolver

        mock_graph = AsyncMock()
        # Graph returns a user that isn't a participant
        mock_graph.search_user = AsyncMock(
            return_value=[
                {
                    "id": "aad-external-user-99",
                    "displayName": "David Lee",
                    "mail": "david.lee@external.com",
                    "userPrincipalName": "david.lee@external.com",
                }
            ]
        )

        resolver = OwnerResolver(graph_client=mock_graph)
        participants = _standard_participants()

        # "David Lee" is NOT a participant, so local matching fails
        user_id, email = await resolver.resolve("David Lee", participants)

        # Should fall back to Graph search and find the user
        assert user_id == "aad-external-user-99"
        assert email == "david.lee@external.com"

        mock_graph.search_user.assert_called_once_with("David Lee")
