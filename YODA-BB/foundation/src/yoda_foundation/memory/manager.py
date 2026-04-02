"""
Memory manager for the Agentic AI Component Library.

Orchestrates all memory tiers, providing a unified interface for storing,
retrieving, searching, consolidating, and managing memory entries across
Working, Episodic, Semantic, and Procedural tiers.

Example:
    ```python
    from yoda_foundation.memory.manager import MemoryManager
    from yoda_foundation.memory.schemas import MemoryTier
    from yoda_foundation.memory.tiers import (
        WorkingMemoryTier,
        EpisodicMemoryTier,
        SemanticMemoryTier,
        ProceduralMemoryTier,
    )

    manager = MemoryManager(
        tiers={
            MemoryTier.WORKING: WorkingMemoryTier(),
            MemoryTier.EPISODIC: EpisodicMemoryTier(),
            MemoryTier.SEMANTIC: SemanticMemoryTier(),
            MemoryTier.PROCEDURAL: ProceduralMemoryTier(),
        },
    )
    await manager.initialize(security_context)
    ```
"""

from __future__ import annotations

from datetime import datetime

from yoda_foundation.exceptions.memory import (
    MemoryRetrievalError,
    MemoryStorageError,
    MemoryTierError,
)
from yoda_foundation.memory.base_tier import BaseTier
from yoda_foundation.memory.consolidation import (
    ConsolidationEngine,
    EmbeddingClient,
    LLMClient,
)
from yoda_foundation.memory.context import ContextBuilder, ContextConfig
from yoda_foundation.memory.decay import DecayManager, DecayStrategy
from yoda_foundation.memory.schemas import (
    ConsolidationResult,
    ConsolidationStrategy,
    ContextResult,
    MemoryContent,
    MemoryEntry,
    MemoryScope,
    MemoryStats,
    MemoryTier,
    SearchFilter,
    SearchResult,
    StoreResult,
)
from yoda_foundation.security.context import SecurityContext


class MemoryManager:
    """
    Central orchestrator for the multi-tier memory system.

    Provides a unified API for all memory operations across multiple
    tiers. Coordinates context building, consolidation, and decay
    management.

    Attributes:
        _tiers: Mapping of memory tiers to their backends.
        _context_builder: Context builder for assembling memory context.
        _decay_manager: Decay manager for importance decay operations.
        _consolidation_engine: Engine for consolidating memory entries.

    Example:
        ```python
        manager = MemoryManager(
            tiers={
                MemoryTier.WORKING: WorkingMemoryTier(),
                MemoryTier.SEMANTIC: SemanticMemoryTier(),
            },
            context_config=ContextConfig(max_tokens=8192),
        )
        await manager.initialize(security_context)

        # Store an entry
        entry = MemoryEntry.create(
            tier=MemoryTier.WORKING,
            scope=MemoryScope.SESSION,
            content=MemoryContent(content="Current task context"),
        )
        result = await manager.store(entry, security_context)

        # Search across tiers
        results = await manager.search(
            "task context", SearchFilter(limit=10), security_context,
        )
        ```

    Raises:
        MemoryTierError: When a requested tier is not registered.
        MemoryStorageError: When store operations fail.
        MemoryRetrievalError: When search/get operations fail.
        MemoryNotFoundError: When an entry is not found.
    """

    def __init__(
        self,
        tiers: dict[MemoryTier, BaseTier] | None = None,
        context_config: ContextConfig | None = None,
        decay_strategy: DecayStrategy | None = None,
    ) -> None:
        """
        Initialize the memory manager.

        Args:
            tiers: Mapping of memory tiers to their backend implementations.
            context_config: Configuration for the context builder.
            decay_strategy: Strategy for memory decay.

        Example:
            ```python
            manager = MemoryManager(
                tiers={MemoryTier.WORKING: WorkingMemoryTier()},
            )
            ```
        """
        self._tiers: dict[MemoryTier, BaseTier] = tiers or {}
        self._context_builder = ContextBuilder(context_config)
        self._decay_manager = DecayManager(decay_strategy)
        self._consolidation_engine = ConsolidationEngine()

    async def initialize(self, security_context: SecurityContext) -> None:
        """
        Initialize all registered memory tiers.

        Args:
            security_context: Security context for the operation.

        Raises:
            MemoryTierError: If any tier fails to initialize.

        Example:
            ```python
            await manager.initialize(security_context)
            ```
        """
        for tier_type, tier_backend in self._tiers.items():
            try:
                await tier_backend.initialize(security_context)
            except MemoryTierError:
                raise
            except (OSError, RuntimeError) as e:
                raise MemoryTierError(
                    message=f"Failed to initialize tier '{tier_type.value}': {e}",
                    tier_name=tier_type.value,
                    cause=e,
                ) from e

    async def close(self, security_context: SecurityContext) -> None:
        """
        Close all registered memory tiers and release resources.

        Args:
            security_context: Security context for the operation.

        Example:
            ```python
            await manager.close(security_context)
            ```
        """
        for tier_backend in self._tiers.values():
            await tier_backend.close(security_context)

    async def store(
        self,
        entry: MemoryEntry,
        security_context: SecurityContext,
    ) -> StoreResult:
        """
        Store a memory entry in the appropriate tier.

        Routes the entry to the tier specified by entry.tier.

        Args:
            entry: The memory entry to store.
            security_context: Security context for the operation.

        Returns:
            StoreResult indicating success.

        Raises:
            MemoryTierError: If the entry's tier is not registered.
            MemoryStorageError: If the store operation fails.

        Example:
            ```python
            entry = MemoryEntry.create(
                tier=MemoryTier.SEMANTIC,
                scope=MemoryScope.USER,
                content=MemoryContent(content="Python is dynamically typed"),
            )
            result = await manager.store(entry, security_context)
            ```
        """
        tier_backend = self._get_tier(entry.tier)
        return await tier_backend.store(entry, security_context)

    async def batch_store(
        self,
        entries: list[MemoryEntry],
        security_context: SecurityContext,
    ) -> list[StoreResult]:
        """
        Store multiple memory entries, routing each to its tier.

        Args:
            entries: List of memory entries to store.
            security_context: Security context for the operation.

        Returns:
            List of StoreResults, one per entry.

        Raises:
            MemoryTierError: If any entry's tier is not registered.
            MemoryStorageError: If any store operation fails.

        Example:
            ```python
            results = await manager.batch_store(entries, security_context)
            stored_count = sum(1 for r in results if r.stored)
            ```
        """
        results: list[StoreResult] = []
        for entry in entries:
            try:
                result = await self.store(entry, security_context)
                results.append(result)
            except (MemoryStorageError, MemoryTierError) as e:
                results.append(
                    StoreResult(
                        entry_id=entry.id,
                        tier=entry.tier,
                        stored=False,
                        message=str(e),
                    )
                )
        return results

    async def get(
        self,
        entry_id: str,
        tier: MemoryTier,
        security_context: SecurityContext,
    ) -> MemoryEntry:
        """
        Retrieve a specific memory entry by ID and tier.

        Args:
            entry_id: Unique identifier of the entry.
            tier: The memory tier to look in.
            security_context: Security context for the operation.

        Returns:
            The requested MemoryEntry.

        Raises:
            MemoryTierError: If the tier is not registered.
            MemoryNotFoundError: If the entry is not found.

        Example:
            ```python
            entry = await manager.get(
                "mem_abc123", MemoryTier.SEMANTIC, security_context,
            )
            ```
        """
        tier_backend = self._get_tier(tier)
        return await tier_backend.get(entry_id, security_context)

    async def search(
        self,
        query: str,
        filters: SearchFilter,
        security_context: SecurityContext,
    ) -> SearchResult:
        """
        Search across memory tiers.

        Searches all registered tiers (or only those specified in filters)
        and merges results sorted by score.

        Args:
            query: Text query for searching.
            filters: Filter criteria (tiers field controls which tiers
                to search).
            security_context: Security context for the operation.

        Returns:
            Merged SearchResult from all searched tiers.

        Raises:
            MemoryRetrievalError: If search fails.

        Example:
            ```python
            result = await manager.search(
                "user preferences",
                SearchFilter(tiers=[MemoryTier.SEMANTIC], limit=10),
                security_context,
            )
            ```
        """
        tiers_to_search = (
            [self._tiers[t] for t in filters.tiers if t in self._tiers]
            if filters.tiers
            else list(self._tiers.values())
        )

        if not tiers_to_search:
            return SearchResult(entries=[], scores=[], total_count=0, query_time_ms=0)

        all_entries: list[MemoryEntry] = []
        all_scores: list[float] = []
        total_count = 0
        max_query_time = 0

        for tier_backend in tiers_to_search:
            try:
                result = await tier_backend.search(query, filters, security_context)
                all_entries.extend(result.entries)
                all_scores.extend(result.scores)
                total_count += result.total_count
                max_query_time = max(max_query_time, result.query_time_ms)
            except MemoryRetrievalError:
                # Continue searching other tiers even if one fails
                continue

        # Sort merged results by score descending
        if all_entries:
            paired = list(zip(all_entries, all_scores))
            paired.sort(key=lambda pair: pair[1], reverse=True)

            limit = filters.limit if filters.limit else 10
            paired = paired[:limit]

            all_entries = [p[0] for p in paired]
            all_scores = [p[1] for p in paired]

        return SearchResult(
            entries=all_entries,
            scores=all_scores,
            total_count=total_count,
            query_time_ms=max_query_time,
        )

    async def update(
        self,
        entry_id: str,
        tier: MemoryTier,
        content: MemoryContent,
        security_context: SecurityContext,
    ) -> MemoryEntry:
        """
        Update the content of an existing memory entry.

        Args:
            entry_id: ID of the entry to update.
            tier: The memory tier the entry belongs to.
            content: New content to replace existing content.
            security_context: Security context for the operation.

        Returns:
            The updated MemoryEntry.

        Raises:
            MemoryTierError: If the tier is not registered.
            MemoryNotFoundError: If the entry is not found.

        Example:
            ```python
            updated = await manager.update(
                "mem_abc123",
                MemoryTier.SEMANTIC,
                MemoryContent(content="Updated knowledge"),
                security_context,
            )
            ```
        """
        tier_backend = self._get_tier(tier)
        return await tier_backend.update(entry_id, content, security_context)

    async def delete(
        self,
        entry_id: str,
        tier: MemoryTier,
        security_context: SecurityContext,
    ) -> bool:
        """
        Delete a memory entry.

        Args:
            entry_id: ID of the entry to delete.
            tier: The memory tier the entry belongs to.
            security_context: Security context for the operation.

        Returns:
            True if deleted, False if not found.

        Raises:
            MemoryTierError: If the tier is not registered.

        Example:
            ```python
            deleted = await manager.delete(
                "mem_abc123", MemoryTier.WORKING, security_context,
            )
            ```
        """
        tier_backend = self._get_tier(tier)
        return await tier_backend.delete(entry_id, security_context)

    async def batch_get(
        self,
        entry_ids: list[str],
        tier: MemoryTier,
        security_context: SecurityContext,
    ) -> list[MemoryEntry]:
        """
        Retrieve multiple memory entries by their IDs from a single tier.

        Entries that are not found are silently skipped.

        Args:
            entry_ids: List of entry IDs to retrieve.
            tier: The memory tier to look in.
            security_context: Security context for the operation.

        Returns:
            List of found MemoryEntry objects.

        Raises:
            MemoryTierError: If the tier is not registered.

        Example:
            ```python
            entries = await manager.batch_get(
                ["mem_1", "mem_2", "mem_3"],
                MemoryTier.SEMANTIC,
                security_context,
            )
            ```
        """
        tier_backend = self._get_tier(tier)
        results: list[MemoryEntry] = []
        for entry_id in entry_ids:
            try:
                entry = await tier_backend.get(entry_id, security_context)
                results.append(entry)
            except (MemoryRetrievalError, MemoryTierError):
                continue
        return results

    async def bulk_delete(
        self,
        entry_ids: list[str],
        tier: MemoryTier,
        security_context: SecurityContext,
    ) -> int:
        """
        Delete multiple memory entries by their IDs from a single tier.

        Args:
            entry_ids: List of entry IDs to delete.
            tier: The memory tier to delete from.
            security_context: Security context for the operation.

        Returns:
            Number of entries successfully deleted.

        Raises:
            MemoryTierError: If the tier is not registered.

        Example:
            ```python
            deleted = await manager.bulk_delete(
                ["mem_1", "mem_2"], MemoryTier.WORKING, security_context,
            )
            print(f"Deleted {deleted} entries")
            ```
        """
        tier_backend = self._get_tier(tier)
        deleted_count = 0
        for entry_id in entry_ids:
            try:
                was_deleted = await tier_backend.delete(entry_id, security_context)
                if was_deleted:
                    deleted_count += 1
            except (MemoryStorageError, MemoryTierError):
                continue
        return deleted_count

    async def consolidate(
        self,
        tier: MemoryTier,
        strategy: ConsolidationStrategy,
        security_context: SecurityContext,
    ) -> ConsolidationResult:
        """
        Consolidate memory entries in a specific tier.

        Retrieves all entries from the tier, consolidates them using
        the specified strategy, then replaces the tier's contents with
        the consolidated entries.

        Args:
            tier: The memory tier to consolidate.
            strategy: Consolidation strategy to apply.
            security_context: Security context for the operation.

        Returns:
            ConsolidationResult with consolidation details.

        Raises:
            MemoryTierError: If the tier is not registered.
            MemoryConsolidationError: If consolidation fails.

        Example:
            ```python
            result = await manager.consolidate(
                MemoryTier.EPISODIC,
                ConsolidationStrategy.SUMMARIZE,
                security_context,
            )
            ```
        """
        tier_backend = self._get_tier(tier)

        # Retrieve all entries from the tier
        all_filter = SearchFilter(limit=100000)
        search_result = await tier_backend.search("", all_filter, security_context)
        entries = search_result.entries

        if not entries:
            return ConsolidationResult(
                original_count=0,
                consolidated_count=0,
                strategy=strategy,
                entries=[],
                duration_ms=0,
            )

        result = await self._consolidation_engine.consolidate(
            entries,
            strategy,
            security_context,
        )

        # Replace tier contents with consolidated entries
        for entry in entries:
            await tier_backend.delete(entry.id, security_context)
        for consolidated_entry in result.entries:
            await tier_backend.store(consolidated_entry, security_context)

        return result

    async def get_context(
        self,
        query: str,
        security_context: SecurityContext,
        filters: SearchFilter | None = None,
    ) -> ContextResult:
        """
        Build context from memory for agent consumption.

        Searches relevant tiers and builds a context using the configured
        strategy, respecting token and entry limits.

        Args:
            query: The query to build context for.
            security_context: Security context for the operation.
            filters: Optional filters to narrow the search.

        Returns:
            ContextResult with selected entries and scores.

        Raises:
            MemoryContextError: If context building fails.

        Example:
            ```python
            context = await manager.get_context(
                "What are the pending tasks?", security_context,
            )
            for entry in context.entries:
                print(entry.content.content)
            ```
        """
        search_filters = filters or SearchFilter(limit=100)
        search_result = await self.search(query, search_filters, security_context)
        return await self._context_builder.build(
            query,
            search_result.entries,
            security_context,
        )

    async def clear_context(
        self,
        security_context: SecurityContext,
        tiers: list[MemoryTier] | None = None,
        scope: MemoryScope | None = None,
    ) -> int:
        """
        Clear memory entries, optionally filtered by tier and scope.

        When called with no filters, clears all working memory entries.
        Used to reset agent/session context.

        Args:
            security_context: Security context for the operation.
            tiers: Tiers to clear (defaults to WORKING only).
            scope: If set, only clear entries with this scope.

        Returns:
            Total number of entries deleted.

        Raises:
            MemoryTierError: If a requested tier is not registered.

        Example:
            ```python
            cleared = await manager.clear_context(
                security_context,
                tiers=[MemoryTier.WORKING],
                scope=MemoryScope.SESSION,
            )
            print(f"Cleared {cleared} entries")
            ```
        """
        target_tiers = tiers or [MemoryTier.WORKING]
        total_deleted = 0

        for tier_type in target_tiers:
            if tier_type not in self._tiers:
                continue
            tier_backend = self._tiers[tier_type]
            all_filter = SearchFilter(
                scopes=[scope] if scope else None,
                limit=100000,
            )
            try:
                result = await tier_backend.search("", all_filter, security_context)
                for entry in result.entries:
                    if scope is not None and entry.scope != scope:
                        continue
                    deleted = await tier_backend.delete(entry.id, security_context)
                    if deleted:
                        total_deleted += 1
            except (MemoryRetrievalError, MemoryTierError):
                continue

        return total_deleted

    async def get_stats(
        self,
        security_context: SecurityContext,
    ) -> MemoryStats:
        """
        Get statistics about the memory system.

        Aggregates statistics from all registered tiers.

        Args:
            security_context: Security context for the operation.

        Returns:
            MemoryStats with aggregate statistics.

        Example:
            ```python
            stats = await manager.get_stats(security_context)
            print(f"Total entries: {stats.total_entries}")
            ```
        """
        entries_by_tier: dict[MemoryTier, int] = {}
        entries_by_scope: dict[MemoryScope, int] = {}
        total_entries = 0
        total_tokens = 0
        oldest_entry: datetime | None = None
        newest_entry: datetime | None = None

        for tier_type, tier_backend in self._tiers.items():
            count = await tier_backend.count(security_context)
            entries_by_tier[tier_type] = count
            total_entries += count

            # Get entries to compute detailed stats
            all_filter = SearchFilter(limit=100000)
            try:
                result = await tier_backend.search("", all_filter, security_context)
                for entry in result.entries:
                    # Count by scope
                    entries_by_scope[entry.scope] = entries_by_scope.get(entry.scope, 0) + 1

                    # Token counts
                    total_tokens += entry.content.token_count or len(entry.content.content.split())

                    # Track time bounds
                    if oldest_entry is None or entry.created_at < oldest_entry:
                        oldest_entry = entry.created_at
                    if newest_entry is None or entry.created_at > newest_entry:
                        newest_entry = entry.created_at
            except MemoryRetrievalError:
                continue

        return MemoryStats(
            total_entries=total_entries,
            entries_by_tier=entries_by_tier,
            entries_by_scope=entries_by_scope,
            total_tokens=total_tokens,
            oldest_entry=oldest_entry,
            newest_entry=newest_entry,
        )

    async def apply_decay(
        self,
        security_context: SecurityContext,
    ) -> dict[MemoryTier, int]:
        """
        Apply decay to all entries across all tiers.

        Uses the configured decay strategy via the decay manager.

        Args:
            security_context: Security context for the operation.

        Returns:
            Dictionary mapping tiers to the number of affected entries.

        Example:
            ```python
            affected = await manager.apply_decay(security_context)
            for tier, count in affected.items():
                print(f"  {tier.value}: {count} entries decayed")
            ```
        """
        affected_by_tier: dict[MemoryTier, int] = {}

        for tier_type, tier_backend in self._tiers.items():
            all_filter = SearchFilter(limit=100000)
            try:
                result = await tier_backend.search("", all_filter, security_context)
                if result.entries:
                    decayed = await self._decay_manager.apply_decay(
                        result.entries,
                        security_context,
                    )
                    affected_by_tier[tier_type] = len(decayed)
                else:
                    affected_by_tier[tier_type] = 0
            except (MemoryRetrievalError, MemoryTierError):
                affected_by_tier[tier_type] = 0

        return affected_by_tier

    def register_tier(self, tier: MemoryTier, backend: BaseTier) -> None:
        """
        Register a memory tier backend.

        Args:
            tier: The memory tier to register.
            backend: The tier backend implementation.

        Example:
            ```python
            manager.register_tier(MemoryTier.WORKING, WorkingMemoryTier())
            ```
        """
        self._tiers[tier] = backend

    def set_embedding_client(self, client: EmbeddingClient) -> None:
        """
        Set the embedding client for the consolidation engine.

        Args:
            client: Embedding client implementation.

        Example:
            ```python
            manager.set_embedding_client(my_embedder)
            ```
        """
        self._consolidation_engine.embedding_client = client

    def set_llm_client(self, client: LLMClient) -> None:
        """
        Set the LLM client for the consolidation engine.

        Args:
            client: LLM client implementation.

        Example:
            ```python
            manager.set_llm_client(my_llm)
            ```
        """
        self._consolidation_engine.llm_client = client

    def _get_tier(self, tier: MemoryTier) -> BaseTier:
        """
        Get a registered tier backend.

        Args:
            tier: The memory tier to look up.

        Returns:
            The registered BaseTier backend.

        Raises:
            MemoryTierError: If the tier is not registered.
        """
        backend = self._tiers.get(tier)
        if backend is None:
            raise MemoryTierError(
                message=f"Memory tier '{tier.value}' is not registered",
                tier_name=tier.value,
            )
        return backend
