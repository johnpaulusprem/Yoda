"""
Abstract base class for memory tiers in the Agentic AI Component Library.

This module defines the interface that all memory tier backends must implement.
Each tier (Working, Episodic, Semantic, Procedural) extends this base class
with tier-specific behavior.

Example:
    ```python
    from yoda_foundation.memory.base_tier import BaseTier
    from yoda_foundation.memory.schemas import MemoryTier

    class CustomTier(BaseTier):
        async def initialize(self, security_context: SecurityContext) -> None:
            self._initialized = True

        async def store(
            self,
            entry: MemoryEntry,
            security_context: SecurityContext,
        ) -> StoreResult:
            ...
    ```
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from yoda_foundation.exceptions.memory import MemoryTierError
from yoda_foundation.memory.schemas import (
    MemoryContent,
    MemoryEntry,
    MemoryTier,
    SearchFilter,
    SearchResult,
    StoreResult,
)
from yoda_foundation.security.context import SecurityContext


class BaseTier(ABC):
    """
    Abstract base class for all memory tier implementations.

    Defines the interface contract that every memory tier backend must
    satisfy. Concrete implementations store entries in-memory, in a
    database, or in a vector store.

    Attributes:
        tier: The memory tier this backend serves.
        config: Tier-specific configuration dictionary.

    Example:
        ```python
        class MyTier(BaseTier):
            async def initialize(self, security_context: SecurityContext) -> None:
                self._initialized = True

            async def store(
                self,
                entry: MemoryEntry,
                security_context: SecurityContext,
            ) -> StoreResult:
                self._entries[entry.id] = entry
                return StoreResult(
                    entry_id=entry.id,
                    tier=self.tier,
                    stored=True,
                )
        ```

    Raises:
        MemoryTierError: If tier operations fail or tier is not initialized.
    """

    def __init__(
        self,
        tier: MemoryTier,
        config: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize the base tier.

        Args:
            tier: The memory tier this backend serves.
            config: Optional tier-specific configuration.

        Example:
            ```python
            tier = MyTier(
                tier=MemoryTier.WORKING,
                config={"max_capacity": 100},
            )
            ```
        """
        self.tier = tier
        self.config = config or {}
        self._initialized = False

    @abstractmethod
    async def initialize(self, security_context: SecurityContext) -> None:
        """
        Initialize the tier backend and prepare for operations.

        Args:
            security_context: Security context for the operation.

        Raises:
            MemoryTierError: If initialization fails.

        Example:
            ```python
            await tier.initialize(security_context)
            ```
        """

    @abstractmethod
    async def close(self, security_context: SecurityContext) -> None:
        """
        Close the tier backend and release resources.

        Args:
            security_context: Security context for the operation.

        Raises:
            MemoryTierError: If closing fails.

        Example:
            ```python
            await tier.close(security_context)
            ```
        """

    @abstractmethod
    async def store(
        self,
        entry: MemoryEntry,
        security_context: SecurityContext,
    ) -> StoreResult:
        """
        Store a memory entry in this tier.

        Args:
            entry: The memory entry to store.
            security_context: Security context for the operation.

        Returns:
            StoreResult indicating success and the stored entry ID.

        Raises:
            MemoryStorageError: If the store operation fails.
            MemoryCapacityError: If tier capacity is exceeded.

        Example:
            ```python
            result = await tier.store(entry, security_context)
            assert result.stored
            ```
        """

    @abstractmethod
    async def get(
        self,
        entry_id: str,
        security_context: SecurityContext,
    ) -> MemoryEntry:
        """
        Retrieve a specific memory entry by ID.

        Args:
            entry_id: Unique identifier of the entry.
            security_context: Security context for the operation.

        Returns:
            The requested MemoryEntry.

        Raises:
            MemoryNotFoundError: If the entry does not exist.
            MemoryRetrievalError: If retrieval fails.

        Example:
            ```python
            entry = await tier.get("mem_abc123def456", security_context)
            ```
        """

    @abstractmethod
    async def update(
        self,
        entry_id: str,
        content: MemoryContent,
        security_context: SecurityContext,
    ) -> MemoryEntry:
        """
        Update the content of an existing memory entry.

        Args:
            entry_id: ID of the entry to update.
            content: New content to replace the existing content.
            security_context: Security context for the operation.

        Returns:
            The updated MemoryEntry.

        Raises:
            MemoryNotFoundError: If the entry does not exist.
            MemoryStorageError: If the update fails.

        Example:
            ```python
            updated = await tier.update(
                "mem_abc123", new_content, security_context,
            )
            ```
        """

    @abstractmethod
    async def delete(
        self,
        entry_id: str,
        security_context: SecurityContext,
    ) -> bool:
        """
        Delete a memory entry from this tier.

        Args:
            entry_id: ID of the entry to delete.
            security_context: Security context for the operation.

        Returns:
            True if the entry was deleted, False if not found.

        Raises:
            MemoryStorageError: If the delete operation fails.

        Example:
            ```python
            deleted = await tier.delete("mem_abc123", security_context)
            ```
        """

    @abstractmethod
    async def search(
        self,
        query: str,
        filters: SearchFilter,
        security_context: SecurityContext,
    ) -> SearchResult:
        """
        Search for memory entries matching a query and filters.

        Args:
            query: Text query for matching.
            filters: Additional filter criteria.
            security_context: Security context for the operation.

        Returns:
            SearchResult with matching entries and scores.

        Raises:
            MemoryRetrievalError: If the search fails.

        Example:
            ```python
            result = await tier.search(
                "user preferences", SearchFilter(limit=5), security_context,
            )
            ```
        """

    @abstractmethod
    async def count(
        self,
        security_context: SecurityContext,
        filters: SearchFilter | None = None,
    ) -> int:
        """
        Count entries in this tier, optionally filtered.

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

    @abstractmethod
    async def decay(
        self,
        factor: float,
        security_context: SecurityContext,
    ) -> int:
        """
        Apply decay to all entries in this tier.

        Reduces importance scores by the given factor. Entries whose
        importance drops below a threshold may be candidates for pruning.

        Args:
            factor: Decay factor (0.0-1.0). Lower values mean faster decay.
            security_context: Security context for the operation.

        Returns:
            Number of entries affected by decay.

        Raises:
            MemoryDecayError: If the decay operation fails.

        Example:
            ```python
            affected = await tier.decay(0.95, security_context)
            ```
        """

    @abstractmethod
    async def health_check(
        self,
        security_context: SecurityContext,
    ) -> dict[str, Any]:
        """
        Check the health status of this tier backend.

        Args:
            security_context: Security context for the operation.

        Returns:
            Dictionary with health status information.

        Example:
            ```python
            health = await tier.health_check(security_context)
            assert health["status"] == "healthy"
            ```
        """

    def _ensure_initialized(self) -> None:
        """
        Verify the tier has been initialized before operations.

        Raises:
            MemoryTierError: If the tier has not been initialized.

        Example:
            ```python
            self._ensure_initialized()
            # Safe to proceed with operations
            ```
        """
        if not self._initialized:
            raise MemoryTierError(
                message=f"Memory tier '{self.tier.value}' is not initialized",
                tier_name=self.tier.value,
            )
