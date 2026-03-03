"""OpenTelemetry tracing with graceful degradation."""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from contextlib import contextmanager
from enum import Enum
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


class SpanStatus(Enum):
    UNSET = "unset"
    OK = "ok"
    ERROR = "error"


class NoOpSpan:
    """No-op span when OpenTelemetry is not installed."""

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def set_status(self, status: SpanStatus, description: str | None = None) -> None:
        pass

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        pass

    def record_exception(self, exception: Exception) -> None:
        pass

    def end(self) -> None:
        pass

    def __enter__(self) -> NoOpSpan:
        return self

    def __exit__(self, *args: Any) -> None:
        pass


class AgentTracer:
    """OpenTelemetry tracer wrapper with graceful degradation."""

    def __init__(self, service_name: str = "cxo-ai-companion") -> None:
        self._service_name = service_name
        self._tracer: Any = None
        self._enabled = False

        try:
            from opentelemetry import trace
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.resources import Resource

            resource = Resource.create({"service.name": service_name})
            provider = TracerProvider(resource=resource)
            trace.set_tracer_provider(provider)
            self._tracer = trace.get_tracer(service_name)
            self._enabled = True
            logger.info("OpenTelemetry tracing enabled for %s", service_name)
        except ImportError:
            logger.info("OpenTelemetry not installed — tracing disabled")

    @contextmanager
    def start_span(self, name: str, attributes: dict[str, Any] | None = None):
        """Start a trace span."""
        if not self._enabled or self._tracer is None:
            yield NoOpSpan()
            return

        with self._tracer.start_as_current_span(name) as span:
            if attributes:
                for k, v in attributes.items():
                    span.set_attribute(k, str(v) if not isinstance(v, (str, int, float, bool)) else v)
            yield span

    def traced(self, name: str | None = None, attributes: dict[str, Any] | None = None) -> Callable[[F], F]:
        """Decorator for automatic function tracing."""
        def decorator(func: F) -> F:
            span_name = name or f"{func.__module__}.{func.__qualname__}"

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                with self.start_span(span_name, attributes) as span:
                    try:
                        result = await func(*args, **kwargs)
                        span.set_status(SpanStatus.OK)
                        return result
                    except Exception as e:
                        span.record_exception(e)
                        span.set_status(SpanStatus.ERROR, str(e))
                        raise

            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                with self.start_span(span_name, attributes) as span:
                    try:
                        result = func(*args, **kwargs)
                        span.set_status(SpanStatus.OK)
                        return result
                    except Exception as e:
                        span.record_exception(e)
                        span.set_status(SpanStatus.ERROR, str(e))
                        raise

            import asyncio
            if asyncio.iscoroutinefunction(func):
                return async_wrapper  # type: ignore[return-value]
            return sync_wrapper  # type: ignore[return-value]

        return decorator


_global_tracer: AgentTracer | None = None


def get_tracer() -> AgentTracer:
    global _global_tracer
    if _global_tracer is None:
        _global_tracer = AgentTracer()
    return _global_tracer


def set_tracer(tracer: AgentTracer) -> None:
    global _global_tracer
    _global_tracer = tracer
