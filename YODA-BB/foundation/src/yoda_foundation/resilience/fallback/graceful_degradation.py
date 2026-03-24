"""
Graceful degradation for reduced functionality fallback.

Provides mechanisms to gracefully degrade functionality when
full features are unavailable.

Example:
    ```python
    from yoda_foundation.resilience.fallback import GracefulDegradation

    degradation = GracefulDegradation()

    # Configure degradation levels
    degradation.add_level("full", full_function)
    degradation.add_level("reduced", reduced_function)
    degradation.add_level("minimal", minimal_function)

    result = await degradation.execute(
        preferred_level="full",
        security_context=context,
    )
    ```
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any, TypeVar

from yoda_foundation.exceptions.base import AgenticBaseException
from yoda_foundation.security.context import SecurityContext


T = TypeVar("T")

logger = logging.getLogger(__name__)


class DegradationLevel(Enum):
    """Service degradation levels."""

    FULL = "full"
    REDUCED = "reduced"
    MINIMAL = "minimal"
    EMERGENCY = "emergency"


class GracefulDegradation:
    """
    Graceful degradation manager.

    Manages multiple service levels and gracefully degrades
    when full functionality is unavailable.

    Attributes:
        _levels: Mapping of degradation levels to handler functions.
        _current_level: The currently active degradation level.

    Example:
        ```python
        degradation = GracefulDegradation()

        degradation.add_level(
            DegradationLevel.FULL,
            full_service_function,
        )
        degradation.add_level(
            DegradationLevel.REDUCED,
            reduced_service_function,
        )

        result = await degradation.execute(
            preferred_level=DegradationLevel.FULL,
            security_context=context,
        )
        ```
    """

    def __init__(self) -> None:
        """Initialize graceful degradation."""
        self._levels: dict[DegradationLevel, Callable[..., Awaitable[T]]] = {}
        self._current_level = DegradationLevel.FULL

    def add_level(
        self,
        level: DegradationLevel,
        func: Callable[..., Awaitable[T]],
    ) -> GracefulDegradation:
        """
        Add degradation level.

        Args:
            level: Degradation level
            func: Function for this level

        Returns:
            Self for chaining
        """
        self._levels[level] = func
        return self

    async def execute(
        self,
        security_context: SecurityContext,
        preferred_level: DegradationLevel = DegradationLevel.FULL,
        args: tuple[Any, ...] = (),
        kwargs: dict | None = None,
    ) -> T:
        """
        Execute with graceful degradation.

        Args:
            security_context: Security context
            preferred_level: Preferred service level
            args: Function arguments
            kwargs: Function keyword arguments

        Returns:
            Result from available service level

        Example:
            ```python
            result = await degradation.execute(
                preferred_level=DegradationLevel.FULL,
                security_context=context,
            )
            ```
        """
        kwargs = kwargs or {}

        # Try levels in order of degradation
        levels_to_try = self._get_degradation_order(preferred_level)

        for level in levels_to_try:
            if level in self._levels:
                try:
                    logger.info(f"Attempting service level: {level.value}")
                    func = self._levels[level]
                    result = await func(*args, **kwargs)
                    self._current_level = level
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
                        f"Service level {level.value} failed: {e!s}",
                        extra={"level": level.value, "exception": str(e)},
                    )

        raise RuntimeError("No service levels available")

    def _get_degradation_order(
        self,
        preferred: DegradationLevel,
    ) -> list[DegradationLevel]:
        """
        Get degradation order starting from the preferred level.

        Returns a list of degradation levels in order of preference,
        starting from the specified level and cascading down to the
        most minimal service levels.

        Args:
            preferred: The preferred starting degradation level.

        Returns:
            List of DegradationLevel values in fallback order.
        """
        order_map = {
            DegradationLevel.FULL: [
                DegradationLevel.FULL,
                DegradationLevel.REDUCED,
                DegradationLevel.MINIMAL,
                DegradationLevel.EMERGENCY,
            ],
            DegradationLevel.REDUCED: [
                DegradationLevel.REDUCED,
                DegradationLevel.MINIMAL,
                DegradationLevel.EMERGENCY,
            ],
            DegradationLevel.MINIMAL: [
                DegradationLevel.MINIMAL,
                DegradationLevel.EMERGENCY,
            ],
            DegradationLevel.EMERGENCY: [
                DegradationLevel.EMERGENCY,
            ],
        }

        return order_map.get(preferred, [DegradationLevel.EMERGENCY])

    async def get_current_level(self) -> DegradationLevel:
        """
        Get current degradation level.

        Returns:
            The current DegradationLevel after the last execution.
        """
        return self._current_level
