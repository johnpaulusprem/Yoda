"""Abstract base retriever and shared data structures for document retrieval."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RetrievedDocument:
    """A document returned from a retrieval operation.

    Attributes:
        id: Unique identifier for the retrieved document.
        content: The text content of the document.
        score: Relevance score from the retrieval method.
        rank: Position in the result set (1-based).
        metadata: Additional metadata associated with the document.
    """

    id: str
    content: str
    score: float
    rank: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RetrievalResult:
    """Aggregated result of a retrieval operation.

    Attributes:
        documents: The list of retrieved documents ordered by relevance.
        query: The original query string.
        total_results: Total number of results returned.
        execution_time_ms: Time taken to perform the retrieval in milliseconds.
    """

    documents: list[RetrievedDocument]
    query: str
    total_results: int
    execution_time_ms: float


class BaseRetriever(ABC):
    """Abstract base class for all retrieval strategies.

    Subclasses must implement :meth:`retrieve` to fetch documents
    relevant to a given query.
    """

    @abstractmethod
    async def retrieve(
        self,
        query: str,
        k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> RetrievalResult:
        """Retrieve documents relevant to the query.

        Args:
            query: The search query string.
            k: Maximum number of documents to return.
            filters: Optional metadata filters to narrow the search.

        Returns:
            A :class:`RetrievalResult` containing the matching documents.
        """


__all__ = [
    "BaseRetriever",
    "RetrievedDocument",
    "RetrievalResult",
]
