"""
Distributed tracing for the Agentic AI Component Library.

This module provides a tracer implementation that wraps OpenTelemetry
with graceful degradation when the SDK is not installed.

Example:
    ```python
    from yoda_foundation.observability import (
        AgentTracer,
        TracingConfig,
        traced,
    )

    # Initialize tracer
    config = TracingConfig(
        service_name="my-agent",
        endpoint="http://jaeger:4317",
    )
    tracer = AgentTracer(config)

    # Use context manager
    async with tracer.span("process_request") as span:
        span.set_attribute("request.id", "req_123")
        result = await do_work()
        span.add_event("work_completed", {"items_processed": 10})

    # Use decorator
    @traced("handle_message")
    async def handle_message(message: str) -> str:
        return process(message)
    ```
"""

from __future__ import annotations

import asyncio
import functools
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import (
    Any,
    TypeVar,
)

from yoda_foundation.observability.config import ExporterType, TracingConfig
from yoda_foundation.observability.spans import SpanContext, SpanKind


# Type variable for decorators
F = TypeVar("F", bound=Callable[..., Any])

# Try to import OpenTelemetry
_OTEL_AVAILABLE = False
try:
    from opentelemetry import trace as otel_trace
    from opentelemetry.context import Context
    from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    from opentelemetry.trace import SpanKind as OtelSpanKind
    from opentelemetry.trace import Status, StatusCode

    _OTEL_AVAILABLE = True
except ImportError:
    otel_trace = None
    OtelSpanKind = None
    TracerProvider = None
    BatchSpanProcessor = None
    ConsoleSpanExporter = None
    Resource = None
    SERVICE_NAME = None
    SERVICE_VERSION = None
    Context = None


class SpanStatus(Enum):
    """Status of a span."""

    UNSET = "unset"
    OK = "ok"
    ERROR = "error"


@dataclass
class SpanEvent:
    """An event recorded on a span."""

    name: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class NoOpSpan:
    """
    No-operation span for when OpenTelemetry is not available.

    Provides the same interface as a real span but does nothing.
    This allows code to use tracing without checking if it's available.
    """

    name: str
    kind: SpanKind = SpanKind.INTERNAL
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[SpanEvent] = field(default_factory=list)
    status: SpanStatus = SpanStatus.UNSET
    status_description: str | None = None
    _start_time: float = field(default_factory=time.time)
    _end_time: float | None = None
    _trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    _span_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    _parent_span_id: str | None = None
    _exception: Exception | None = None

    def set_attribute(self, key: str, value: Any) -> None:
        """Set a span attribute."""
        self.attributes[key] = value

    def set_attributes(self, attributes: dict[str, Any]) -> None:
        """Set multiple span attributes."""
        self.attributes.update(attributes)

    def add_event(
        self,
        name: str,
        attributes: dict[str, Any] | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        """Add an event to the span."""
        self.events.append(
            SpanEvent(
                name=name,
                timestamp=timestamp or datetime.now(UTC),
                attributes=attributes or {},
            )
        )

    def set_status(
        self,
        status: SpanStatus,
        description: str | None = None,
    ) -> None:
        """Set the span status."""
        self.status = status
        self.status_description = description

    def record_exception(
        self,
        exception: Exception,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        """Record an exception on the span."""
        self._exception = exception
        self.status = SpanStatus.ERROR
        self.status_description = str(exception)
        self.add_event(
            "exception",
            attributes={
                "exception.type": type(exception).__name__,
                "exception.message": str(exception),
                **(attributes or {}),
            },
        )

    def end(self, end_time: float | None = None) -> None:
        """End the span."""
        self._end_time = end_time or time.time()

    def get_span_context(self) -> SpanContext:
        """Get the span context."""
        return SpanContext(
            trace_id=self._trace_id,
            span_id=self._span_id,
            trace_flags=1,
        )

    @property
    def is_recording(self) -> bool:
        """Check if the span is recording."""
        return self._end_time is None

    @property
    def duration_ms(self) -> float:
        """Get the span duration in milliseconds."""
        end = self._end_time or time.time()
        return (end - self._start_time) * 1000

    def __enter__(self) -> NoOpSpan:
        """Enter context manager."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit context manager."""
        if exc_val is not None:
            self.record_exception(exc_val)
        self.end()


class AgentTracer:
    """
    Tracer for agent operations with OpenTelemetry support.

    Provides distributed tracing capabilities with graceful degradation
    when OpenTelemetry is not available.

    Attributes:
        config: Tracing configuration
        _tracer: Underlying OpenTelemetry tracer (if available)
        _enabled: Whether tracing is enabled

    Example:
        ```python
        config = TracingConfig(
            service_name="my-agent",
            endpoint="http://jaeger:4317",
            exporter_type=ExporterType.OTLP,
        )
        tracer = AgentTracer(config)

        # Create spans
        async with tracer.span("operation") as span:
            span.set_attribute("key", "value")
            await do_work()

        # Get current span
        current = tracer.current_span()
        if current:
            current.add_event("checkpoint")
        ```
    """

    def __init__(self, config: TracingConfig | None = None) -> None:
        """
        Initialize the tracer.

        Args:
            config: Tracing configuration

        Example:
            ```python
            tracer = AgentTracer(TracingConfig(
                service_name="agent-service",
                endpoint="http://jaeger:4317",
            ))
            ```
        """
        self.config = config or TracingConfig()
        self._enabled = self.config.enabled and _OTEL_AVAILABLE
        self._tracer: Any = None
        self._provider: Any = None

        if self._enabled:
            self._setup_tracer()

    def _setup_tracer(self) -> None:
        """Set up the OpenTelemetry tracer."""
        if not _OTEL_AVAILABLE:
            return

        # Create resource
        resource = Resource.create(
            {
                SERVICE_NAME: self.config.service_name,
                **self.config.resource_attributes,
            }
        )

        # Create provider
        self._provider = TracerProvider(resource=resource)

        # Create exporter based on config
        exporter = self._create_exporter()
        if exporter:
            processor = BatchSpanProcessor(
                exporter,
                max_queue_size=self.config.max_queue_size,
                max_export_batch_size=self.config.batch_size,
                export_timeout_millis=self.config.export_timeout_ms,
            )
            self._provider.add_span_processor(processor)

        # Set as global provider
        otel_trace.set_tracer_provider(self._provider)

        # Get tracer
        self._tracer = otel_trace.get_tracer(
            self.config.service_name,
            schema_url="https://opentelemetry.io/schemas/1.21.0",
        )

    def _create_exporter(self) -> Any:
        """Create the appropriate exporter based on configuration."""
        if not _OTEL_AVAILABLE:
            return None

        if self.config.exporter_type == ExporterType.CONSOLE:
            return ConsoleSpanExporter()

        elif self.config.exporter_type == ExporterType.OTLP:
            try:
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                    OTLPSpanExporter,
                )

                return OTLPSpanExporter(
                    endpoint=self.config.endpoint,
                    headers=self.config.headers or None,
                    timeout=self.config.export_timeout_ms // 1000,
                )
            except ImportError:
                # Fall back to console if OTLP not installed
                return ConsoleSpanExporter()

        elif self.config.exporter_type == ExporterType.JAEGER:
            try:
                from opentelemetry.exporter.jaeger.thrift import JaegerExporter

                return JaegerExporter(
                    collector_endpoint=self.config.endpoint,
                )
            except ImportError:
                return ConsoleSpanExporter()

        elif self.config.exporter_type == ExporterType.ZIPKIN:
            try:
                from opentelemetry.exporter.zipkin.json import ZipkinExporter

                return ZipkinExporter(endpoint=self.config.endpoint)
            except ImportError:
                return ConsoleSpanExporter()

        elif self.config.exporter_type == ExporterType.NONE:
            return None

        return ConsoleSpanExporter()

    def _convert_span_kind(self, kind: SpanKind) -> Any:
        """Convert SpanKind to OpenTelemetry SpanKind."""
        if not _OTEL_AVAILABLE:
            return None

        mapping = {
            SpanKind.INTERNAL: OtelSpanKind.INTERNAL,
            SpanKind.CLIENT: OtelSpanKind.CLIENT,
            SpanKind.SERVER: OtelSpanKind.SERVER,
            SpanKind.PRODUCER: OtelSpanKind.PRODUCER,
            SpanKind.CONSUMER: OtelSpanKind.CONSUMER,
        }
        return mapping.get(kind, OtelSpanKind.INTERNAL)

    def start_span(
        self,
        name: str,
        kind: SpanKind = SpanKind.INTERNAL,
        attributes: dict[str, Any] | None = None,
        parent: SpanContext | None = None,
    ) -> Any | NoOpSpan:
        """
        Start a new span.

        Args:
            name: Name of the span
            kind: Kind of span
            attributes: Initial attributes
            parent: Parent span context (optional)

        Returns:
            A span object (OpenTelemetry span or NoOpSpan)

        Example:
            ```python
            span = tracer.start_span(
                "process_document",
                kind=SpanKind.INTERNAL,
                attributes={"document.id": "doc_123"},
            )
            try:
                result = process()
                span.set_status(SpanStatus.OK)
            except (RuntimeError, ConnectionError, TimeoutError, OSError) as e:
                span.record_exception(e)
                raise
            finally:
                span.end()
            ```
        """
        if not self._enabled or self._tracer is None:
            return NoOpSpan(
                name=name,
                kind=kind,
                attributes=attributes or {},
            )

        otel_kind = self._convert_span_kind(kind)

        # Handle parent context
        context = None
        if parent and _OTEL_AVAILABLE:
            # Create context from parent span context
            pass  # OpenTelemetry handles parent context automatically

        span = self._tracer.start_span(
            name=name,
            kind=otel_kind,
            attributes=attributes,
            context=context,
        )

        return span

    @contextmanager
    def span(
        self,
        name: str,
        kind: SpanKind = SpanKind.INTERNAL,
        attributes: dict[str, Any] | None = None,
    ) -> Iterator[Any | NoOpSpan]:
        """
        Create a span as a context manager (sync).

        Args:
            name: Name of the span
            kind: Kind of span
            attributes: Initial attributes

        Yields:
            A span object

        Example:
            ```python
            with tracer.span("process_item") as span:
                span.set_attribute("item.id", "item_123")
                result = process_item()
            ```
        """
        if not self._enabled or self._tracer is None:
            span = NoOpSpan(name=name, kind=kind, attributes=attributes or {})
            try:
                yield span
            except BaseException as e:  # Intentionally broad: instrumentation catch-record-reraise
                span.record_exception(e)
                raise
            finally:
                span.end()
            return

        otel_kind = self._convert_span_kind(kind)

        with self._tracer.start_as_current_span(
            name=name,
            kind=otel_kind,
            attributes=attributes,
        ) as span:
            try:
                yield span
            except BaseException as e:  # Intentionally broad: instrumentation catch-record-reraise
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                raise

    @asynccontextmanager
    async def async_span(
        self,
        name: str,
        kind: SpanKind = SpanKind.INTERNAL,
        attributes: dict[str, Any] | None = None,
    ) -> AsyncIterator[Any | NoOpSpan]:
        """
        Create a span as an async context manager.

        Args:
            name: Name of the span
            kind: Kind of span
            attributes: Initial attributes

        Yields:
            A span object

        Example:
            ```python
            async with tracer.async_span("async_operation") as span:
                span.set_attribute("operation.type", "fetch")
                result = await fetch_data()
            ```
        """
        if not self._enabled or self._tracer is None:
            span = NoOpSpan(name=name, kind=kind, attributes=attributes or {})
            try:
                yield span
            except BaseException as e:  # Intentionally broad: instrumentation catch-record-reraise
                span.record_exception(e)
                raise
            finally:
                span.end()
            return

        otel_kind = self._convert_span_kind(kind)

        with self._tracer.start_as_current_span(
            name=name,
            kind=otel_kind,
            attributes=attributes,
        ) as span:
            try:
                yield span
            except BaseException as e:  # Intentionally broad: instrumentation catch-record-reraise
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                raise

    def current_span(self) -> Any | NoOpSpan | None:
        """
        Get the current active span.

        Returns:
            The current span or None if no span is active

        Example:
            ```python
            span = tracer.current_span()
            if span:
                span.add_event("checkpoint_reached")
            ```
        """
        if not self._enabled or not _OTEL_AVAILABLE:
            return None

        return otel_trace.get_current_span()

    def add_event(
        self,
        name: str,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        """
        Add an event to the current span.

        Args:
            name: Event name
            attributes: Event attributes

        Example:
            ```python
            tracer.add_event("cache_miss", {"key": "user_123"})
            ```
        """
        span = self.current_span()
        if span:
            span.add_event(name, attributes=attributes)

    def set_attribute(self, key: str, value: Any) -> None:
        """
        Set an attribute on the current span.

        Args:
            key: Attribute key
            value: Attribute value

        Example:
            ```python
            tracer.set_attribute("user.id", "user_123")
            ```
        """
        span = self.current_span()
        if span:
            span.set_attribute(key, value)

    def set_status(
        self,
        status: SpanStatus,
        description: str | None = None,
    ) -> None:
        """
        Set the status of the current span.

        Args:
            status: Span status
            description: Optional status description

        Example:
            ```python
            tracer.set_status(SpanStatus.OK)
            # or
            tracer.set_status(SpanStatus.ERROR, "Request failed")
            ```
        """
        span = self.current_span()
        if span is None:
            return

        if isinstance(span, NoOpSpan):
            span.set_status(status, description)
        elif _OTEL_AVAILABLE:
            status_code = {
                SpanStatus.UNSET: StatusCode.UNSET,
                SpanStatus.OK: StatusCode.OK,
                SpanStatus.ERROR: StatusCode.ERROR,
            }.get(status, StatusCode.UNSET)
            span.set_status(Status(status_code, description))

    def record_exception(
        self,
        exception: Exception,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        """
        Record an exception on the current span.

        Args:
            exception: The exception to record
            attributes: Additional attributes

        Example:
            ```python
            try:
                risky_operation()
            except (RuntimeError, ConnectionError, TimeoutError, OSError) as e:
                tracer.record_exception(e)
                raise
            ```
        """
        span = self.current_span()
        if span:
            span.record_exception(exception, attributes=attributes)
            if isinstance(span, NoOpSpan):
                span.set_status(SpanStatus.ERROR, str(exception))
            elif _OTEL_AVAILABLE:
                span.set_status(Status(StatusCode.ERROR, str(exception)))

    def inject_context(self, carrier: dict[str, str]) -> dict[str, str]:
        """
        Inject trace context into a carrier for propagation.

        Args:
            carrier: Dictionary to inject context into

        Returns:
            The carrier with injected context

        Example:
            ```python
            headers = {}
            tracer.inject_context(headers)
            # headers now contains trace context
            await http_client.post(url, headers=headers)
            ```
        """
        if not _OTEL_AVAILABLE:
            # Create a basic trace context for propagation
            span = self.current_span()
            if isinstance(span, NoOpSpan):
                carrier["traceparent"] = f"00-{span._trace_id}-{span._span_id}-01"
            return carrier

        from opentelemetry.propagate import inject

        inject(carrier)
        return carrier

    def extract_context(self, carrier: dict[str, str]) -> SpanContext | None:
        """
        Extract trace context from a carrier.

        Args:
            carrier: Dictionary containing trace context

        Returns:
            Extracted span context or None

        Example:
            ```python
            # Extract context from incoming request headers
            context = tracer.extract_context(request.headers)
            async with tracer.async_span("handle_request", parent=context) as span:
                await process_request()
            ```
        """
        if not _OTEL_AVAILABLE:
            # Parse basic traceparent header
            traceparent = carrier.get("traceparent", "")
            if traceparent:
                parts = traceparent.split("-")
                if len(parts) >= 4:
                    return SpanContext(
                        trace_id=parts[1],
                        span_id=parts[2],
                        trace_flags=int(parts[3], 16),
                        is_remote=True,
                    )
            return None

        from opentelemetry.propagate import extract

        context = extract(carrier)
        span_context = otel_trace.get_current_span(context).get_span_context()

        if span_context.is_valid:
            return SpanContext(
                trace_id=format(span_context.trace_id, "032x"),
                span_id=format(span_context.span_id, "016x"),
                trace_flags=span_context.trace_flags,
                trace_state=str(span_context.trace_state) if span_context.trace_state else None,
                is_remote=span_context.is_remote,
            )

        return None

    def get_trace_id(self) -> str | None:
        """
        Get the current trace ID.

        Returns:
            The trace ID as a hex string or None

        Example:
            ```python
            trace_id = tracer.get_trace_id()
            logger.info("Processing request", extra={"trace_id": trace_id})
            ```
        """
        span = self.current_span()
        if span is None:
            return None

        if isinstance(span, NoOpSpan):
            return span._trace_id

        if _OTEL_AVAILABLE:
            ctx = span.get_span_context()
            if ctx.is_valid:
                return format(ctx.trace_id, "032x")

        return None

    def get_span_id(self) -> str | None:
        """
        Get the current span ID.

        Returns:
            The span ID as a hex string or None

        Example:
            ```python
            span_id = tracer.get_span_id()
            ```
        """
        span = self.current_span()
        if span is None:
            return None

        if isinstance(span, NoOpSpan):
            return span._span_id

        if _OTEL_AVAILABLE:
            ctx = span.get_span_context()
            if ctx.is_valid:
                return format(ctx.span_id, "016x")

        return None

    async def shutdown(self) -> None:
        """
        Shutdown the tracer and flush pending spans.

        Example:
            ```python
            # On application shutdown
            await tracer.shutdown()
            ```
        """
        if self._provider and _OTEL_AVAILABLE:
            self._provider.shutdown()

    @property
    def is_enabled(self) -> bool:
        """Check if tracing is enabled."""
        return self._enabled

    @property
    def is_otel_available(self) -> bool:
        """Check if OpenTelemetry is available."""
        return _OTEL_AVAILABLE


def traced(
    name: str | None = None,
    kind: SpanKind = SpanKind.INTERNAL,
    attributes: dict[str, Any] | None = None,
    record_exception: bool = True,
) -> Callable[[F], F]:
    """
    Decorator to trace a function or coroutine.

    Args:
        name: Span name (defaults to function name)
        kind: Span kind
        attributes: Static attributes to add to the span
        record_exception: Whether to record exceptions

    Returns:
        Decorated function

    Example:
        ```python
        @traced("process_document")
        async def process_document(doc_id: str) -> Document:
            return await fetch_and_process(doc_id)

        @traced(attributes={"component": "auth"})
        def validate_token(token: str) -> bool:
            return check_token(token)
        ```
    """

    def decorator(func: F) -> F:
        span_name = name or func.__name__

        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                # Get tracer from global or create NoOp
                tracer = _get_global_tracer()
                async with tracer.async_span(
                    span_name,
                    kind=kind,
                    attributes=attributes,
                ) as span:
                    try:
                        return await func(*args, **kwargs)
                    except (
                        BaseException
                    ) as e:  # Intentionally broad: instrumentation catch-record-reraise
                        if record_exception:
                            span.record_exception(e)
                        raise

            return async_wrapper  # type: ignore
        else:

            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                tracer = _get_global_tracer()
                with tracer.span(
                    span_name,
                    kind=kind,
                    attributes=attributes,
                ) as span:
                    try:
                        return func(*args, **kwargs)
                    except (
                        BaseException
                    ) as e:  # Intentionally broad: instrumentation catch-record-reraise
                        if record_exception:
                            span.record_exception(e)
                        raise

            return sync_wrapper  # type: ignore

    return decorator


# Global tracer instance
_global_tracer: AgentTracer | None = None


def get_tracer() -> AgentTracer:
    """
    Get the global tracer instance.

    Returns:
        The global AgentTracer instance

    Example:
        ```python
        tracer = get_tracer()
        with tracer.span("operation") as span:
            pass
        ```
    """
    global _global_tracer
    if _global_tracer is None:
        _global_tracer = AgentTracer()
    return _global_tracer


def set_tracer(tracer: AgentTracer) -> None:
    """
    Set the global tracer instance.

    Args:
        tracer: The tracer to set as global

    Example:
        ```python
        config = TracingConfig(
            service_name="my-service",
            endpoint="http://jaeger:4317",
        )
        tracer = AgentTracer(config)
        set_tracer(tracer)
        ```
    """
    global _global_tracer
    _global_tracer = tracer


def _get_global_tracer() -> AgentTracer:
    """Internal function to get or create global tracer."""
    return get_tracer()
