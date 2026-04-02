"""Abstract base vector store and shared data structures."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class DistanceMetric(Enum):
    """Supported vector distance metrics for similarity search."""

    COSINE = "cosine"
    EUCLIDEAN = "euclidean"
    DOT_PRODUCT = "dot_product"


@dataclass
class VectorDocument:
    """A document stored in the vector store.

    Attributes:
        id: Unique identifier (typically a UUID hex string).
        vector: Dense embedding vector for similarity search.
        content: The plain-text content of the document chunk.
        metadata: Arbitrary key-value metadata attached to the document.
    """

    id: str
    vector: list[float]
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class VectorSearchResult:
    """A single result from a vector similarity search.

    Attributes:
        document: The matched vector document.
        score: Similarity score (higher is more similar).
        rank: 1-based position in the result set.
    """

    document: VectorDocument
    score: float
    rank: int


class BaseVectorStore(ABC):
    """Abstract base class for vector store implementations.

    Provides a CRUD + search interface over vectorised documents.
    """

    @abstractmethod
    async def upsert(self, documents: list[VectorDocument]) -> int:
        """Insert or update documents in the store.

        Args:
            documents: Documents to upsert.

        Returns:
            The number of documents successfully upserted.
        """

    @abstractmethod
    async def search(
        self,
        query_vector: list[float],
        k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]:
        """Perform a similarity search.

        Args:
            query_vector: The query embedding vector.
            k: Number of results to return.
            filters: Optional metadata filters.

        Returns:
            A list of :class:`VectorSearchResult` ordered by relevance.
        """

    @abstractmethod
    async def delete(self, ids: list[str]) -> int:
        """Delete documents by their IDs.

        Args:
            ids: Document IDs to delete.

        Returns:
            The number of documents actually deleted.
        """

    @abstractmethod
    async def get(self, id: str) -> VectorDocument | None:
        """Retrieve a single document by ID.

        Args:
            id: The document ID.

        Returns:
            The document, or ``None`` if not found.
        """

    @abstractmethod
    async def count(self) -> int:
        """Return the total number of documents in the store."""


__all__ = [
    "DistanceMetric",
    "VectorDocument",
    "VectorSearchResult",
    "BaseVectorStore",
]
