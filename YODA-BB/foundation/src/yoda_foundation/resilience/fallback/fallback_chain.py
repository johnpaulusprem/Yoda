"""
Fallback chain for sequential fallback strategies.

This module provides a fallback chain that tries multiple strategies
in sequence until one succeeds.

Example:
    ```python
    from yoda_foundation.resilience.fallback import FallbackChain

    chain = FallbackChain()

    # Add fallback strategies
    chain.add_fallback("primary_db", lambda: fetch_from_db())
    chain.add_fallback("cache", lambda: fetch_from_cache())
    chain.add_fallback("default", lambda: get_default_value())

    # Execute with fallbacks
    result = await chain.execute(security_context=context)
    ```
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from yoda_foundation.exceptions import FallbackFailedError
from yoda_foundation.exceptions.base import AgenticBaseException
from yoda_foundation.security.context import SecurityContext


T = TypeVar("T")

logger = logging.getLogger(__name__)


@dataclass
class FallbackResult:
    """
    Result of fallback chain execution.

    Attributes:
        result: The result value from the successful fallback.
        strategy_used: Name of the strategy that succeeded.
        attempts: List of strategy attempts with errors.
        success: Whether a fallback succeeded.
    """

    result: Any
    strategy_used: str
    attempts: list[tuple[str, Exception | None]]
    success: bool


class FallbackChain:
    """
    Sequential fallback chain.

    Tries multiple fallback strategies in order until one succeeds.

    Attributes:
        _fallbacks: List of named fallback strategies in order.

    Example:
        ```python
        chain = FallbackChain()
        chain.add_fallback("primary", primary_func)
        chain.add_fallback("secondary", secondary_func)

        result = await chain.execute(security_context=context)
        ```
    """

    def __init__(self) -> None:
        """Initialize fallback chain."""
        self._fallbacks: list[tuple[str, Callable[..., Awaitable[T]]]] = []

    def add_fallback(
        self,
        name: str,
        func: Callable[..., Awaitable[T]],
    ) -> FallbackChain:
        """
        Add fallback strategy.

        Args:
            name: Fallback name
            func: Fallback function

        Returns:
            Self for chaining

        Example:
            ```python
            chain.add_fallback("primary", func1) \\
                 .add_fallback("secondary", func2)
            ```
        """
        self._fallbacks.append((name, func))
        return self

    async def execute(
        self,
        security_context: SecurityContext,
        args: tuple[Any, ...] = (),
        kwargs: dict | None = None,
    ) -> T:
        """
        Execute fallback chain.

        Args:
            security_context: Security context
            args: Arguments for fallback functions
            kwargs: Keyword arguments for fallback functions

        Returns:
            Result from first successful fallback

        Raises:
            FallbackFailedError: If all fallbacks fail

        Example:
            ```python
            result = await chain.execute(
                security_context=context,
                args=(arg1,),
                kwargs={"key": "value"},
            )
            ```
        """
        kwargs = kwargs or {}
        attempts: list[tuple[str, Exception | None]] = []
        errors: list[Exception | None] = []

        for name, func in self._fallbacks:
            try:
                logger.info(f"Attempting fallback strategy: {name}")
                result = await func(*args, **kwargs)
                attempts.append((name, None))

                logger.info(f"Fallback strategy '{name}' succeeded")
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
                logger.warning(
                    f"Fallback strategy '{name}' failed: {e!s}",
                    extra={"fallback": name, "exception": str(e)},
                )
                attempts.append((name, e))
                errors.append(e)

        # All fallbacks failed
        fallback_names = [name for name, _ in self._fallbacks]
        raise FallbackFailedError(
            operation="fallback_chain",
            fallback_chain=fallback_names,
            errors=errors,
        )
