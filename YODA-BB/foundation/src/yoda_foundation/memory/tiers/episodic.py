"""
Episodic memory tier for the Agentic AI Component Library.

Event and episode-based memory tier that stores time-ordered experiences.
Supports temporal queries for retrieving memories by time range and
provides chronological ordering of events.

Example:
    ```python
    from yoda_foundation.memory.tiers import EpisodicMemoryTier

    tier = EpisodicMemoryTier()
    await tier.initialize(security_context)

    entry = MemoryEntry.create(
        tier=MemoryTier.EPISODIC,
        scope=MemoryScope.USER,
        content=MemoryContent(content="Completed research task successfully"),
        tags=["task", "research"],
    )
    result = await tier.store(entry, security_context)
    ```
"""

from __future__ import annotations

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


class EpisodicMemoryTier(BaseTier):
    """
    In-memory episodic memory tier for event/episode storage.

    Episodic memory stores time-ordered experiences and events. It supports
    temporal queries, allowing retrieval of memories within specific time
    ranges. Entries are naturally ordered by creation time.

    Attributes:
        tier: Always MemoryTier.EPISODIC.
        config: Configuration with keys:
            - max_episodes (int): Maximum stored episodes (default 10000).

    Example:
        ```python
        tier = EpisodicMemoryTier(config={"max_episodes": 5000})
        await tier.initialize(security_context)

        # Store an episode
        entry = MemoryEntry.create(
            tier=MemoryTier.EPISODIC,
            scope=MemoryScope.USER,
            content=MemoryContent(content="User asked about Python best practices"),
            importance=0.7,
            tags=["conversation", "python"],
        )
        await tier.store(entry, security_context)

        # Search by time range
        filters = SearchFilter(since=one_hour_ago, limit=20)
        result = await tier.search("python", filters, security_context)
        ```

    Raises:
        MemoryStorageError: When store operations fail.
        MemoryNotFoundError: When an entry ID is not found.
        MemoryRetrievalError: When search operations fail.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """
        Initialize the episodic memory tier.

        Args:
            config: Optional configuration dictionary. Supported keys:
                - max_episodes (int): Maximum stored episodes (default 10000).

        Example:
            ```python
            tier = EpisodicMemoryTier(config={"max_episodes": 5000})
            ```
        """
        super().__init__(tier=MemoryTier.EPISODIC, config=config)
        self._entries: dict[str, MemoryEntry] = {}
        self._max_episodes: int = self.config.get("max_episodes", 10000)

    async def initialize(self, security_context: SecurityContext) -> None:
        """
        Initialize the episodic memory tier.

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
                message=f"Failed to initialize episodic memory tier: {e}",
                tier_name=self.tier.value,
                cause=e,
            ) from e

    async def close(self, security_context: SecurityContext) -> None:
        """
        Close the episodic memory tier and clear entries.

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
        Store an episode in episodic memory.

        Enforces max_episodes capacity. When capacity is reached, the oldest
        episode (by creation time) is evicted.

        Args:
            entry: The memory entry to store.
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
            # Evict oldest if at capacity
            if len(self._entries) >= self._max_episodes:
                oldest_id = min(
                    self._entries,
                    key=lambda eid: self._entries[eid].created_at,
                )
                del self._entries[oldest_id]

            self._entries[entry.id] = entry
            return StoreResult(
                entry_id=entry.id,
                tier=self.tier,
                stored=True,
                message="Stored in episodic memory",
            )
        except (KeyError, TypeError, ValueError) as e:
            raise MemoryStorageError(
                message=f"Failed to store entry in episodic memory: {e}",
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
        Retrieve an episode by ID.

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
                message=f"Entry '{entry_id}' not found in episodic memory",
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
        Update the content of an existing episodic memory entry.

        Args:
            entry_id: ID of the entry to update.
            content: New content to replace the existing content.
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
                message=f"Entry '{entry_id}' not found in episodic memory",
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
        Delete an episode from episodic memory.

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
        Search episodic memory with temporal ordering.

        Results are scored by a combination of text relevance and temporal
        recency. More recent episodes receive a recency bonus.

        Args:
            query: Text query to match against entry content.
            filters: Additional filter criteria (supports since/until for
                temporal queries).
            security_context: Security context for the operation.

        Returns:
            SearchResult with matching entries sorted by combined score.

        Raises:
            MemoryRetrievalError: If the search operation fails.

        Example:
            ```python
            from datetime import datetime, timedelta, UTC
            filters = SearchFilter(
                since=datetime.now(UTC) - timedelta(hours=1),
                limit=10,
            )
            result = await tier.search("python", filters, security_context)
            ```
        """
        self._ensure_initialized()
        try:
            start_ms = int(time.monotonic() * 1000)
            matched: list[tuple[MemoryEntry, float]] = []
            query_lower = query.lower()

            # Get time bounds for recency scoring
            entries_list = list(self._entries.values())
            if entries_list:
                min_ts = min(e.created_at.timestamp() for e in entries_list)
                max_ts = max(e.created_at.timestamp() for e in entries_list)
                time_range = max_ts - min_ts if max_ts > min_ts else 1.0
            else:
                min_ts = 0.0
                time_range = 1.0

            for entry in entries_list:
                if not self._matches_filters(entry, filters):
                    continue

                text_score = self._compute_text_score(query_lower, entry)
                recency_score = (entry.created_at.timestamp() - min_ts) / time_range

                # Weighted combination: 60% text, 40% recency
                combined = (0.6 * text_score) + (0.4 * recency_score)

                if combined > 0.0 or not query:
                    matched.append((entry, combined))

            # Sort by score descending, then by time (newest first)
            matched.sort(
                key=lambda pair: (pair[1], pair[0].created_at.timestamp()),
                reverse=True,
            )

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
                message=f"Search failed in episodic memory: {e}",
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
        Count episodes in episodic memory.

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
        Apply decay to episodic memory entries.

        Args:
            factor: Decay factor (0.0-1.0). Importance is multiplied by this.
            security_context: Security context for the operation.

        Returns:
            Number of entries affected.

        Example:
            ```python
            affected = await tier.decay(0.95, security_context)
            ```
        """
        self._ensure_initialized()
        affected = 0
        for entry in self._entries.values():
            old_importance = entry.importance
            entry.importance = max(0.0, entry.importance * factor)
            if entry.importance != old_importance:
                affected += 1
        return affected

    async def health_check(
        self,
        security_context: SecurityContext,
    ) -> dict[str, Any]:
        """
        Check the health of the episodic memory tier.

        Args:
            security_context: Security context for the operation.

        Returns:
            Dictionary with health information.

        Example:
            ```python
            health = await tier.health_check(security_context)
            ```
        """
        return {
            "status": "healthy" if self._initialized else "not_initialized",
            "tier": self.tier.value,
            "entry_count": len(self._entries),
            "max_episodes": self._max_episodes,
            "utilization": (
                len(self._entries) / self._max_episodes if self._max_episodes > 0 else 0.0
            ),
        }

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
