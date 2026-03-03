"""
Owner Resolver service for matching names extracted by the LLM to real Azure AD users.

Uses a multi-strategy approach: exact match, partial (first-name) match, fuzzy match
via rapidfuzz, and finally a Graph API user search as a last resort.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from rapidfuzz import fuzz, process

if TYPE_CHECKING:
    from app.services.graph_client import GraphClient

from app.models import MeetingParticipant

logger = logging.getLogger(__name__)

# Minimum score (0-100) for rapidfuzz fuzzy matching to count as a hit
_FUZZY_MATCH_THRESHOLD = 80


class OwnerResolver:
    """Resolves a name mentioned in a transcript to an actual Azure AD user."""

    def __init__(self, graph_client: GraphClient) -> None:
        self.graph = graph_client

    async def resolve(
        self,
        name: str,
        participants: list[MeetingParticipant],
    ) -> tuple[str | None, str | None]:
        """
        Resolve a name mentioned in the transcript to a real user.

        Strategy (in order of precedence):
        1. Exact match against meeting participant display names (case-insensitive).
        2. Partial match: check if the name is a first name of any participant
           (e.g. "John" matches "John Smith").
        3. Fuzzy match using rapidfuzz against participant display names
           (threshold >= 80).
        4. Search Graph API via graph_client.search_user(name).
        5. If no match is found, return (None, None).

        Returns:
            (user_id, email) on success, or (None, None) if unresolved.
        """
        if not name or not name.strip():
            return None, None

        cleaned = name.strip()

        # --- Strategy 1: Exact match (case-insensitive) ---
        match = self._exact_match(cleaned, participants)
        if match is not None:
            logger.info("Resolved '%s' via exact match → %s", cleaned, match.email)
            return match.user_id, match.email

        # --- Strategy 2: Partial / first-name match ---
        match = self._partial_match(cleaned, participants)
        if match is not None:
            logger.info("Resolved '%s' via partial match → %s (%s)", cleaned, match.display_name, match.email)
            return match.user_id, match.email

        # --- Strategy 3: Fuzzy match via rapidfuzz ---
        match = self._fuzzy_match(cleaned, participants)
        if match is not None:
            logger.info("Resolved '%s' via fuzzy match → %s (%s)", cleaned, match.display_name, match.email)
            return match.user_id, match.email

        # --- Strategy 4: Graph API user search ---
        graph_result = await self._graph_search(cleaned)
        if graph_result is not None:
            user_id, email = graph_result
            logger.info("Resolved '%s' via Graph API search → %s", cleaned, email)
            return user_id, email

        # --- Strategy 5: No match found ---
        logger.warning("Could not resolve name '%s' to any user", cleaned)
        return None, None

    # ------------------------------------------------------------------
    # Strategy implementations
    # ------------------------------------------------------------------

    @staticmethod
    def _exact_match(
        name: str, participants: list[MeetingParticipant]
    ) -> MeetingParticipant | None:
        """Case-insensitive exact match against participant display names."""
        name_lower = name.lower()
        for p in participants:
            if p.display_name.lower() == name_lower:
                return p
        return None

    @staticmethod
    def _partial_match(
        name: str, participants: list[MeetingParticipant]
    ) -> MeetingParticipant | None:
        """
        Check if the given name matches the first name of any participant.

        For example, "John" matches a participant named "John Smith".
        Also handles the case where the name matches any single token in
        the participant's display name (e.g. "Smith" matches "John Smith").
        """
        name_lower = name.lower()
        for p in participants:
            parts = p.display_name.lower().split()
            # Match against first name
            if parts and parts[0] == name_lower:
                return p
            # Also match against last name or any single token
            if name_lower in parts:
                return p
        return None

    @staticmethod
    def _fuzzy_match(
        name: str, participants: list[MeetingParticipant]
    ) -> MeetingParticipant | None:
        """
        Use rapidfuzz to find the best fuzzy match among participant names.

        Returns the participant only if the best match score meets or exceeds
        the threshold (default 80).
        """
        if not participants:
            return None

        # Build a mapping of display_name -> participant for lookup
        name_to_participant: dict[str, MeetingParticipant] = {
            p.display_name: p for p in participants
        }
        choices = list(name_to_participant.keys())

        # Use token_sort_ratio for resilience against word-order differences
        best = process.extractOne(
            name,
            choices,
            scorer=fuzz.token_sort_ratio,
            score_cutoff=_FUZZY_MATCH_THRESHOLD,
        )

        if best is not None:
            matched_name, score, _index = best
            logger.debug("Fuzzy match: '%s' → '%s' (score=%.1f)", name, matched_name, score)
            return name_to_participant[matched_name]

        return None

    async def _graph_search(self, name: str) -> tuple[str, str] | None:
        """
        Search for a user in Azure AD via Graph API.

        Calls graph_client.search_user which executes:
        GET /users?$filter=startswith(displayName, '{name}')

        Returns (user_id, email) for the first match, or None.
        """
        try:
            results = await self.graph.search_user(name)
        except Exception:
            logger.exception("Graph API user search failed for '%s'", name)
            return None

        if not results:
            return None

        # Take the first result — most relevant match
        user = results[0]
        user_id = user.get("id")
        email = user.get("mail") or user.get("userPrincipalName")

        if user_id and email:
            return user_id, email

        return None
