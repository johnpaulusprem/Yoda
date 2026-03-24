"""
Fallback strategies for resilient operations.

This module provides various fallback strategy implementations for use
with the FallbackChain.

Example:
    ```python
    from yoda_foundation.resilience.fallback import FallbackChain
    from yoda_foundation.resilience.fallback.fallback_strategies import (
        StaticFallback,
        CacheFallback,
        DegradedFallback,
        AlternativeServiceFallback,
    )

    # Create fallback chain with various strategies
    chain = FallbackChain()
    chain.add_fallback("primary", primary_function)
    chain.add_fallback("cache", CacheFallback(cache_client).execute)
    chain.add_fallback("static", StaticFallback({"default": "value"}).execute)

    result = await chain.execute(security_context=context)
    ```
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import (
    Any,
    Generic,
    TypeVar,
)

from yoda_foundation.exceptions import (
    FallbackError,
    FallbackFailedError,
    ValidationError,
)
from yoda_foundation.exceptions.base import AgenticBaseException
from yoda_foundation.security.context import SecurityContext


T = TypeVar("T")

logger = logging.getLogger(__name__)


class FallbackStrategyType(Enum):
    """Types of fallback strategies."""

    STATIC = "static"
    CACHE = "cache"
    DEGRADED = "degraded"
    ALTERNATIVE_SERVICE = "alternative_service"
    CUSTOM = "custom"


@dataclass
class FallbackStrategyConfig:
    """
    Configuration for fallback strategies.

    Attributes:
        name: Strategy name
        priority: Execution priority (lower = higher priority)
        timeout_ms: Maximum execution time in milliseconds
        enabled: Whether the strategy is enabled
        metadata: Additional configuration metadata

    Example:
        ```python
        config = FallbackStrategyConfig(
            name="cache_fallback",
            priority=2,
            timeout_ms=5000,
        )
        ```
    """

    name: str
    priority: int = 0
    timeout_ms: int = 30000
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class FallbackExecutionResult(Generic[T]):
    """
    Result of fallback strategy execution.

    Attributes:
        value: The result value
        strategy_name: Name of the strategy that succeeded
        strategy_type: Type of the strategy
        execution_time_ms: Time taken to execute
        is_degraded: Whether the result is degraded
        metadata: Additional result metadata

    Example:
        ```python
        result = FallbackExecutionResult(
            value={"data": "cached"},
            strategy_name="cache_fallback",
            strategy_type=FallbackStrategyType.CACHE,
            execution_time_ms=50,
            is_degraded=True,
        )
        ```
    """

    value: T
    strategy_name: str
    strategy_type: FallbackStrategyType
    execution_time_ms: float = 0.0
    is_degraded: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseFallbackStrategy(ABC, Generic[T]):
    """
    Base class for fallback strategies.

    Provides common functionality for all fallback strategy implementations.

    Attributes:
        config: Strategy configuration
        strategy_type: Type of this strategy

    Example:
        ```python
        class MyFallback(BaseFallbackStrategy[dict]):
            async def execute(
                self,
                security_context: SecurityContext,
                **kwargs,
            ) -> dict:
                return {"fallback": True}
        ```
    """

    def __init__(
        self,
        config: FallbackStrategyConfig | None = None,
        strategy_type: FallbackStrategyType = FallbackStrategyType.CUSTOM,
    ) -> None:
        """
        Initialize fallback strategy.

        Args:
            config: Strategy configuration
            strategy_type: Type of this strategy
        """
        self.config = config or FallbackStrategyConfig(name="base")
        self.strategy_type = strategy_type
        self._execution_count = 0
        self._success_count = 0
        self._failure_count = 0

    @abstractmethod
    async def execute(
        self,
        security_context: SecurityContext,
        **kwargs: Any,
    ) -> T:
        """
        Execute the fallback strategy.

        Args:
            security_context: Security context
            **kwargs: Additional arguments

        Returns:
            Fallback result value

        Raises:
            FallbackError: If fallback execution fails
        """
        pass

    async def execute_with_result(
        self,
        security_context: SecurityContext,
        **kwargs: Any,
    ) -> FallbackExecutionResult[T]:
        """
        Execute the fallback and return detailed result.

        Args:
            security_context: Security context
            **kwargs: Additional arguments

        Returns:
            FallbackExecutionResult with detailed information

        Example:
            ```python
            result = await strategy.execute_with_result(
                security_context=context,
            )
            if result.is_degraded:
                logger.warning("Using degraded response")
            ```
        """
        start_time = datetime.now(UTC)
        self._execution_count += 1

        try:
            value = await self.execute(security_context, **kwargs)
            self._success_count += 1

            execution_time = (datetime.now(UTC) - start_time).total_seconds() * 1000

            return FallbackExecutionResult(
                value=value,
                strategy_name=self.config.name,
                strategy_type=self.strategy_type,
                execution_time_ms=execution_time,
                is_degraded=self._is_degraded_result(),
            )

        except (
            AgenticBaseException,
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            TypeError,
            KeyError,
            RuntimeError,
        ):
            self._failure_count += 1
            raise

    def _is_degraded_result(self) -> bool:
        """
        Check if this strategy provides degraded results.

        Determines whether the fallback result should be considered
        degraded based on the strategy type. Cache, degraded, and
        static strategies are considered to provide degraded results.

        Returns:
            True if the strategy produces degraded results.
        """
        return self.strategy_type in (
            FallbackStrategyType.CACHE,
            FallbackStrategyType.DEGRADED,
            FallbackStrategyType.STATIC,
        )

    async def get_statistics(
        self,
        security_context: SecurityContext,
    ) -> dict[str, Any]:
        """
        Get strategy execution statistics.

        Args:
            security_context: Security context

        Returns:
            Dictionary with execution statistics

        Example:
            ```python
            stats = await strategy.get_statistics(security_context=context)
            print(f"Success rate: {stats['success_rate']:.2%}")
            ```
        """
        total = self._execution_count or 1
        return {
            "strategy_name": self.config.name,
            "strategy_type": self.strategy_type.value,
            "execution_count": self._execution_count,
            "success_count": self._success_count,
            "failure_count": self._failure_count,
            "success_rate": self._success_count / total,
        }


class StaticFallback(BaseFallbackStrategy[T]):
    """
    Static fallback that returns a predetermined value.

    Returns a static value when all primary strategies fail.
    Useful for providing default responses.

    Attributes:
        static_value: The static value to return

    Example:
        ```python
        # Create static fallback with default response
        fallback = StaticFallback(
            value={"status": "unavailable", "data": []},
            config=FallbackStrategyConfig(name="default_response"),
        )

        # Use in fallback chain
        result = await fallback.execute(security_context=context)
        print(result)  # {"status": "unavailable", "data": []}
        ```
    """

    def __init__(
        self,
        value: T,
        config: FallbackStrategyConfig | None = None,
    ) -> None:
        """
        Initialize static fallback.

        Args:
            value: The static value to return
            config: Strategy configuration
        """
        config = config or FallbackStrategyConfig(name="static_fallback")
        super().__init__(config=config, strategy_type=FallbackStrategyType.STATIC)
        self.static_value = value

    async def execute(
        self,
        security_context: SecurityContext,
        **kwargs: Any,
    ) -> T:
        """
        Return the static value.

        Args:
            security_context: Security context
            **kwargs: Ignored

        Returns:
            The static fallback value

        Example:
            ```python
            result = await fallback.execute(security_context=context)
            ```
        """
        logger.debug(
            f"Static fallback '{self.config.name}' returning predetermined value",
            extra={"strategy": self.config.name},
        )
        return self.static_value


class CacheFallback(BaseFallbackStrategy[T]):
    """
    Cache fallback that returns previously cached values.

    Retrieves values from a cache when primary strategies fail.
    Supports configurable cache key generation.

    Attributes:
        cache_client: Cache client for retrieving values
        key_generator: Function to generate cache keys

    Example:
        ```python
        # Create cache fallback
        fallback = CacheFallback(
            cache_client=redis_client,
            key_prefix="api_response",
            config=FallbackStrategyConfig(name="cache_fallback"),
        )

        # Use in fallback chain
        result = await fallback.execute(
            security_context=context,
            cache_key="user_123_profile",
        )
        ```
    """

    def __init__(
        self,
        cache_client: Any,
        key_prefix: str = "fallback",
        key_generator: Callable[..., str] | None = None,
        default_value: T | None = None,
        config: FallbackStrategyConfig | None = None,
    ) -> None:
        """
        Initialize cache fallback.

        Args:
            cache_client: Cache client (must have async get method)
            key_prefix: Prefix for cache keys
            key_generator: Optional function to generate cache keys
            default_value: Value to return if cache miss
            config: Strategy configuration
        """
        config = config or FallbackStrategyConfig(name="cache_fallback")
        super().__init__(config=config, strategy_type=FallbackStrategyType.CACHE)
        self.cache_client = cache_client
        self.key_prefix = key_prefix
        self.key_generator = key_generator
        self.default_value = default_value

    async def execute(
        self,
        security_context: SecurityContext,
        cache_key: str | None = None,
        **kwargs: Any,
    ) -> T:
        """
        Retrieve value from cache.

        Args:
            security_context: Security context
            cache_key: Cache key to retrieve
            **kwargs: Additional arguments for key generation

        Returns:
            Cached value or default value

        Raises:
            FallbackError: If cache retrieval fails and no default

        Example:
            ```python
            result = await fallback.execute(
                security_context=context,
                cache_key="user_profile_123",
            )
            ```
        """
        # Generate cache key
        if cache_key:
            full_key = f"{self.key_prefix}:{cache_key}"
        elif self.key_generator:
            generated_key = self.key_generator(**kwargs)
            full_key = f"{self.key_prefix}:{generated_key}"
        else:
            full_key = self.key_prefix

        try:
            logger.debug(
                f"Cache fallback '{self.config.name}' retrieving key: {full_key}",
                extra={"strategy": self.config.name, "cache_key": full_key},
            )

            # Try to get from cache
            if hasattr(self.cache_client, "get"):
                if asyncio.iscoroutinefunction(self.cache_client.get):
                    value = await self.cache_client.get(full_key)
                else:
                    value = self.cache_client.get(full_key)
            else:
                raise FallbackError(
                    message="Cache client does not have 'get' method",
                    operation="cache_fallback",
                )

            if value is not None:
                logger.info(
                    f"Cache fallback '{self.config.name}' hit for key: {full_key}",
                    extra={"strategy": self.config.name, "cache_key": full_key},
                )
                return value

            # Cache miss
            if self.default_value is not None:
                logger.info(
                    f"Cache fallback '{self.config.name}' miss, returning default",
                    extra={"strategy": self.config.name, "cache_key": full_key},
                )
                return self.default_value

            raise FallbackError(
                message=f"Cache miss for key '{full_key}' and no default value",
                operation="cache_fallback",
            )

        except FallbackError:
            raise
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
            raise FallbackError(
                message=f"Cache fallback failed: {e!s}",
                operation="cache_fallback",
                cause=e,
            )

    async def set_cache(
        self,
        security_context: SecurityContext,
        cache_key: str,
        value: T,
        ttl_seconds: int | None = None,
    ) -> None:
        """
        Store value in cache for future fallback.

        Args:
            security_context: Security context
            cache_key: Cache key to store under
            value: Value to cache
            ttl_seconds: Time-to-live in seconds

        Example:
            ```python
            await fallback.set_cache(
                security_context=context,
                cache_key="user_profile_123",
                value=user_profile,
                ttl_seconds=3600,
            )
            ```
        """
        full_key = f"{self.key_prefix}:{cache_key}"

        try:
            if hasattr(self.cache_client, "set"):
                if asyncio.iscoroutinefunction(self.cache_client.set):
                    if ttl_seconds:
                        await self.cache_client.set(full_key, value, ttl=ttl_seconds)
                    else:
                        await self.cache_client.set(full_key, value)
                elif ttl_seconds:
                    self.cache_client.set(full_key, value, ttl=ttl_seconds)
                else:
                    self.cache_client.set(full_key, value)

            logger.debug(
                f"Cache fallback '{self.config.name}' stored key: {full_key}",
                extra={"strategy": self.config.name, "cache_key": full_key},
            )

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
            logger.warning(
                f"Failed to set cache for key '{full_key}': {e!s}",
                extra={"strategy": self.config.name, "cache_key": full_key},
            )


class DegradedFallback(BaseFallbackStrategy[T]):
    """
    Degraded fallback that provides reduced functionality.

    Executes a degraded version of the operation when the primary fails.
    Useful for graceful degradation scenarios.

    Attributes:
        degraded_function: Function providing degraded functionality
        degradation_level: Level of degradation (0.0 = full, 1.0 = minimal)

    Example:
        ```python
        async def degraded_search(query: str) -> dict:
            # Return limited search results
            return {"results": [], "degraded": True, "message": "Limited results"}

        fallback = DegradedFallback(
            degraded_function=degraded_search,
            degradation_level=0.5,
            config=FallbackStrategyConfig(name="degraded_search"),
        )

        result = await fallback.execute(
            security_context=context,
            query="search term",
        )
        ```
    """

    def __init__(
        self,
        degraded_function: Callable[..., Awaitable[T]],
        degradation_level: float = 0.5,
        description: str | None = None,
        config: FallbackStrategyConfig | None = None,
    ) -> None:
        """
        Initialize degraded fallback.

        Args:
            degraded_function: Async function providing degraded functionality
            degradation_level: Level of degradation (0.0-1.0)
            description: Description of degraded functionality
            config: Strategy configuration

        Raises:
            ValidationError: If degradation_level is out of range
        """
        if not 0.0 <= degradation_level <= 1.0:
            raise ValidationError(
                message=f"degradation_level must be between 0.0 and 1.0, got {degradation_level}",
                field_name="degradation_level",
            )

        config = config or FallbackStrategyConfig(name="degraded_fallback")
        super().__init__(config=config, strategy_type=FallbackStrategyType.DEGRADED)
        self.degraded_function = degraded_function
        self.degradation_level = degradation_level
        self.description = description or "Degraded functionality"

    async def execute(
        self,
        security_context: SecurityContext,
        **kwargs: Any,
    ) -> T:
        """
        Execute degraded functionality.

        Args:
            security_context: Security context
            **kwargs: Arguments passed to degraded function

        Returns:
            Result from degraded function

        Raises:
            FallbackError: If degraded function fails

        Example:
            ```python
            result = await fallback.execute(
                security_context=context,
                query="search term",
            )
            ```
        """
        try:
            logger.info(
                f"Degraded fallback '{self.config.name}' executing with level {self.degradation_level}",
                extra={
                    "strategy": self.config.name,
                    "degradation_level": self.degradation_level,
                    "description": self.description,
                },
            )

            result = await self.degraded_function(**kwargs)

            logger.info(
                f"Degraded fallback '{self.config.name}' completed successfully",
                extra={"strategy": self.config.name},
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
            raise FallbackError(
                message=f"Degraded fallback failed: {e!s}",
                operation="degraded_fallback",
                cause=e,
            )


class AlternativeServiceFallback(BaseFallbackStrategy[T]):
    """
    Alternative service fallback that routes to backup services.

    Routes requests to alternative services when the primary fails.
    Supports multiple backup services with priority ordering.

    Attributes:
        services: List of alternative service callables
        service_names: Names of the services for logging

    Example:
        ```python
        async def backup_api_1(params: dict) -> dict:
            return await backup_client_1.call(params)

        async def backup_api_2(params: dict) -> dict:
            return await backup_client_2.call(params)

        fallback = AlternativeServiceFallback(
            services=[
                ("backup_region_1", backup_api_1),
                ("backup_region_2", backup_api_2),
            ],
            config=FallbackStrategyConfig(name="geo_fallback"),
        )

        result = await fallback.execute(
            security_context=context,
            params={"query": "data"},
        )
        ```
    """

    def __init__(
        self,
        services: list[tuple[str, Callable[..., Awaitable[T]]]],
        fail_fast: bool = False,
        config: FallbackStrategyConfig | None = None,
    ) -> None:
        """
        Initialize alternative service fallback.

        Args:
            services: List of (name, callable) tuples for alternative services
            fail_fast: Whether to fail immediately on first error
            config: Strategy configuration

        Raises:
            ValidationError: If no services provided
        """
        if not services:
            raise ValidationError(
                message="At least one alternative service must be provided",
                field_name="services",
            )

        config = config or FallbackStrategyConfig(name="alternative_service_fallback")
        super().__init__(
            config=config,
            strategy_type=FallbackStrategyType.ALTERNATIVE_SERVICE,
        )
        self.services = services
        self.fail_fast = fail_fast
        self._service_stats: dict[str, dict[str, int]] = {
            name: {"attempts": 0, "successes": 0, "failures": 0} for name, _ in services
        }

    async def execute(
        self,
        security_context: SecurityContext,
        **kwargs: Any,
    ) -> T:
        """
        Execute using alternative services.

        Args:
            security_context: Security context
            **kwargs: Arguments passed to service functions

        Returns:
            Result from first successful service

        Raises:
            FallbackFailedError: If all services fail

        Example:
            ```python
            result = await fallback.execute(
                security_context=context,
                params={"query": "data"},
            )
            ```
        """
        errors: list[tuple[str, Exception]] = []

        for service_name, service_func in self.services:
            self._service_stats[service_name]["attempts"] += 1

            try:
                logger.info(
                    f"Alternative service fallback trying '{service_name}'",
                    extra={
                        "strategy": self.config.name,
                        "service": service_name,
                    },
                )

                # Apply timeout if configured
                timeout_seconds = self.config.timeout_ms / 1000.0

                result = await asyncio.wait_for(
                    service_func(**kwargs),
                    timeout=timeout_seconds,
                )

                self._service_stats[service_name]["successes"] += 1

                logger.info(
                    f"Alternative service '{service_name}' succeeded",
                    extra={
                        "strategy": self.config.name,
                        "service": service_name,
                    },
                )

                return result

            except TimeoutError as e:
                self._service_stats[service_name]["failures"] += 1
                error = FallbackError(
                    message=f"Service '{service_name}' timed out after {self.config.timeout_ms}ms",
                    operation="alternative_service",
                    cause=e,
                )
                errors.append((service_name, error))

                logger.warning(
                    f"Alternative service '{service_name}' timed out",
                    extra={
                        "strategy": self.config.name,
                        "service": service_name,
                        "timeout_ms": self.config.timeout_ms,
                    },
                )

                if self.fail_fast:
                    break

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
                self._service_stats[service_name]["failures"] += 1
                errors.append((service_name, e))

                logger.warning(
                    f"Alternative service '{service_name}' failed: {e!s}",
                    extra={
                        "strategy": self.config.name,
                        "service": service_name,
                        "error": str(e),
                    },
                )

                if self.fail_fast:
                    break

        # All services failed
        service_names = [name for name, _ in self.services]
        raise FallbackFailedError(
            operation=f"alternative_service_fallback:{self.config.name}",
            fallback_chain=service_names,
            errors=[e for _, e in errors],
        )

    async def get_service_statistics(
        self,
        security_context: SecurityContext,
    ) -> dict[str, dict[str, Any]]:
        """
        Get statistics for each alternative service.

        Args:
            security_context: Security context

        Returns:
            Dictionary with service statistics

        Example:
            ```python
            stats = await fallback.get_service_statistics(security_context=context)
            for service, data in stats.items():
                print(f"{service}: {data['success_rate']:.2%}")
            ```
        """
        result = {}
        for service_name, stats in self._service_stats.items():
            total = stats["attempts"] or 1
            result[service_name] = {
                **stats,
                "success_rate": stats["successes"] / total,
            }
        return result

    def _is_degraded_result(self) -> bool:
        """
        Check if alternative service results are degraded.

        Alternative services typically provide full functionality
        equivalent to the primary service, so results are not
        considered degraded.

        Returns:
            False, as alternative services provide non-degraded results.
        """
        return False
