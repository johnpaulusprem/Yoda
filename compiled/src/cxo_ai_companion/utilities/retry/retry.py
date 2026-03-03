"""Tenacity-based retry utilities with sensible defaults.

Provides decorators for both async and sync callables, a ``RetryConfig``
dataclass for declarative configuration, and an async context-manager for
ad-hoc retry blocks.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import wraps
from typing import Any, AsyncIterator, Callable, TypeVar

from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


# ---------------------------------------------------------------------------
# RetryConfig
# ---------------------------------------------------------------------------

@dataclass
class RetryConfig:
    """Declarative retry configuration.

    Can be passed around and later applied via :func:`with_retry` /
    :func:`with_retry_sync`.
    """

    max_attempts: int = 3
    min_wait: float = 1.0
    max_wait: float = 60.0
    retry_on: tuple[type[Exception], ...] = (Exception,)
    log_retries: bool = True

    def as_decorator(self, *, is_async: bool = True) -> Callable[[F], F]:
        """Return the appropriate retry decorator pre-filled with this config."""
        if is_async:
            return with_retry(  # type: ignore[return-value]
                max_attempts=self.max_attempts,
                min_wait=self.min_wait,
                max_wait=self.max_wait,
                retry_on=self.retry_on,
                log_retries=self.log_retries,
            )
        return with_retry_sync(  # type: ignore[return-value]
            max_attempts=self.max_attempts,
            min_wait=self.min_wait,
            max_wait=self.max_wait,
            retry_on=self.retry_on,
            log_retries=self.log_retries,
        )


# ---------------------------------------------------------------------------
# Logging callback
# ---------------------------------------------------------------------------

def _build_before_sleep_log(
    log_retries: bool,
) -> Callable[[RetryCallState], None] | None:
    """Return a ``before_sleep`` callback that logs retry attempts."""
    if not log_retries:
        return None

    def _log(retry_state: RetryCallState) -> None:
        exception = (
            retry_state.outcome.exception() if retry_state.outcome else None
        )
        logger.warning(
            "Retrying %s (attempt %d/%s) after %s: %s",
            getattr(retry_state.fn, "__qualname__", retry_state.fn),
            retry_state.attempt_number,
            retry_state.retry_object.stop.max_attempt_number  # type: ignore[union-attr]
            if hasattr(retry_state.retry_object.stop, "max_attempt_number")
            else "?",
            type(exception).__name__ if exception else "unknown",
            exception,
        )

    return _log


# ---------------------------------------------------------------------------
# Async decorator
# ---------------------------------------------------------------------------

def with_retry(
    max_attempts: int = 3,
    min_wait: float = 1.0,
    max_wait: float = 60.0,
    retry_on: tuple[type[Exception], ...] = (Exception,),
    log_retries: bool = True,
) -> Callable[[F], F]:
    """Decorator for retrying **async** functions with exponential backoff.

    Parameters
    ----------
    max_attempts:
        Total number of attempts (including the initial call).
    min_wait:
        Minimum seconds to wait between retries.
    max_wait:
        Maximum seconds to wait between retries.
    retry_on:
        Exception types that should trigger a retry.
    log_retries:
        Emit a ``WARNING`` log on each retry.
    """

    def decorator(func: F) -> F:
        @wraps(func)
        @retry(
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(min=min_wait, max=max_wait),
            retry=retry_if_exception_type(retry_on),
            before_sleep=_build_before_sleep_log(log_retries),
            reraise=True,
        )
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Sync decorator
# ---------------------------------------------------------------------------

def with_retry_sync(
    max_attempts: int = 3,
    min_wait: float = 1.0,
    max_wait: float = 60.0,
    retry_on: tuple[type[Exception], ...] = (Exception,),
    log_retries: bool = True,
) -> Callable[[F], F]:
    """Decorator for retrying **sync** functions with exponential backoff.

    Same parameters as :func:`with_retry`.
    """

    def decorator(func: F) -> F:
        @wraps(func)
        @retry(
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(min=min_wait, max=max_wait),
            retry=retry_if_exception_type(retry_on),
            before_sleep=_build_before_sleep_log(log_retries),
            reraise=True,
        )
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Async context manager for ad-hoc retry blocks
# ---------------------------------------------------------------------------

@asynccontextmanager
async def retry_context(
    max_attempts: int = 3,
    min_wait: float = 1.0,
    max_wait: float = 60.0,
    retry_on: tuple[type[Exception], ...] = (Exception,),
    log_retries: bool = True,
) -> AsyncIterator[None]:
    """Async context manager that retries the enclosed block on failure.

    Usage::

        async with retry_context(max_attempts=3):
            await some_flaky_operation()

    Note: due to how Python context managers work the body executes only once
    per ``yield``.  This helper therefore wraps an internal retry loop and
    yields on each attempt.  If the final attempt also fails the exception
    propagates normally.
    """
    last_exception: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            yield
            return  # Success -- exit the context manager cleanly.
        except tuple(retry_on) as exc:
            last_exception = exc
            if attempt >= max_attempts:
                break
            if log_retries:
                logger.warning(
                    "retry_context: attempt %d/%d failed with %s: %s -- retrying.",
                    attempt,
                    max_attempts,
                    type(exc).__name__,
                    exc,
                )
            # Compute backoff delay using exponential wait.
            delay = min(min_wait * (2 ** (attempt - 1)), max_wait)
            await asyncio.sleep(delay)

    # All attempts exhausted.
    if last_exception is not None:
        raise last_exception
