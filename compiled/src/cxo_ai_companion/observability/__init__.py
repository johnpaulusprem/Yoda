"""Observability module — tracing, logging, metrics."""

from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from typing import Any

from cxo_ai_companion.observability.logging import (
    JsonFormatter, TextFormatter, TracedLogger, configure_logging, get_logger,
)
from cxo_ai_companion.observability.metrics import CXOMetrics, get_metrics, set_metrics
from cxo_ai_companion.observability.tracing import (
    AgentTracer, NoOpSpan, SpanStatus, get_tracer, set_tracer,
)


# ---------------------------------------------------------------------------
# Convenience wrappers used by services
# ---------------------------------------------------------------------------


@asynccontextmanager
async def trace_span(
    name: str, attributes: dict[str, Any] | None = None
) -> AsyncGenerator[NoOpSpan, None]:
    """Async context manager wrapping the global tracer's start_span."""
    with get_tracer().start_span(name, attributes) as span:
        yield span


class _MetricsProxy:
    """Dict-like proxy providing on-demand no-op metric access.

    Services use ``metrics["counter_name"].add(1)`` style calls.
    This proxy creates no-op counters/histograms for any key so
    services never fail even without OpenTelemetry.
    """

    def __getitem__(self, key: str) -> Any:
        from cxo_ai_companion.observability.metrics import NoOpCounter
        m = get_metrics()
        return getattr(m, key, NoOpCounter())

    def __getattr__(self, key: str) -> Any:
        from cxo_ai_companion.observability.metrics import NoOpCounter
        m = get_metrics()
        return getattr(m, key, NoOpCounter())


metrics = _MetricsProxy()


__all__ = [
    "AgentTracer", "NoOpSpan", "SpanStatus", "get_tracer", "set_tracer",
    "JsonFormatter", "TextFormatter", "TracedLogger", "configure_logging", "get_logger",
    "CXOMetrics", "get_metrics", "set_metrics",
    "trace_span", "metrics",
]
