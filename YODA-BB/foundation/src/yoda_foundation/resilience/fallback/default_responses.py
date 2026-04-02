"""
Default response management for fallback scenarios.

This module provides priority-based fallback selection, context-aware
response generation, and graceful degradation strategies.

Example:
    ```python
    from yoda_foundation.resilience.fallback import (
        DefaultResponses,
        FallbackConfig,
        FallbackStrategy,
    )
    from yoda_foundation.security import create_security_context

    # Create default responses manager
    responses = DefaultResponses()

    # Register static fallback
    await responses.register_fallback(
        operation="get_user_profile",
        fallback_type="static",
        response={"name": "Guest", "role": "viewer"},
        priority=10,
        security_context=context,
    )

    # Register dynamic fallback
    async def cached_profile(ctx):
        return await cache.get(f"profile:{ctx['user_id']}")

    await responses.register_fallback(
        operation="get_user_profile",
        fallback_type="dynamic",
        response=cached_profile,
        priority=20,
        security_context=context,
    )

    # Get fallback response
    result = await responses.get_fallback(
        operation="get_user_profile",
        context={"user_id": "123"},
        security_context=context,
    )
    ```
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from yoda_foundation.exceptions import (
    FallbackError,
    ValidationError,
)
from yoda_foundation.exceptions.base import AgenticBaseException
from yoda_foundation.security.context import SecurityContext


logger = logging.getLogger(__name__)


class FallbackStrategy(Enum):
    """Fallback selection strategies."""

    PRIORITY = "priority"  # Use highest priority fallback
    ROUND_ROBIN = "round_robin"  # Rotate through fallbacks
    RANDOM = "random"  # Random selection
    ALL = "all"  # Try all fallbacks in order


class FallbackType(Enum):
    """Types of fallback responses."""

    STATIC = "static"  # Static response value
    DYNAMIC = "dynamic"  # Dynamic function-generated response
    CACHED = "cached"  # Cached previous response
    DEFAULT = "default"  # Default safe value


@dataclass
class FallbackConfig:
    """
    Configuration for a fallback response.

    Attributes:
        operation: Operation name
        fallback_type: Type of fallback
        response: Fallback response (value or function)
        priority: Priority (higher = preferred)
        enabled: Whether fallback is enabled
        conditions: Conditions for using this fallback
        metadata: Additional metadata
        created_at: When fallback was registered
        last_used: Last time fallback was used
        use_count: Number of times fallback was used

    Example:
        ```python
        config = FallbackConfig(
            operation="get_data",
            fallback_type=FallbackType.STATIC,
            response={"status": "unavailable"},
            priority=10,
        )
        ```
    """

    operation: str
    fallback_type: FallbackType
    response: Any | Callable[[dict[str, Any]], Awaitable[Any]]
    priority: int = 0
    enabled: bool = True
    conditions: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_used: datetime | None = None
    use_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """
        Convert config to dictionary.

        Returns:
            Dictionary representation
        """
        data = {
            "operation": self.operation,
            "fallback_type": self.fallback_type.value,
            "priority": self.priority,
            "enabled": self.enabled,
            "conditions": self.conditions,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "last_used": self.last_used.isoformat() if self.last_used else None,
            "use_count": self.use_count,
        }

        # Include response if it's serializable
        if not callable(self.response):
            data["response"] = self.response

        return data


class DefaultResponses:
    """
    Default response manager for fallback scenarios.

    Manages fallback responses with priority-based selection,
    context-aware generation, and graceful degradation.

    Attributes:
        strategy: Fallback selection strategy
        max_fallbacks_per_operation: Maximum fallbacks per operation
        cache_responses: Whether to cache dynamic responses

    Example:
        ```python
        # Create default responses manager
        responses = DefaultResponses(
            strategy=FallbackStrategy.PRIORITY,
            cache_responses=True,
        )

        # Register static fallback
        await responses.register_fallback(
            operation="search",
            fallback_type="static",
            response={"results": [], "total": 0},
            priority=10,
            security_context=context,
        )

        # Register dynamic fallback with higher priority
        async def cached_search(ctx):
            return await cache.get(f"search:{ctx['query']}")

        await responses.register_fallback(
            operation="search",
            fallback_type="dynamic",
            response=cached_search,
            priority=20,
            security_context=context,
        )

        # Get fallback
        result = await responses.get_fallback(
            operation="search",
            context={"query": "python"},
            security_context=context,
        )
        ```
    """

    def __init__(
        self,
        strategy: FallbackStrategy = FallbackStrategy.PRIORITY,
        max_fallbacks_per_operation: int = 10,
        cache_responses: bool = True,
        cache_ttl_seconds: int = 300,
    ) -> None:
        """
        Initialize default responses manager.

        Args:
            strategy: Fallback selection strategy
            max_fallbacks_per_operation: Max fallbacks per operation
            cache_responses: Whether to cache dynamic responses
            cache_ttl_seconds: Cache TTL for dynamic responses

        Raises:
            ValidationError: If parameters are invalid
        """
        if max_fallbacks_per_operation < 1:
            raise ValidationError(
                message=f"max_fallbacks_per_operation must be at least 1, got {max_fallbacks_per_operation}",
                field_name="max_fallbacks_per_operation",
            )

        self.strategy = strategy
        self.max_fallbacks_per_operation = max_fallbacks_per_operation
        self.cache_responses = cache_responses
        self.cache_ttl_seconds = cache_ttl_seconds

        # Storage
        self._fallbacks: dict[str, list[FallbackConfig]] = {}
        self._cache: dict[str, tuple[Any, datetime]] = {}
        self._lock = asyncio.Lock()

        # Round-robin state
        self._round_robin_index: dict[str, int] = {}

    async def register_fallback(
        self,
        operation: str,
        fallback_type: str,
        response: Any | Callable[[dict[str, Any]], Awaitable[Any]],
        security_context: SecurityContext,
        priority: int = 0,
        conditions: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Register a fallback response.

        Args:
            operation: Operation name
            fallback_type: Type of fallback
            response: Fallback response or generator function
            priority: Priority (higher = preferred)
            security_context: Security context
            conditions: Conditions for using this fallback
            metadata: Additional metadata

        Returns:
            Fallback ID

        Raises:
            ValidationError: If parameters are invalid
            FallbackError: If too many fallbacks registered

        Example:
            ```python
            # Static fallback
            await responses.register_fallback(
                operation="get_config",
                fallback_type="static",
                response={"timeout": 30},
                priority=10,
                security_context=context,
            )

            # Dynamic fallback
            async def get_cached_config(ctx):
                return await cache.get("config")

            await responses.register_fallback(
                operation="get_config",
                fallback_type="dynamic",
                response=get_cached_config,
                priority=20,
                security_context=context,
            )
            ```
        """
        security_context.require_permission("resilience.manage_fallback")

        try:
            fb_type = FallbackType(fallback_type)
        except ValueError:
            raise ValidationError(
                message=f"Invalid fallback_type: {fallback_type}",
                field_name="fallback_type",
            )

        # Validate dynamic fallback is callable
        if fb_type == FallbackType.DYNAMIC and not callable(response):
            raise ValidationError(
                message="Dynamic fallback must be a callable",
                field_name="response",
            )

        async with self._lock:
            # Check limit
            if operation in self._fallbacks:
                if len(self._fallbacks[operation]) >= self.max_fallbacks_per_operation:
                    raise FallbackError(
                        message=f"Too many fallbacks for operation '{operation}'",
                        operation=operation,
                    )

            # Create config
            config = FallbackConfig(
                operation=operation,
                fallback_type=fb_type,
                response=response,
                priority=priority,
                conditions=conditions or {},
                metadata=metadata or {},
            )

            # Add to storage
            if operation not in self._fallbacks:
                self._fallbacks[operation] = []

            self._fallbacks[operation].append(config)

            # Sort by priority (highest first)
            self._fallbacks[operation].sort(key=lambda x: x.priority, reverse=True)

            logger.info(
                f"Registered {fb_type.value} fallback for '{operation}'",
                extra={
                    "operation": operation,
                    "fallback_type": fb_type.value,
                    "priority": priority,
                },
            )

            return f"{operation}:{fb_type.value}:{priority}"

    async def get_fallback(
        self,
        operation: str,
        security_context: SecurityContext,
        context: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> Any:
        """
        Get fallback response for an operation.

        Args:
            operation: Operation name
            security_context: Security context
            context: Context for dynamic fallbacks
            error: Original error that triggered fallback

        Returns:
            Fallback response

        Raises:
            FallbackError: If no suitable fallback found

        Example:
            ```python
            try:
                result = await expensive_operation()
            except Exception as e:
                result = await responses.get_fallback(
                    operation="expensive_operation",
                    context={"user_id": user_id},
                    error=e,
                    security_context=context,
                )
            ```
        """
        security_context.require_permission("resilience.use_fallback")

        context = context or {}

        async with self._lock:
            # Get fallbacks for operation
            fallbacks = self._fallbacks.get(operation, [])
            if not fallbacks:
                raise FallbackError(
                    message=f"No fallback registered for operation '{operation}'",
                    operation=operation,
                )

            # Filter enabled fallbacks
            enabled_fallbacks = [fb for fb in fallbacks if fb.enabled]
            if not enabled_fallbacks:
                raise FallbackError(
                    message=f"No enabled fallbacks for operation '{operation}'",
                    operation=operation,
                )

            # Select fallback based on strategy
            selected = await self._select_fallback(
                operation=operation,
                fallbacks=enabled_fallbacks,
                context=context,
            )

            if selected is None:
                raise FallbackError(
                    message=f"No suitable fallback found for operation '{operation}'",
                    operation=operation,
                )

        # Execute fallback (outside lock)
        try:
            result = await self._execute_fallback(
                config=selected,
                context=context,
            )

            # Update usage stats
            async with self._lock:
                selected.use_count += 1
                selected.last_used = datetime.now(UTC)

            logger.info(
                f"Used {selected.fallback_type.value} fallback for '{operation}'",
                extra={
                    "operation": operation,
                    "fallback_type": selected.fallback_type.value,
                    "priority": selected.priority,
                },
            )

            return result

        except (
            AgenticBaseException,
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            TypeError,
            KeyError,
            RuntimeError,
        ) as e:
            logger.error(
                f"Fallback execution failed for '{operation}'",
                exc_info=True,
                extra={
                    "operation": operation,
                    "fallback_type": selected.fallback_type.value,
                },
            )
            raise FallbackError(
                message=f"Fallback execution failed for '{operation}'",
                operation=operation,
                cause=e,
            )

    async def list_fallbacks(
        self,
        security_context: SecurityContext,
        operation: str | None = None,
    ) -> list[FallbackConfig]:
        """
        List registered fallbacks.

        Args:
            operation: Optional operation filter
            security_context: Security context

        Returns:
            List of fallback configurations

        Example:
            ```python
            # List all fallbacks
            all_fallbacks = await responses.list_fallbacks(
                security_context=context,
            )

            # List fallbacks for specific operation
            search_fallbacks = await responses.list_fallbacks(
                operation="search",
                security_context=context,
            )
            ```
        """
        security_context.require_permission("resilience.read_fallback")

        async with self._lock:
            if operation:
                return list(self._fallbacks.get(operation, []))

            # Return all fallbacks
            all_fallbacks = []
            for fallback_list in self._fallbacks.values():
                all_fallbacks.extend(fallback_list)
            return all_fallbacks

    async def remove_fallback(
        self,
        operation: str,
        security_context: SecurityContext,
        priority: int | None = None,
    ) -> int:
        """
        Remove fallback(s) for an operation.

        Args:
            operation: Operation name
            priority: Optional priority filter
            security_context: Security context

        Returns:
            Number of fallbacks removed

        Example:
            ```python
            # Remove all fallbacks for operation
            count = await responses.remove_fallback(
                operation="search",
                security_context=context,
            )

            # Remove specific priority fallback
            count = await responses.remove_fallback(
                operation="search",
                priority=10,
                security_context=context,
            )
            ```
        """
        security_context.require_permission("resilience.manage_fallback")

        async with self._lock:
            if operation not in self._fallbacks:
                return 0

            if priority is not None:
                # Remove specific priority
                original_len = len(self._fallbacks[operation])
                self._fallbacks[operation] = [
                    fb for fb in self._fallbacks[operation] if fb.priority != priority
                ]
                removed = original_len - len(self._fallbacks[operation])
            else:
                # Remove all
                removed = len(self._fallbacks[operation])
                del self._fallbacks[operation]

            logger.info(
                f"Removed {removed} fallback(s) for '{operation}'",
                extra={"operation": operation, "removed": removed},
            )

            return removed

    async def enable_fallback(
        self,
        operation: str,
        security_context: SecurityContext,
        priority: int,
    ) -> None:
        """
        Enable a fallback.

        Args:
            operation: Operation name
            priority: Fallback priority
            security_context: Security context

        Example:
            ```python
            await responses.enable_fallback(
                operation="search",
                priority=20,
                security_context=context,
            )
            ```
        """
        security_context.require_permission("resilience.manage_fallback")

        async with self._lock:
            fallbacks = self._fallbacks.get(operation, [])
            for fb in fallbacks:
                if fb.priority == priority:
                    fb.enabled = True
                    logger.info(
                        f"Enabled fallback for '{operation}' with priority {priority}",
                        extra={"operation": operation, "priority": priority},
                    )
                    return

    async def disable_fallback(
        self,
        operation: str,
        security_context: SecurityContext,
        priority: int,
    ) -> None:
        """
        Disable a fallback.

        Args:
            operation: Operation name
            priority: Fallback priority
            security_context: Security context

        Example:
            ```python
            await responses.disable_fallback(
                operation="search",
                priority=10,
                security_context=context,
            )
            ```
        """
        security_context.require_permission("resilience.manage_fallback")

        async with self._lock:
            fallbacks = self._fallbacks.get(operation, [])
            for fb in fallbacks:
                if fb.priority == priority:
                    fb.enabled = False
                    logger.info(
                        f"Disabled fallback for '{operation}' with priority {priority}",
                        extra={"operation": operation, "priority": priority},
                    )
                    return

    async def _select_fallback(
        self,
        operation: str,
        fallbacks: list[FallbackConfig],
        context: dict[str, Any],
    ) -> FallbackConfig | None:
        """
        Select a fallback based on strategy.

        Args:
            operation: Operation name
            fallbacks: Available fallbacks
            context: Execution context

        Returns:
            Selected fallback config or None
        """
        # Filter by conditions
        suitable = []
        for fb in fallbacks:
            if await self._check_conditions(fb, context):
                suitable.append(fb)

        if not suitable:
            return None

        # Apply strategy
        if self.strategy == FallbackStrategy.PRIORITY:
            # Already sorted by priority
            return suitable[0]

        elif self.strategy == FallbackStrategy.ROUND_ROBIN:
            # Round-robin selection
            if operation not in self._round_robin_index:
                self._round_robin_index[operation] = 0

            index = self._round_robin_index[operation]
            selected = suitable[index % len(suitable)]
            self._round_robin_index[operation] = (index + 1) % len(suitable)
            return selected

        elif self.strategy == FallbackStrategy.RANDOM:
            # Random selection
            import random

            return random.choice(suitable)

        else:
            # Default to priority
            return suitable[0]

    async def _check_conditions(
        self,
        config: FallbackConfig,
        context: dict[str, Any],
    ) -> bool:
        """
        Check if fallback conditions are met.

        Args:
            config: Fallback config
            context: Execution context

        Returns:
            True if conditions are met
        """
        if not config.conditions:
            return True

        # Simple condition checking
        for key, value in config.conditions.items():
            if key not in context or context[key] != value:
                return False

        return True

    async def _execute_fallback(
        self,
        config: FallbackConfig,
        context: dict[str, Any],
    ) -> Any:
        """
        Execute a fallback.

        Args:
            config: Fallback config
            context: Execution context

        Returns:
            Fallback result
        """
        if config.fallback_type == FallbackType.STATIC:
            return config.response

        elif config.fallback_type == FallbackType.DYNAMIC:
            # Check cache first
            if self.cache_responses:
                cache_key = f"{config.operation}:{hash(str(context))}"
                if cache_key in self._cache:
                    cached_value, cached_at = self._cache[cache_key]
                    age = (datetime.now(UTC) - cached_at).total_seconds()
                    if age < self.cache_ttl_seconds:
                        logger.debug(f"Using cached fallback for {config.operation}")
                        return cached_value

            # Execute dynamic function
            result = await config.response(context)

            # Cache result
            if self.cache_responses:
                cache_key = f"{config.operation}:{hash(str(context))}"
                self._cache[cache_key] = (result, datetime.now(UTC))

            return result

        elif config.fallback_type == FallbackType.CACHED:
            # Return cached response
            cache_key = f"{config.operation}:{hash(str(context))}"
            if cache_key in self._cache:
                cached_value, _ = self._cache[cache_key]
                return cached_value
            # Fall back to static response if no cache
            return config.response

        else:  # DEFAULT
            return config.response

    async def clear_cache(self, security_context: SecurityContext) -> None:
        """
        Clear cached fallback responses.

        Args:
            security_context: Security context

        Example:
            ```python
            await responses.clear_cache(security_context=context)
            ```
        """
        security_context.require_permission("resilience.manage_fallback")

        async with self._lock:
            self._cache.clear()
            logger.info("Cleared fallback response cache")
