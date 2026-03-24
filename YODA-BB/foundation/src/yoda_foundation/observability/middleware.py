"""
Middleware for automatic instrumentation of async functions.

This module provides middleware and decorators for automatically
adding tracing and metrics to functions and methods.

Example:
    ```python
    from yoda_foundation.observability import (
        observable,
        TracingMiddleware,
        MetricsMiddleware,
    )

    # Use decorator for automatic instrumentation
    @observable("process_request", collect_metrics=True, trace=True)
    async def process_request(request: Request) -> Response:
        return await handle(request)

    # Use middleware class
    middleware = TracingMiddleware(tracer)
    wrapped_func = middleware.wrap(my_function)
    result = await wrapped_func(arg1, arg2)
    ```
"""

from __future__ import annotations

import asyncio
import functools
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from yoda_foundation.observability.metrics import AgentMetrics, get_metrics
from yoda_foundation.observability.spans import SpanKind
from yoda_foundation.observability.tracer import (
    AgentTracer,
    NoOpSpan,
    SpanStatus,
    get_tracer,
)


# Type variable for decorators
F = TypeVar("F", bound=Callable[..., Any])


@dataclass
class MiddlewareConfig:
    """
    Configuration for middleware behavior.

    Attributes:
        trace_enabled: Whether to create spans
        metrics_enabled: Whether to collect metrics
        record_exceptions: Whether to record exceptions in spans
        record_arguments: Whether to record function arguments
        argument_max_length: Maximum length for argument values
        exclude_patterns: Patterns to exclude from instrumentation

    Example:
        ```python
        config = MiddlewareConfig(
            trace_enabled=True,
            metrics_enabled=True,
            record_arguments=True,
            argument_max_length=100,
        )
        ```
    """

    trace_enabled: bool = True
    metrics_enabled: bool = True
    record_exceptions: bool = True
    record_arguments: bool = False
    argument_max_length: int = 100
    exclude_patterns: list[str] = field(default_factory=list)


class TracingMiddleware:
    """
    Middleware for adding tracing to async functions.

    Wraps functions to automatically create spans for each invocation.

    Attributes:
        tracer: The tracer to use for creating spans
        config: Middleware configuration

    Example:
        ```python
        middleware = TracingMiddleware(tracer)

        # Wrap a function
        wrapped = middleware.wrap(my_async_function)
        result = await wrapped(arg1, arg2)

        # Or use as decorator
        @middleware.trace("operation_name")
        async def my_function():
            pass
        ```
    """

    def __init__(
        self,
        tracer: AgentTracer | None = None,
        config: MiddlewareConfig | None = None,
    ) -> None:
        """
        Initialize the tracing middleware.

        Args:
            tracer: Tracer to use (defaults to global tracer)
            config: Middleware configuration

        Example:
            ```python
            middleware = TracingMiddleware(
                tracer=my_tracer,
                config=MiddlewareConfig(record_arguments=True),
            )
            ```
        """
        self.tracer = tracer or get_tracer()
        self.config = config or MiddlewareConfig()

    def wrap(
        self,
        func: Callable[..., Any],
        name: str | None = None,
        kind: SpanKind = SpanKind.INTERNAL,
        attributes: dict[str, Any] | None = None,
    ) -> Callable[..., Any]:
        """
        Wrap a function with tracing.

        Args:
            func: Function to wrap
            name: Span name (defaults to function name)
            kind: Span kind
            attributes: Static attributes to add

        Returns:
            Wrapped function

        Example:
            ```python
            wrapped = middleware.wrap(my_function, name="custom_name")
            result = await wrapped(arg1, arg2)
            ```
        """
        span_name = name or func.__name__
        static_attrs = attributes or {}

        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                attrs = self._build_attributes(func, args, kwargs, static_attrs)

                async with self.tracer.async_span(
                    span_name,
                    kind=kind,
                    attributes=attrs,
                ) as span:
                    try:
                        result = await func(*args, **kwargs)
                        if isinstance(span, NoOpSpan):
                            span.set_status(SpanStatus.OK)
                        return result
                    except (
                        BaseException
                    ) as e:  # Intentionally broad: instrumentation catch-record-reraise
                        if self.config.record_exceptions:
                            span.record_exception(e)
                        raise

            return async_wrapper
        else:

            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                attrs = self._build_attributes(func, args, kwargs, static_attrs)

                with self.tracer.span(
                    span_name,
                    kind=kind,
                    attributes=attrs,
                ) as span:
                    try:
                        result = func(*args, **kwargs)
                        if isinstance(span, NoOpSpan):
                            span.set_status(SpanStatus.OK)
                        return result
                    except (
                        BaseException
                    ) as e:  # Intentionally broad: instrumentation catch-record-reraise
                        if self.config.record_exceptions:
                            span.record_exception(e)
                        raise

            return sync_wrapper

    def _build_attributes(
        self,
        func: Callable[..., Any],
        args: tuple,
        kwargs: dict,
        static_attrs: dict[str, Any],
    ) -> dict[str, Any]:
        """Build span attributes from function call."""
        attrs = {
            "code.function": func.__name__,
            "code.namespace": func.__module__ if hasattr(func, "__module__") else "",
            **static_attrs,
        }

        if self.config.record_arguments:
            # Record arguments (with truncation)
            for i, arg in enumerate(args):
                arg_str = str(arg)[: self.config.argument_max_length]
                attrs[f"code.args.{i}"] = arg_str

            for key, value in kwargs.items():
                value_str = str(value)[: self.config.argument_max_length]
                attrs[f"code.kwargs.{key}"] = value_str

        return attrs

    def trace(
        self,
        name: str | None = None,
        kind: SpanKind = SpanKind.INTERNAL,
        attributes: dict[str, Any] | None = None,
    ) -> Callable[[F], F]:
        """
        Decorator to add tracing to a function.

        Args:
            name: Span name (defaults to function name)
            kind: Span kind
            attributes: Static attributes to add

        Returns:
            Decorator function

        Example:
            ```python
            @middleware.trace("process_document")
            async def process_document(doc_id: str):
                pass
            ```
        """

        def decorator(func: F) -> F:
            return self.wrap(func, name=name, kind=kind, attributes=attributes)  # type: ignore

        return decorator


class MetricsMiddleware:
    """
    Middleware for adding metrics to async functions.

    Wraps functions to automatically collect timing and count metrics.

    Attributes:
        metrics: The metrics collector to use
        config: Middleware configuration

    Example:
        ```python
        middleware = MetricsMiddleware(metrics)

        # Wrap a function
        wrapped = middleware.wrap(my_async_function)
        result = await wrapped(arg1, arg2)
        ```
    """

    def __init__(
        self,
        metrics: AgentMetrics | None = None,
        config: MiddlewareConfig | None = None,
    ) -> None:
        """
        Initialize the metrics middleware.

        Args:
            metrics: Metrics collector to use (defaults to global)
            config: Middleware configuration

        Example:
            ```python
            middleware = MetricsMiddleware(
                metrics=my_metrics,
                config=MiddlewareConfig(metrics_enabled=True),
            )
            ```
        """
        self.metrics = metrics or get_metrics()
        self.config = config or MiddlewareConfig()

        # Create function-level metrics
        self._call_counter = self.metrics.counter(
            "function_calls_total",
            description="Total function calls",
            unit="1",
        )
        self._duration_histogram = self.metrics.histogram(
            "function_duration_seconds",
            description="Function execution duration",
            unit="s",
            boundaries=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
        )
        self._error_counter = self.metrics.counter(
            "function_errors_total",
            description="Total function errors",
            unit="1",
        )

    def wrap(
        self,
        func: Callable[..., Any],
        name: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> Callable[..., Any]:
        """
        Wrap a function with metrics collection.

        Args:
            func: Function to wrap
            name: Metric name prefix (defaults to function name)
            labels: Additional labels to add

        Returns:
            Wrapped function

        Example:
            ```python
            wrapped = middleware.wrap(my_function, labels={"component": "processor"})
            result = await wrapped(arg1, arg2)
            ```
        """
        metric_name = name or func.__name__
        static_labels = labels or {}

        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                labels = {"function": metric_name, **static_labels}
                start_time = time.perf_counter()

                try:
                    result = await func(*args, **kwargs)
                    labels["status"] = "success"
                    return result
                except (
                    BaseException
                ) as e:  # Intentionally broad: instrumentation catch-record-reraise
                    labels["status"] = "error"
                    labels["error_type"] = type(e).__name__
                    self._error_counter.add(1, labels)
                    raise
                finally:
                    duration = time.perf_counter() - start_time
                    self._call_counter.add(1, labels)
                    self._duration_histogram.record(
                        duration,
                        {"function": metric_name, **static_labels},
                    )

            return async_wrapper
        else:

            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                labels = {"function": metric_name, **static_labels}
                start_time = time.perf_counter()

                try:
                    result = func(*args, **kwargs)
                    labels["status"] = "success"
                    return result
                except (
                    BaseException
                ) as e:  # Intentionally broad: instrumentation catch-record-reraise
                    labels["status"] = "error"
                    labels["error_type"] = type(e).__name__
                    self._error_counter.add(1, labels)
                    raise
                finally:
                    duration = time.perf_counter() - start_time
                    self._call_counter.add(1, labels)
                    self._duration_histogram.record(
                        duration,
                        {"function": metric_name, **static_labels},
                    )

            return sync_wrapper

    def measure(
        self,
        name: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> Callable[[F], F]:
        """
        Decorator to add metrics to a function.

        Args:
            name: Metric name prefix (defaults to function name)
            labels: Additional labels to add

        Returns:
            Decorator function

        Example:
            ```python
            @middleware.measure("process_document")
            async def process_document(doc_id: str):
                pass
            ```
        """

        def decorator(func: F) -> F:
            return self.wrap(func, name=name, labels=labels)  # type: ignore

        return decorator


def observable(
    name: str | None = None,
    collect_metrics: bool = True,
    trace: bool = True,
    kind: SpanKind = SpanKind.INTERNAL,
    attributes: dict[str, Any] | None = None,
    labels: dict[str, str] | None = None,
    record_exceptions: bool = True,
) -> Callable[[F], F]:
    """
    Decorator to add both tracing and metrics to a function.

    Combines TracingMiddleware and MetricsMiddleware into a single decorator.

    Args:
        name: Operation name (defaults to function name)
        collect_metrics: Whether to collect metrics
        trace: Whether to create spans
        kind: Span kind
        attributes: Span attributes
        labels: Metric labels
        record_exceptions: Whether to record exceptions

    Returns:
        Decorator function

    Example:
        ```python
        @observable("process_request", collect_metrics=True, trace=True)
        async def process_request(request: Request) -> Response:
            return await handle(request)

        @observable(attributes={"component": "auth"}, labels={"service": "auth"})
        def validate_token(token: str) -> bool:
            return check_token(token)
        ```
    """

    def decorator(func: F) -> F:
        operation_name = name or func.__name__
        static_attrs = attributes or {}
        static_labels = labels or {}

        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                tracer = get_tracer()
                metrics = get_metrics()

                # Prepare metrics labels
                metric_labels = {"function": operation_name, **static_labels}
                start_time = time.perf_counter()

                # Create span context
                span_context = (
                    tracer.async_span(
                        operation_name,
                        kind=kind,
                        attributes=static_attrs,
                    )
                    if trace
                    else _no_op_context()
                )

                async with span_context as span:
                    try:
                        result = await func(*args, **kwargs)

                        if trace and isinstance(span, NoOpSpan):
                            span.set_status(SpanStatus.OK)

                        metric_labels["status"] = "success"
                        return result

                    except (
                        BaseException
                    ) as e:  # Intentionally broad: instrumentation catch-record-reraise
                        if trace:
                            if record_exceptions:
                                span.record_exception(e)

                        metric_labels["status"] = "error"
                        metric_labels["error_type"] = type(e).__name__

                        if collect_metrics:
                            metrics.agent_errors_total.add(
                                1,
                                {"component": operation_name, "error_type": type(e).__name__},
                            )
                        raise

                    finally:
                        duration = time.perf_counter() - start_time

                        if collect_metrics:
                            metrics.agent_requests_total.add(1, metric_labels)
                            metrics.agent_request_duration_seconds.record(
                                duration,
                                {"agent": operation_name},
                            )

            return async_wrapper  # type: ignore
        else:

            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                tracer = get_tracer()
                metrics = get_metrics()

                metric_labels = {"function": operation_name, **static_labels}
                start_time = time.perf_counter()

                span_context = (
                    tracer.span(
                        operation_name,
                        kind=kind,
                        attributes=static_attrs,
                    )
                    if trace
                    else _no_op_sync_context()
                )

                with span_context as span:
                    try:
                        result = func(*args, **kwargs)

                        if trace and isinstance(span, NoOpSpan):
                            span.set_status(SpanStatus.OK)

                        metric_labels["status"] = "success"
                        return result

                    except (
                        BaseException
                    ) as e:  # Intentionally broad: instrumentation catch-record-reraise
                        if trace:
                            if record_exceptions:
                                span.record_exception(e)

                        metric_labels["status"] = "error"
                        metric_labels["error_type"] = type(e).__name__

                        if collect_metrics:
                            metrics.agent_errors_total.add(
                                1,
                                {"component": operation_name, "error_type": type(e).__name__},
                            )
                        raise

                    finally:
                        duration = time.perf_counter() - start_time

                        if collect_metrics:
                            metrics.agent_requests_total.add(1, metric_labels)
                            metrics.agent_request_duration_seconds.record(
                                duration,
                                {"agent": operation_name},
                            )

            return sync_wrapper  # type: ignore

    return decorator


from contextlib import asynccontextmanager, contextmanager


@asynccontextmanager
async def _no_op_context():
    """No-op async context manager."""
    yield NoOpSpan(name="noop")


@contextmanager
def _no_op_sync_context():
    """No-op sync context manager."""
    yield NoOpSpan(name="noop")


class CombinedMiddleware:
    """
    Combined middleware that applies both tracing and metrics.

    Convenience class for using both middleware types together.

    Example:
        ```python
        middleware = CombinedMiddleware()

        @middleware.wrap("my_operation")
        async def my_operation():
            pass
        ```
    """

    def __init__(
        self,
        tracer: AgentTracer | None = None,
        metrics: AgentMetrics | None = None,
        config: MiddlewareConfig | None = None,
    ) -> None:
        """
        Initialize the combined middleware.

        Args:
            tracer: Tracer to use
            metrics: Metrics collector to use
            config: Middleware configuration
        """
        self.config = config or MiddlewareConfig()
        self._tracing = TracingMiddleware(tracer, self.config)
        self._metrics = MetricsMiddleware(metrics, self.config)

    def wrap(
        self,
        name: str | None = None,
        kind: SpanKind = SpanKind.INTERNAL,
        attributes: dict[str, Any] | None = None,
        labels: dict[str, str] | None = None,
    ) -> Callable[[F], F]:
        """
        Decorator to wrap a function with tracing and metrics.

        Args:
            name: Operation name
            kind: Span kind
            attributes: Span attributes
            labels: Metric labels

        Returns:
            Decorator function
        """

        def decorator(func: F) -> F:
            # Apply metrics first, then tracing (so span wraps the metrics call)
            wrapped = func
            if self.config.metrics_enabled:
                wrapped = self._metrics.wrap(wrapped, name=name, labels=labels)
            if self.config.trace_enabled:
                wrapped = self._tracing.wrap(wrapped, name=name, kind=kind, attributes=attributes)
            return wrapped  # type: ignore

        return decorator
