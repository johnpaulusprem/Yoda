"""
Semantic memory tier for the Agentic AI Component Library.

Knowledge-based memory tier that supports vector similarity search using
cosine similarity on embedding vectors. Stores factual knowledge and
supports rich semantic retrieval.

Example:
    ```python
    from yoda_foundation.memory.tiers import SemanticMemoryTier

    tier = SemanticMemoryTier()
    await tier.initialize(security_context)

    entry = MemoryEntry.create(
        tier=MemoryTier.SEMANTIC,
        scope=MemoryScope.USER,
        content=MemoryContent(
            content="Python is a high-level programming language",
            embedding=[0.1, 0.2, 0.3, ...],
        ),
        tags=["programming", "python"],
    )
    result = await tier.store(entry, security_context)
    ```
"""

from __future__ import annotations

import math
import time
from typing import Any

from yoda_foundation.exceptions.memory import (
    MemoryNotFoundError,
    MemoryRetrievalError,
    MemoryStorageError,
    MemoryTierError,
)
from yoda_foundation.memory.base_tier import BaseTier
from yoda_foundation.memory.schemas import (
    MemoryContent,
    MemoryEntry,
    MemoryTier,
    SearchFilter,
    SearchResult,
    StoreResult,
)
from yoda_foundation.security.context import SecurityContext


class SemanticMemoryTier(BaseTier):
    """
    In-memory semantic memory tier with vector similarity search.

    Semantic memory stores factual knowledge and supports retrieval via
    cosine similarity on embedding vectors. When embeddings are available,
    search uses vector similarity; otherwise it falls back to text matching.

    Attributes:
        tier: Always MemoryTier.SEMANTIC.
        config: Configuration with keys:
            - max_entries (int): Maximum stored entries (default 50000).
            - similarity_threshold (float): Minimum cosine similarity for
              results (default 0.0).

    Example:
        ```python
        tier = SemanticMemoryTier(config={"similarity_threshold": 0.5})
        await tier.initialize(security_context)

        # Store with embedding
        entry = MemoryEntry.create(
            tier=MemoryTier.SEMANTIC,
            scope=MemoryScope.GLOBAL,
            content=MemoryContent(
                content="Machine learning is a subset of AI",
                embedding=[0.1, 0.2, 0.3],
            ),
        )
        await tier.store(entry, security_context)

        # Search with query embedding
        filters = SearchFilter(limit=5)
        result = await tier.search("AI techniques", filters, security_context)
        ```

    Raises:
        MemoryStorageError: When store operations fail.
        MemoryNotFoundError: When an entry ID is not found.
        MemoryRetrievalError: When search operations fail.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """
        Initialize the semantic memory tier.

        Args:
            config: Optional configuration dictionary. Supported keys:
                - max_entries (int): Maximum stored entries (default 50000).
                - similarity_threshold (float): Minimum cosine similarity (default 0.0).

        Example:
            ```python
            tier = SemanticMemoryTier(config={"similarity_threshold": 0.5})
            ```
        """
        super().__init__(tier=MemoryTier.SEMANTIC, config=config)
        self._entries: dict[str, MemoryEntry] = {}
        self._max_entries: int = self.config.get("max_entries", 50000)
        self._similarity_threshold: float = self.config.get("similarity_threshold", 0.0)

    async def initialize(self, security_context: SecurityContext) -> None:
        """
        Initialize the semantic memory tier.

        Args:
            security_context: Security context for the operation.

        Raises:
            MemoryTierError: If initialization fails.

        Example:
            ```python
            await tier.initialize(security_context)
            ```
        """
        try:
            self._entries = {}
            self._initialized = True
        except (OSError, RuntimeError) as e:
            raise MemoryTierError(
                message=f"Failed to initialize semantic memory tier: {e}",
                tier_name=self.tier.value,
                cause=e,
            ) from e

    async def close(self, security_context: SecurityContext) -> None:
        """
        Close the semantic memory tier and clear entries.

        Args:
            security_context: Security context for the operation.

        Example:
            ```python
            await tier.close(security_context)
            ```
        """
        self._entries.clear()
        self._initialized = False

    async def store(
        self,
        entry: MemoryEntry,
        security_context: SecurityContext,
    ) -> StoreResult:
        """
        Store a knowledge entry in semantic memory.

        Enforces max_entries capacity by evicting the entry with lowest
        importance when full.

        Args:
            entry: The memory entry to store (ideally with embedding).
            security_context: Security context for the operation.

        Returns:
            StoreResult indicating success.

        Raises:
            MemoryStorageError: If the store operation fails.

        Example:
            ```python
            result = await tier.store(entry, security_context)
            assert result.stored
            ```
        """
        self._ensure_initialized()
        try:
            # Evict lowest-importance entry if at capacity
            if len(self._entries) >= self._max_entries:
                least_important_id = min(
                    self._entries,
                    key=lambda eid: self._entries[eid].importance,
                )
                del self._entries[least_important_id]

            self._entries[entry.id] = entry
            return StoreResult(
                entry_id=entry.id,
                tier=self.tier,
                stored=True,
                message="Stored in semantic memory",
            )
        except (KeyError, TypeError, ValueError) as e:
            raise MemoryStorageError(
                message=f"Failed to store entry in semantic memory: {e}",
                memory_type=self.tier.value,
                entry_id=entry.id,
                cause=e,
            ) from e

    async def get(
        self,
        entry_id: str,
        security_context: SecurityContext,
    ) -> MemoryEntry:
        """
        Retrieve a knowledge entry by ID.

        Args:
            entry_id: Unique identifier of the entry.
            security_context: Security context for the operation.

        Returns:
            The requested MemoryEntry.

        Raises:
            MemoryNotFoundError: If the entry does not exist.

        Example:
            ```python
            entry = await tier.get("mem_abc123", security_context)
            ```
        """
        self._ensure_initialized()
        entry = self._entries.get(entry_id)
        if entry is None:
            raise MemoryNotFoundError(
                message=f"Entry '{entry_id}' not found in semantic memory",
                memory_type=self.tier.value,
                entry_id=entry_id,
            )

        entry.mark_accessed()
        return entry

    async def update(
        self,
        entry_id: str,
        content: MemoryContent,
        security_context: SecurityContext,
    ) -> MemoryEntry:
        """
        Update the content of an existing semantic memory entry.

        Args:
            entry_id: ID of the entry to update.
            content: New content (ideally with updated embedding).
            security_context: Security context for the operation.

        Returns:
            The updated MemoryEntry.

        Raises:
            MemoryNotFoundError: If the entry does not exist.

        Example:
            ```python
            updated = await tier.update("mem_abc123", new_content, security_context)
            ```
        """
        self._ensure_initialized()
        entry = self._entries.get(entry_id)
        if entry is None:
            raise MemoryNotFoundError(
                message=f"Entry '{entry_id}' not found in semantic memory",
                memory_type=self.tier.value,
                entry_id=entry_id,
            )

        entry.content = content
        entry.mark_accessed()
        return entry

    async def delete(
        self,
        entry_id: str,
        security_context: SecurityContext,
    ) -> bool:
        """
        Delete an entry from semantic memory.

        Args:
            entry_id: ID of the entry to delete.
            security_context: Security context for the operation.

        Returns:
            True if deleted, False if not found.

        Example:
            ```python
            deleted = await tier.delete("mem_abc123", security_context)
            ```
        """
        self._ensure_initialized()
        if entry_id in self._entries:
            del self._entries[entry_id]
            return True
        return False

    async def search(
        self,
        query: str,
        filters: SearchFilter,
        security_context: SecurityContext,
    ) -> SearchResult:
        """
        Search semantic memory using cosine similarity or text matching.

        When the query text has a matching embedding in at least one stored
        entry, cosine similarity is used. Otherwise falls back to text
        substring matching.

        To perform vector search, pass an embedding via the filters metadata
        or ensure entries have embeddings for cosine similarity comparison.
        This tier computes cosine similarity between the query embedding
        (extracted from the first entry that matches the query text) and
        all stored entry embeddings.

        Args:
            query: Text query for matching.
            filters: Additional filter criteria.
            security_context: Security context for the operation.

        Returns:
            SearchResult with matching entries sorted by similarity score.

        Raises:
            MemoryRetrievalError: If the search fails.

        Example:
            ```python
            result = await tier.search("machine learning", filters, security_context)
            ```
        """
        self._ensure_initialized()
        try:
            start_ms = int(time.monotonic() * 1000)
            matched: list[tuple[MemoryEntry, float]] = []
            query_lower = query.lower()

            # Try to find a query embedding from any entry whose content
            # closely matches the query (for vector-based search)
            query_embedding: list[float] | None = None
            for entry in self._entries.values():
                if (
                    entry.content.embedding is not None
                    and query_lower in entry.content.content.lower()
                ):
                    query_embedding = entry.content.embedding
                    break

            for entry in self._entries.values():
                if not self._matches_filters(entry, filters):
                    continue

                score: float
                if query_embedding is not None and entry.content.embedding is not None:
                    # Vector cosine similarity
                    cos_sim = self._cosine_similarity(
                        query_embedding,
                        entry.content.embedding,
                    )
                    if cos_sim < self._similarity_threshold:
                        continue
                    score = cos_sim
                else:
                    # Fallback to text matching
                    score = self._compute_text_score(query_lower, entry)

                if score > 0.0 or not query:
                    matched.append((entry, score))

            matched.sort(key=lambda pair: pair[1], reverse=True)
            limit = filters.limit if filters.limit else 10
            limited = matched[:limit]

            elapsed_ms = int(time.monotonic() * 1000) - start_ms
            return SearchResult(
                entries=[pair[0] for pair in limited],
                scores=[pair[1] for pair in limited],
                total_count=len(matched),
                query_time_ms=elapsed_ms,
            )
        except (KeyError, TypeError, ValueError) as e:
            raise MemoryRetrievalError(
                message=f"Search failed in semantic memory: {e}",
                memory_type=self.tier.value,
                query=query,
                cause=e,
            ) from e

    async def count(
        self,
        security_context: SecurityContext,
        filters: SearchFilter | None = None,
    ) -> int:
        """
        Count entries in semantic memory.

        Args:
            security_context: Security context for the operation.
            filters: Optional filter criteria.

        Returns:
            Number of matching entries.

        Example:
            ```python
            total = await tier.count(security_context)
            ```
        """
        self._ensure_initialized()
        if filters is None:
            return len(self._entries)

        return sum(1 for entry in self._entries.values() if self._matches_filters(entry, filters))

    async def decay(
        self,
        factor: float,
        security_context: SecurityContext,
    ) -> int:
        """
        Apply decay to semantic memory entries.

        Semantic memory decays slower than other tiers since knowledge
        tends to persist. The factor is applied more gently.

        Args:
            factor: Decay factor (0.0-1.0). Importance is multiplied by this.
            security_context: Security context for the operation.

        Returns:
            Number of entries affected.

        Example:
            ```python
            affected = await tier.decay(0.99, security_context)
            ```
        """
        self._ensure_initialized()
        affected = 0
        # Semantic memory uses a gentler decay (square root of factor)
        gentle_factor = math.sqrt(factor)
        for entry in self._entries.values():
            old_importance = entry.importance
            entry.importance = max(0.0, entry.importance * gentle_factor)
            if entry.importance != old_importance:
                affected += 1
        return affected

    async def health_check(
        self,
        security_context: SecurityContext,
    ) -> dict[str, Any]:
        """
        Check the health of the semantic memory tier.

        Args:
            security_context: Security context for the operation.

        Returns:
            Dictionary with health information.

        Example:
            ```python
            health = await tier.health_check(security_context)
            ```
        """
        entries_with_embeddings = sum(
            1 for entry in self._entries.values() if entry.content.embedding is not None
        )
        return {
            "status": "healthy" if self._initialized else "not_initialized",
            "tier": self.tier.value,
            "entry_count": len(self._entries),
            "max_entries": self._max_entries,
            "entries_with_embeddings": entries_with_embeddings,
            "utilization": (
                len(self._entries) / self._max_entries if self._max_entries > 0 else 0.0
            ),
        }

    @staticmethod
    def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
        """
        Compute cosine similarity between two vectors.

        Args:
            vec_a: First vector.
            vec_b: Second vector.

        Returns:
            Cosine similarity score between -1.0 and 1.0.
            Returns 0.0 if either vector has zero magnitude.
        """
        if len(vec_a) != len(vec_b):
            return 0.0

        dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
        magnitude_a = math.sqrt(sum(a * a for a in vec_a))
        magnitude_b = math.sqrt(sum(b * b for b in vec_b))

        if magnitude_a == 0.0 or magnitude_b == 0.0:
            return 0.0

        return dot_product / (magnitude_a * magnitude_b)

    @staticmethod
    def _compute_text_score(query_lower: str, entry: MemoryEntry) -> float:
        """
        Compute a simple text relevance score.

        Args:
            query_lower: Lowercased query string.
            entry: Memory entry to score.

        Returns:
            Relevance score between 0.0 and 1.0.
        """
        if not query_lower:
            return entry.importance

        content_lower = entry.content.content.lower()
        if query_lower in content_lower:
            return 0.8 + (0.2 * entry.importance)

        query_words = set(query_lower.split())
        content_words = set(content_lower.split())
        overlap = query_words & content_words
        if overlap:
            return (len(overlap) / len(query_words)) * 0.6 + (0.2 * entry.importance)

        return 0.0

    @staticmethod
    def _matches_filters(entry: MemoryEntry, filters: SearchFilter) -> bool:
        """
        Check if an entry matches the given filters.

        Args:
            entry: Memory entry to check.
            filters: Filter criteria.

        Returns:
            True if the entry matches all applicable filters.
        """
        if filters.tiers and entry.tier not in filters.tiers:
            return False
        if filters.scopes and entry.scope not in filters.scopes:
            return False
        if filters.tags and not any(tag in entry.tags for tag in filters.tags):
            return False
        if filters.min_importance is not None and entry.importance < filters.min_importance:
            return False
        if filters.since and entry.created_at < filters.since:
            return False
        if filters.until and entry.created_at > filters.until:
            return False
        if filters.content_type and entry.content.content_type != filters.content_type:
            return False
        return True
