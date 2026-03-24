"""Pydantic v2 schemas for global search."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel


class SearchResultItem(BaseModel):
    """A single result from a global search query.

    Represents a matched entity across meetings, documents, action items,
    or people.

    Attributes:
        type: Entity type (meeting, document, action_item, person).
        id: Unique identifier of the matched entity.
        title: Display title for the result.
        snippet: Relevant text excerpt with match context.
        score: Relevance score from the search engine (0.0+).
        metadata: Additional type-specific metadata.
    """

    type: str  # meeting | document | action_item | person
    id: uuid.UUID
    title: str
    snippet: str = ""
    score: float = 0.0
    metadata: dict[str, Any] = {}


class SearchResponse(BaseModel):
    """Response wrapper for a global search query.

    Attributes:
        results: List of matched search result items.
        total: Total number of results across all pages.
        query: The original search query string that was executed.
    """

    results: list[SearchResultItem]
    total: int
    query: str
