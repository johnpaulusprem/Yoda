"""
Memory-related exceptions for the Agentic AI Component Library.

This module provides exceptions specific to memory operations including
storage, retrieval, and management of agent memory.

Example:
    ```python
    from yoda_foundation.exceptions import (
        MemoryError,
        MemoryStorageError,
        MemoryRetrievalError,
    )

    try:
        await memory.store(entry)
    except MemoryStorageError as e:
        logger.error(f"Failed to store memory: {e.error_id}")
        raise
    ```
"""

from __future__ import annotations

from typing import Any

from yoda_foundation.exceptions.base import (
    AgenticBaseException,
    ErrorCategory,
    ErrorSeverity,
)


class MemoryError(AgenticBaseException):
    """
    Base exception for all memory-related errors.

    All memory exceptions inherit from this class.

    Attributes:
        memory_type: Type of memory (short_term, long_term, etc.)
        operation: The operation that failed
        memory_id: Optional memory entry ID

    Example:
        ```python
        raise MemoryError(
            message="Memory operation failed",
            memory_type="short_term",
            operation="store",
        )
        ```
    """

    def __init__(
        self,
        message: str,
        *,
        memory_type: str | None = None,
        operation: str | None = None,
        memory_id: str | None = None,
        retryable: bool = False,
        user_message: str | None = None,
        suggestions: list[str] | None = None,
        cause: Exception | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize memory error.

        Args:
            message: Error description
            memory_type: Type of memory
            operation: Operation that failed
            memory_id: Memory entry ID
            retryable: Whether operation can be retried
            user_message: User-safe message
            suggestions: Remediation suggestions
            cause: Original exception
            details: Additional context
        """
        details = details or {}
        if memory_type:
            details["memory_type"] = memory_type
        if operation:
            details["operation"] = operation
        if memory_id:
            details["memory_id"] = memory_id

        super().__init__(
            message=message,
            category=ErrorCategory.INTERNAL,
            severity=ErrorSeverity.MEDIUM,
            retryable=retryable,
            user_message=user_message or "Memory operation failed",
            suggestions=suggestions or ["Check memory system status", "Retry operation"],
            cause=cause,
            details=details,
        )

        self.memory_type = memory_type
        self.operation = operation
        self.memory_id = memory_id


class MemoryStorageError(MemoryError):
    """
    Exception raised when storing data to memory fails.

    Raised when attempting to persist memory entries fails due to
    storage issues, capacity limits, or serialization errors.

    Example:
        ```python
        try:
            await memory.store(entry)
        except MemoryStorageError as e:
            if e.retryable:
                await retry_with_backoff(memory.store, entry)
            else:
                logger.error(f"Permanent storage failure: {e}")
        ```
    """

    def __init__(
        self,
        message: str,
        *,
        memory_type: str | None = None,
        entry_id: str | None = None,
        capacity_reached: bool = False,
        cause: Exception | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize storage error.

        Args:
            message: Error description
            memory_type: Type of memory
            entry_id: Entry ID that failed to store
            capacity_reached: Whether storage capacity was reached
            cause: Original exception
            **kwargs: Additional error parameters
        """
        suggestions = kwargs.pop("suggestions", None) or []
        if capacity_reached:
            suggestions.extend(
                [
                    "Clear old memory entries",
                    "Increase memory capacity",
                    "Enable automatic pruning",
                ]
            )

        details = kwargs.pop("details", {})
        details["capacity_reached"] = capacity_reached
        if entry_id:
            details["entry_id"] = entry_id

        super().__init__(
            message=message,
            memory_type=memory_type,
            operation="store",
            retryable=not capacity_reached,
            user_message="Failed to save to memory",
            suggestions=suggestions,
            cause=cause,
            details=details,
            **kwargs,
        )

        self.entry_id = entry_id
        self.capacity_reached = capacity_reached


class MemoryRetrievalError(MemoryError):
    """
    Exception raised when retrieving data from memory fails.

    Raised when memory lookup, search, or access operations fail.

    Example:
        ```python
        try:
            entries = await memory.retrieve(query)
        except MemoryRetrievalError as e:
            logger.warning(f"Retrieval failed: {e}, using empty context")
            entries = []
        ```
    """

    def __init__(
        self,
        message: str,
        *,
        memory_type: str | None = None,
        query: str | None = None,
        cause: Exception | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize retrieval error.

        Args:
            message: Error description
            memory_type: Type of memory
            query: The query that failed
            cause: Original exception
            **kwargs: Additional error parameters
        """
        details = kwargs.pop("details", {})
        if query:
            details["query"] = query

        super().__init__(
            message=message,
            memory_type=memory_type,
            operation="retrieve",
            retryable=True,
            user_message="Failed to retrieve from memory",
            suggestions=[
                "Retry retrieval",
                "Check memory system status",
                "Use fallback context",
            ],
            cause=cause,
            details=details,
            **kwargs,
        )

        self.query = query


class MemoryNotFoundError(MemoryError):
    """
    Exception raised when requested memory entry is not found.

    Raised when attempting to access a specific memory entry that
    does not exist.

    Example:
        ```python
        try:
            entry = await memory.get_entry(entry_id)
        except MemoryNotFoundError:
            logger.info(f"Entry {entry_id} not found")
            entry = None
        ```
    """

    def __init__(
        self,
        message: str,
        *,
        memory_type: str | None = None,
        entry_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize not found error.

        Args:
            message: Error description
            memory_type: Type of memory
            entry_id: Entry ID that was not found
            **kwargs: Additional error parameters
        """
        details = kwargs.pop("details", {})
        if entry_id:
            details["entry_id"] = entry_id

        super().__init__(
            message=message,
            memory_type=memory_type,
            operation="get",
            memory_id=entry_id,
            retryable=False,
            user_message="Memory entry not found",
            suggestions=[
                "Verify entry ID is correct",
                "Check if entry was deleted",
                "Use search instead of direct access",
            ],
            details=details,
            **kwargs,
        )

        self.entry_id = entry_id


class MemoryCapacityError(MemoryError):
    """
    Exception raised when memory capacity is exceeded.

    Raised when attempting to store data exceeds configured capacity limits.

    Example:
        ```python
        try:
            await memory.store(large_entry)
        except MemoryCapacityError:
            await memory.prune_old_entries()
            await memory.store(large_entry)
        ```
    """

    def __init__(
        self,
        message: str,
        *,
        memory_type: str | None = None,
        current_size: int | None = None,
        max_size: int | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize capacity error.

        Args:
            message: Error description
            memory_type: Type of memory
            current_size: Current memory size
            max_size: Maximum allowed size
            **kwargs: Additional error parameters
        """
        details = kwargs.pop("details", {})
        if current_size is not None:
            details["current_size"] = current_size
        if max_size is not None:
            details["max_size"] = max_size

        super().__init__(
            message=message,
            memory_type=memory_type,
            operation="store",
            retryable=False,
            user_message="Memory capacity exceeded",
            suggestions=[
                "Clear old entries",
                "Increase memory capacity",
                "Enable automatic pruning",
                "Use summarization for old entries",
            ],
            severity=ErrorSeverity.HIGH,
            details=details,
            **kwargs,
        )

        self.current_size = current_size
        self.max_size = max_size


class MemorySerializationError(MemoryError):
    """
    Exception raised when serializing/deserializing memory fails.

    Raised when converting memory entries to/from storage format fails.

    Example:
        ```python
        try:
            serialized = await memory.serialize_entry(entry)
        except MemorySerializationError as e:
            logger.error(f"Cannot serialize entry: {e}")
            # Use alternative serialization format
        ```
    """

    def __init__(
        self,
        message: str,
        *,
        memory_type: str | None = None,
        entry_id: str | None = None,
        serialization_format: str | None = None,
        cause: Exception | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize serialization error.

        Args:
            message: Error description
            memory_type: Type of memory
            entry_id: Entry ID that failed serialization
            serialization_format: Format attempted (json, pickle, etc.)
            cause: Original exception
            **kwargs: Additional error parameters
        """
        details = kwargs.pop("details", {})
        if entry_id:
            details["entry_id"] = entry_id
        if serialization_format:
            details["format"] = serialization_format

        super().__init__(
            message=message,
            memory_type=memory_type,
            operation="serialize",
            memory_id=entry_id,
            retryable=False,
            user_message="Failed to process memory data",
            suggestions=[
                "Check data types are serializable",
                "Use alternative serialization format",
                "Simplify entry data structure",
            ],
            cause=cause,
            details=details,
            **kwargs,
        )

        self.entry_id = entry_id
        self.serialization_format = serialization_format


class MemoryPruningError(MemoryError):
    """
    Exception raised when pruning/cleanup of memory fails.

    Raised when automatic or manual memory cleanup operations fail.

    Example:
        ```python
        try:
            await memory.prune(older_than=timestamp)
        except MemoryPruningError as e:
            logger.error(f"Pruning failed: {e}, continuing with full memory")
        ```
    """

    def __init__(
        self,
        message: str,
        *,
        memory_type: str | None = None,
        entries_to_prune: int | None = None,
        cause: Exception | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize pruning error.

        Args:
            message: Error description
            memory_type: Type of memory
            entries_to_prune: Number of entries attempted to prune
            cause: Original exception
            **kwargs: Additional error parameters
        """
        details = kwargs.pop("details", {})
        if entries_to_prune is not None:
            details["entries_to_prune"] = entries_to_prune

        super().__init__(
            message=message,
            memory_type=memory_type,
            operation="prune",
            retryable=True,
            user_message="Failed to clean up memory",
            suggestions=[
                "Retry pruning operation",
                "Check storage permissions",
                "Manually clear specific entries",
            ],
            cause=cause,
            details=details,
            **kwargs,
        )

        self.entries_to_prune = entries_to_prune


class MemoryConsolidationError(MemoryError):
    """
    Exception raised when memory consolidation fails.

    Raised when merging, summarizing, or hierarchically consolidating
    memory entries encounters an error.

    Example:
        ```python
        try:
            result = await consolidation_engine.consolidate(entries, security_context)
        except MemoryConsolidationError as e:
            logger.error(f"Consolidation failed: {e}")
        ```
    """

    def __init__(
        self,
        message: str,
        *,
        memory_type: str | None = None,
        strategy: str | None = None,
        entries_count: int | None = None,
        cause: Exception | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize consolidation error.

        Args:
            message: Error description
            memory_type: Type of memory being consolidated
            strategy: Consolidation strategy that failed
            entries_count: Number of entries being consolidated
            cause: Original exception
            **kwargs: Additional error parameters
        """
        details = kwargs.pop("details", {})
        if strategy:
            details["strategy"] = strategy
        if entries_count is not None:
            details["entries_count"] = entries_count

        super().__init__(
            message=message,
            memory_type=memory_type,
            operation="consolidate",
            retryable=True,
            user_message="Failed to consolidate memory entries",
            suggestions=[
                "Retry consolidation with fewer entries",
                "Check LLM service availability",
                "Try a different consolidation strategy",
            ],
            cause=cause,
            details=details,
            **kwargs,
        )

        self.strategy = strategy
        self.entries_count = entries_count


class MemoryContextError(MemoryError):
    """
    Exception raised when building memory context fails.

    Raised when assembling context from memory tiers for agent
    consumption encounters an error.

    Example:
        ```python
        try:
            context = await context_builder.build(query, security_context)
        except MemoryContextError as e:
            logger.warning(f"Context build failed: {e}, using empty context")
        ```
    """

    def __init__(
        self,
        message: str,
        *,
        memory_type: str | None = None,
        strategy: str | None = None,
        max_tokens: int | None = None,
        cause: Exception | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize context error.

        Args:
            message: Error description
            memory_type: Type of memory
            strategy: Context strategy that failed
            max_tokens: Token budget that may have been exceeded
            cause: Original exception
            **kwargs: Additional error parameters
        """
        details = kwargs.pop("details", {})
        if strategy:
            details["strategy"] = strategy
        if max_tokens is not None:
            details["max_tokens"] = max_tokens

        super().__init__(
            message=message,
            memory_type=memory_type,
            operation="get_context",
            retryable=True,
            user_message="Failed to build memory context",
            suggestions=[
                "Retry context building",
                "Reduce token budget",
                "Use simpler context strategy",
            ],
            cause=cause,
            details=details,
            **kwargs,
        )

        self.strategy = strategy
        self.max_tokens = max_tokens


class MemoryDecayError(MemoryError):
    """
    Exception raised when memory decay processing fails.

    Raised when applying decay functions to memory entries
    encounters an error.

    Example:
        ```python
        try:
            await decay_manager.apply_decay(tier, security_context)
        except MemoryDecayError as e:
            logger.error(f"Decay failed: {e}")
        ```
    """

    def __init__(
        self,
        message: str,
        *,
        memory_type: str | None = None,
        decay_strategy: str | None = None,
        affected_entries: int | None = None,
        cause: Exception | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize decay error.

        Args:
            message: Error description
            memory_type: Type of memory
            decay_strategy: Decay strategy that failed
            affected_entries: Number of entries affected
            cause: Original exception
            **kwargs: Additional error parameters
        """
        details = kwargs.pop("details", {})
        if decay_strategy:
            details["decay_strategy"] = decay_strategy
        if affected_entries is not None:
            details["affected_entries"] = affected_entries

        super().__init__(
            message=message,
            memory_type=memory_type,
            operation="decay",
            retryable=True,
            user_message="Failed to apply memory decay",
            suggestions=[
                "Retry decay operation",
                "Check decay configuration parameters",
                "Manually prune stale entries",
            ],
            cause=cause,
            details=details,
            **kwargs,
        )

        self.decay_strategy = decay_strategy
        self.affected_entries = affected_entries


class MemoryTierError(MemoryError):
    """
    Exception raised when a memory tier operation fails.

    Raised when tier-specific operations like initialization,
    health checks, or cross-tier coordination fail.

    Example:
        ```python
        try:
            await tier.health_check(security_context)
        except MemoryTierError as e:
            logger.error(f"Tier {e.tier_name} unhealthy: {e}")
        ```
    """

    def __init__(
        self,
        message: str,
        *,
        memory_type: str | None = None,
        tier_name: str | None = None,
        cause: Exception | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize tier error.

        Args:
            message: Error description
            memory_type: Type of memory
            tier_name: Name of the memory tier
            cause: Original exception
            **kwargs: Additional error parameters
        """
        details = kwargs.pop("details", {})
        if tier_name:
            details["tier_name"] = tier_name

        super().__init__(
            message=message,
            memory_type=memory_type,
            operation="tier_operation",
            retryable=True,
            user_message="Memory tier operation failed",
            suggestions=[
                "Check tier backend connectivity",
                "Verify tier configuration",
                "Review tier health status",
            ],
            cause=cause,
            details=details,
            **kwargs,
        )

        self.tier_name = tier_name
