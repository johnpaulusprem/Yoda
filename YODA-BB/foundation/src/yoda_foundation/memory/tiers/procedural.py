"""
Procedural memory tier for the Agentic AI Component Library.

Skill and procedure storage tier that supports pattern matching by tags.
Stores learned procedures, workflows, and behavioral patterns that
agents can retrieve and execute.

Example:
    ```python
    from yoda_foundation.memory.tiers import ProceduralMemoryTier

    tier = ProceduralMemoryTier()
    await tier.initialize(security_context)

    entry = MemoryEntry.create(
        tier=MemoryTier.PROCEDURAL,
        scope=MemoryScope.GLOBAL,
        content=MemoryContent(
            content="Step 1: Parse input. Step 2: Validate. Step 3: Execute.",
            content_type="procedure",
        ),
        tags=["data_processing", "etl"],
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


class ProceduralMemoryTier(BaseTier):
    """
    In-memory procedural memory tier for skill and procedure storage.

    Procedural memory stores learned procedures, skills, and behavioral
    patterns. It supports tag-based pattern matching for efficient
    retrieval of relevant procedures. Tags serve as the primary index
    for procedure lookup.

    Attributes:
        tier: Always MemoryTier.PROCEDURAL.
        config: Configuration with keys:
            - max_procedures (int): Maximum stored procedures (default 10000).

    Example:
        ```python
        tier = ProceduralMemoryTier(config={"max_procedures": 5000})
        await tier.initialize(security_context)

        # Store a procedure
        entry = MemoryEntry.create(
            tier=MemoryTier.PROCEDURAL,
            scope=MemoryScope.GLOBAL,
            content=MemoryContent(
                content="To summarize a document: 1) Extract key points...",
                content_type="procedure",
            ),
            tags=["summarization", "nlp"],
            importance=0.9,
        )
        await tier.store(entry, security_context)

        # Search by tags
        filters = SearchFilter(tags=["summarization"], limit=5)
        result = await tier.search("summarize", filters, security_context)
        ```

    Raises:
        MemoryStorageError: When store operations fail.
        MemoryNotFoundError: When an entry ID is not found.
        MemoryRetrievalError: When search operations fail.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """
        Initialize the procedural memory tier.

        Args:
            config: Optional configuration dictionary. Supported keys:
                - max_procedures (int): Maximum stored procedures (default 10000).

        Example:
            ```python
            tier = ProceduralMemoryTier(config={"max_procedures": 5000})
            ```
        """
        super().__init__(tier=MemoryTier.PROCEDURAL, config=config)
        self._entries: dict[str, MemoryEntry] = {}
        self._max_procedures: int = self.config.get("max_procedures", 10000)
        # Tag index: tag -> set of entry IDs
        self._tag_index: dict[str, set[str]] = {}

    async def initialize(self, security_context: SecurityContext) -> None:
        """
        Initialize the procedural memory tier.

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
            self._tag_index = {}
            self._initialized = True
        except (OSError, RuntimeError) as e:
            raise MemoryTierError(
                message=f"Failed to initialize procedural memory tier: {e}",
                tier_name=self.tier.value,
                cause=e,
            ) from e

    async def close(self, security_context: SecurityContext) -> None:
        """
        Close the procedural memory tier and clear entries.

        Args:
            security_context: Security context for the operation.

        Example:
            ```python
            await tier.close(security_context)
            ```
        """
        self._entries.clear()
        self._tag_index.clear()
        self._initialized = False

    async def store(
        self,
        entry: MemoryEntry,
        security_context: SecurityContext,
    ) -> StoreResult:
        """
        Store a procedure in procedural memory.

        Updates the tag index for efficient tag-based lookups. Evicts
        the least important procedure when at capacity.

        Args:
            entry: The memory entry to store (should have descriptive tags).
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
            # Evict least important if at capacity
            if len(self._entries) >= self._max_procedures:
                least_important_id = min(
                    self._entries,
                    key=lambda eid: self._entries[eid].importance,
                )
                self._remove_from_tag_index(least_important_id)
                del self._entries[least_important_id]

            self._entries[entry.id] = entry
            self._add_to_tag_index(entry)

            return StoreResult(
                entry_id=entry.id,
                tier=self.tier,
                stored=True,
                message="Stored in procedural memory",
            )
        except (KeyError, TypeError, ValueError) as e:
            raise MemoryStorageError(
                message=f"Failed to store entry in procedural memory: {e}",
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
        Retrieve a procedure by ID.

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
                message=f"Entry '{entry_id}' not found in procedural memory",
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
        Update the content of an existing procedure.

        Args:
            entry_id: ID of the entry to update.
            content: New content for the procedure.
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
                message=f"Entry '{entry_id}' not found in procedural memory",
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
        Delete a procedure from procedural memory.

        Also removes the entry from the tag index.

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
            self._remove_from_tag_index(entry_id)
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
        Search procedural memory using tag-based pattern matching and text.

        Scoring prioritizes tag matches, then text content relevance.
        When filters include tags, only entries matching at least one
        tag are considered as candidates, leveraging the tag index.

        Args:
            query: Text query for content matching.
            filters: Filter criteria (tags are especially relevant here).
            security_context: Security context for the operation.

        Returns:
            SearchResult with matching procedures sorted by relevance.

        Raises:
            MemoryRetrievalError: If the search fails.

        Example:
            ```python
            filters = SearchFilter(tags=["nlp", "summarization"], limit=5)
            result = await tier.search("summarize documents", filters, security_context)
            ```
        """
        self._ensure_initialized()
        try:
            start_ms = int(time.monotonic() * 1000)
            matched: list[tuple[MemoryEntry, float]] = []
            query_lower = query.lower()

            # Determine candidate set
            if filters.tags:
                # Use tag index for fast lookup
                candidate_ids: set[str] = set()
                for tag in filters.tags:
                    candidate_ids |= self._tag_index.get(tag, set())
                candidates = [self._entries[eid] for eid in candidate_ids if eid in self._entries]
            else:
                candidates = list(self._entries.values())

            for entry in candidates:
                if not self._matches_filters(entry, filters):
                    continue

                # Compute score with tag bonus
                text_score = self._compute_text_score(query_lower, entry)
                tag_score = self._compute_tag_score(query_lower, entry)

                # Weighted: 40% text, 40% tag, 20% importance
                combined = 0.4 * text_score + 0.4 * tag_score + 0.2 * entry.importance

                if combined > 0.0 or not query:
                    matched.append((entry, combined))

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
                message=f"Search failed in procedural memory: {e}",
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
        Count entries in procedural memory.

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
        Apply decay to procedural memory entries.

        Procedural memory decays very slowly since skills are durable.
        Frequently accessed procedures resist decay.

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
        for entry in self._entries.values():
            old_importance = entry.importance
            # Frequently accessed procedures resist decay
            access_bonus = min(0.1, entry.access_count * 0.01)
            adjusted_factor = min(1.0, factor + access_bonus)
            entry.importance = max(0.0, entry.importance * adjusted_factor)
            if entry.importance != old_importance:
                affected += 1
        return affected

    async def health_check(
        self,
        security_context: SecurityContext,
    ) -> dict[str, Any]:
        """
        Check the health of the procedural memory tier.

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
            "max_procedures": self._max_procedures,
            "unique_tags": len(self._tag_index),
            "utilization": (
                len(self._entries) / self._max_procedures if self._max_procedures > 0 else 0.0
            ),
        }

    def _add_to_tag_index(self, entry: MemoryEntry) -> None:
        """
        Add an entry's tags to the tag index.

        Args:
            entry: Memory entry whose tags to index.
        """
        for tag in entry.tags:
            if tag not in self._tag_index:
                self._tag_index[tag] = set()
            self._tag_index[tag].add(entry.id)

    def _remove_from_tag_index(self, entry_id: str) -> None:
        """
        Remove an entry from the tag index.

        Args:
            entry_id: ID of the entry to remove from index.
        """
        entry = self._entries.get(entry_id)
        if entry is None:
            return
        for tag in entry.tags:
            tag_set = self._tag_index.get(tag)
            if tag_set is not None:
                tag_set.discard(entry_id)
                if not tag_set:
                    del self._tag_index[tag]

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
    def _compute_tag_score(query_lower: str, entry: MemoryEntry) -> float:
        """
        Compute a tag-based relevance score.

        Tags that overlap with the query words receive a higher score.

        Args:
            query_lower: Lowercased query string.
            entry: Memory entry to score.

        Returns:
            Tag relevance score between 0.0 and 1.0.
        """
        if not entry.tags:
            return 0.0

        query_words = set(query_lower.split())
        tag_words: set[str] = set()
        for tag in entry.tags:
            tag_words.update(tag.lower().split("_"))
            tag_words.update(tag.lower().split("-"))
            tag_words.add(tag.lower())

        overlap = query_words & tag_words
        if not overlap:
            return 0.0

        return len(overlap) / max(len(query_words), 1)

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
