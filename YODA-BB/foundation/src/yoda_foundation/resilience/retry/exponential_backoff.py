"""
Exponential backoff strategy for retry mechanisms.

This module provides configurable exponential backoff with jitter
to prevent thundering herd problems.

Example:
    ```python
    from yoda_foundation.resilience.retry import ExponentialBackoff

    # Create backoff strategy
    backoff = ExponentialBackoff(
        base_delay_ms=100,
        max_delay_ms=30000,
        multiplier=2.0,
        jitter=True,
    )

    # Calculate delay for attempt
    delay_ms = backoff.get_delay(attempt=3)
    # With base=100, multiplier=2, attempt=3:
    # delay = 100 * (2 ** 3) = 800ms (plus jitter)
    ```
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from yoda_foundation.exceptions import ValidationError


@dataclass
class ExponentialBackoff:
    """
    Exponential backoff strategy with jitter.

    Calculates retry delays using exponential backoff algorithm
    to progressively increase wait time between retries. Includes
    optional jitter to prevent synchronized retries.

    Attributes:
        base_delay_ms: Base delay in milliseconds
        max_delay_ms: Maximum delay in milliseconds
        multiplier: Backoff multiplier (default 2.0)
        jitter: Whether to add random jitter (0-100% of delay)
        jitter_factor: Maximum jitter as fraction of delay (0.0 to 1.0)

    Example:
        ```python
        # Standard exponential backoff: 100ms, 200ms, 400ms, 800ms...
        backoff = ExponentialBackoff(
            base_delay_ms=100,
            max_delay_ms=10000,
            multiplier=2.0,
        )

        # With jitter to prevent thundering herd
        backoff = ExponentialBackoff(
            base_delay_ms=100,
            max_delay_ms=10000,
            jitter=True,
            jitter_factor=0.5,  # Up to 50% jitter
        )
        ```
    """

    base_delay_ms: int = 100
    max_delay_ms: int = 30000
    multiplier: float = 2.0
    jitter: bool = True
    jitter_factor: float = 0.5

    def __post_init__(self) -> None:
        """Validate backoff configuration."""
        if self.base_delay_ms <= 0:
            raise ValidationError(
                message=f"base_delay_ms must be positive, got {self.base_delay_ms}",
                field_name="base_delay_ms",
            )

        if self.max_delay_ms < self.base_delay_ms:
            raise ValidationError(
                message=f"max_delay_ms ({self.max_delay_ms}) must be >= base_delay_ms ({self.base_delay_ms})",
                field_name="max_delay_ms",
            )

        if self.multiplier <= 1.0:
            raise ValidationError(
                message=f"multiplier must be > 1.0, got {self.multiplier}",
                field_name="multiplier",
            )

        if self.jitter_factor < 0.0 or self.jitter_factor > 1.0:
            raise ValidationError(
                message=f"jitter_factor must be between 0.0 and 1.0, got {self.jitter_factor}",
                field_name="jitter_factor",
            )

    def get_delay(self, attempt: int) -> int:
        """
        Calculate delay for given retry attempt.

        Uses exponential backoff formula:
        delay = min(base_delay * (multiplier ** attempt), max_delay)

        If jitter is enabled, adds random variance:
        final_delay = delay * (1 + random(0, jitter_factor))

        Args:
            attempt: Retry attempt number (0-indexed)

        Returns:
            Delay in milliseconds

        Example:
            ```python
            backoff = ExponentialBackoff(base_delay_ms=100, multiplier=2.0)

            # First retry (attempt 0): 100ms
            delay0 = backoff.get_delay(0)

            # Second retry (attempt 1): 200ms
            delay1 = backoff.get_delay(1)

            # Third retry (attempt 2): 400ms
            delay2 = backoff.get_delay(2)
            ```
        """
        attempt = max(attempt, 0)

        # Calculate base exponential delay
        delay = self.base_delay_ms * (self.multiplier**attempt)

        # Cap at maximum
        delay = min(delay, self.max_delay_ms)

        # Add jitter if enabled
        if self.jitter:
            jitter_amount = delay * self.jitter_factor * random.random()
            delay = delay + jitter_amount

        return int(delay)

    def get_total_delay(self, attempts: int) -> int:
        """
        Calculate total delay for given number of attempts.

        Args:
            attempts: Number of attempts

        Returns:
            Total delay in milliseconds

        Example:
            ```python
            backoff = ExponentialBackoff(base_delay_ms=100, multiplier=2.0)

            # Total delay for 5 attempts
            total = backoff.get_total_delay(5)
            # 100 + 200 + 400 + 800 + 1600 = 3100ms (without jitter)
            ```
        """
        return sum(self.get_delay(i) for i in range(attempts))

    def __repr__(self) -> str:
        """Return string representation."""
        return (
            f"ExponentialBackoff("
            f"base={self.base_delay_ms}ms, "
            f"max={self.max_delay_ms}ms, "
            f"multiplier={self.multiplier}, "
            f"jitter={self.jitter})"
        )
