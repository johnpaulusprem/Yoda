"""
Working memory tier for the Agentic AI Component Library.

Short-lived, auto-expiring memory tier for active task context and
reasoning state. Enforces a maximum capacity and automatically
removes expired entries.

Example:
    ```python
    from yoda_foundation.memory.tiers import WorkingMemoryTier

    tier = WorkingMemoryTier(config={"max_capacity": 50, "default_ttl_seconds": 300})
    await tier.initialize(security_context)

    result = await tier.store(entry, security_context)
    ```
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

from yoda_foundation.exceptions.memory import (
    MemoryCapacityError,
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


class WorkingMemoryTier(BaseTier):
    """
    In-memory working memory tier with capacity limits and auto-expiry.

    Working memory is designed for short-lived task context. Entries
    automatically expire after a configurable TTL, and the tier enforces
    a maximum capacity, evicting the oldest entries when full.

    Attributes:
        tier: Always MemoryTier.WORKING.
        config: Configuration with keys:
            - max_capacity (int): Maximum entries (default 100).
            - default_ttl_seconds (int): Default TTL in seconds (default 300).

    Example:
        ```python
        tier = WorkingMemoryTier(config={"max_capacity": 50})
        await tier.initialize(security_context)

        entry = MemoryEntry.create(
            tier=MemoryTier.WORKING,
            scope=MemoryScope.SESSION,
            content=MemoryContent(content="Current reasoning step"),
        )
        result = await tier.store(entry, security_context)
        ```

    Raises:
        MemoryCapacityError: When max capacity is reached.
        MemoryStorageError: When store operations fail.
        MemoryNotFoundError: When an entry ID is not found.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """
        Initialize the working memory tier.

        Args:
            config: Optional configuration dictionary. Supported keys:
                - max_capacity (int): Maximum number of entries (default 100).
                - default_ttl_seconds (int): Default TTL for entries (default 300).

        Example:
            ```python
            tier = WorkingMemoryTier(config={"max_capacity": 50})
            ```
        """
        super().__init__(tier=MemoryTier.WORKING, config=config)
        self._entries: dict[str, MemoryEntry] = {}
        self._max_capacity: int = self.config.get("max_capacity", 100)
        self._default_ttl_seconds: int = self.config.get("default_ttl_seconds", 300)

    async def initialize(self, security_context: SecurityContext) -> None:
        """
        Initialize the working memory tier.

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
                message=f"Failed to initialize working memory tier: {e}",
                tier_name=self.tier.value,
                cause=e,
            ) from e

    async def close(self, security_context: SecurityContext) -> None:
        """
        Close the working memory tier and clear all entries.

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
        Store an entry in working memory.

        Automatically assigns a default TTL if the entry has no expiration.
        Evicts expired entries before checking capacity. Raises
        MemoryCapacityError if capacity is still exceeded after eviction.

        Args:
            entry: The memory entry to store.
            security_context: Security context for the operation.

        Returns:
            StoreResult indicating success.

        Raises:
            MemoryStorageError: If the store operation fails.
            MemoryCapacityError: If capacity is exceeded after eviction.

        Example:
            ```python
            result = await tier.store(entry, security_context)
            assert result.stored
            ```
        """
        self._ensure_initialized()
        try:
            # Apply default TTL if no expiration set
            if entry.expires_at is None:
                entry.expires_at = datetime.now(UTC) + timedelta(
                    seconds=self._default_ttl_seconds,
                )

            # Evict expired entries first
            await self._evict_expired()

            # Check capacity
            if len(self._entries) >= self._max_capacity:
                raise MemoryCapacityError(
                    message=(
                        f"Working memory capacity exceeded: "
                        f"{len(self._entries)}/{self._max_capacity}"
                    ),
                    memory_type=self.tier.value,
                    current_size=len(self._entries),
                    max_size=self._max_capacity,
                )

            self._entries[entry.id] = entry
            return StoreResult(
                entry_id=entry.id,
                tier=self.tier,
                stored=True,
                message="Stored in working memory",
            )
        except MemoryCapacityError:
            raise
        except (KeyError, TypeError, ValueError) as e:
            raise MemoryStorageError(
                message=f"Failed to store entry in working memory: {e}",
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
        Retrieve an entry by ID from working memory.

        Checks expiration before returning. Expired entries are removed
        and treated as not found.

        Args:
            entry_id: Unique identifier of the entry.
            security_context: Security context for the operation.

        Returns:
            The requested MemoryEntry.

        Raises:
            MemoryNotFoundError: If the entry does not exist or has expired.

        Example:
            ```python
            entry = await tier.get("mem_abc123", security_context)
            ```
        """
        self._ensure_initialized()
        entry = self._entries.get(entry_id)
        if entry is None:
            raise MemoryNotFoundError(
                message=f"Entry '{entry_id}' not found in working memory",
                memory_type=self.tier.value,
                entry_id=entry_id,
            )

        if entry.is_expired():
            del self._entries[entry_id]
            raise MemoryNotFoundError(
                message=f"Entry '{entry_id}' has expired in working memory",
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
        Update the content of an existing working memory entry.

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
                message=f"Entry '{entry_id}' not found in working memory",
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
        Delete an entry from working memory.

        Args:
            entry_id: ID of the entry to delete.
            security_context: Security context for the operation.

        Returns:
            True if the entry was deleted, False if not found.

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
        Search working memory using substring matching.

        Args:
            query: Text query to match against entry content.
            filters: Additional filter criteria.
            security_context: Security context for the operation.

        Returns:
            SearchResult with matching entries and relevance scores.

        Raises:
            MemoryRetrievalError: If the search operation fails.

        Example:
            ```python
            result = await tier.search("task context", filters, security_context)
            ```
        """
        self._ensure_initialized()
        try:
            start_ms = int(time.monotonic() * 1000)
            await self._evict_expired()

            matched: list[tuple[MemoryEntry, float]] = []
            query_lower = query.lower()

            for entry in self._entries.values():
                if not self._matches_filters(entry, filters):
                    continue

                score = self._compute_text_score(query_lower, entry)
                if score > 0.0 or not query:
                    matched.append((entry, score))

            # Sort by score descending
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
                message=f"Search failed in working memory: {e}",
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
        Count entries in working memory.

        Args:
            security_context: Security context for the operation.
            filters: Optional filter criteria.

        Returns:
            Number of matching non-expired entries.

        Example:
            ```python
            total = await tier.count(security_context)
            ```
        """
        self._ensure_initialized()
        await self._evict_expired()

        if filters is None:
            return len(self._entries)

        return sum(1 for entry in self._entries.values() if self._matches_filters(entry, filters))

    async def decay(
        self,
        factor: float,
        security_context: SecurityContext,
    ) -> int:
        """
        Apply decay to working memory entries by reducing importance.

        Args:
            factor: Decay factor (0.0-1.0). Importance is multiplied by this.
            security_context: Security context for the operation.

        Returns:
            Number of entries affected.

        Example:
            ```python
            affected = await tier.decay(0.9, security_context)
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
        Check the health of the working memory tier.

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
            "max_capacity": self._max_capacity,
            "utilization": len(self._entries) / self._max_capacity
            if self._max_capacity > 0
            else 0.0,
        }

    async def _evict_expired(self) -> None:
        """Remove all expired entries from working memory."""
        expired_ids = [entry_id for entry_id, entry in self._entries.items() if entry.is_expired()]
        for entry_id in expired_ids:
            del self._entries[entry_id]

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
            # Exact substring match gets high score, weighted by importance
            return 0.8 + (0.2 * entry.importance)

        # Check word overlap
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
