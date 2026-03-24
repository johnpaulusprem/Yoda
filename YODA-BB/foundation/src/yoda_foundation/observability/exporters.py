"""
Exporter factories for OpenTelemetry backends.

This module provides factory functions for creating trace, metrics, and log
exporters with support for multiple backends.

Example:
    ```python
    from yoda_foundation.observability import (
        create_trace_exporter,
        create_metrics_exporter,
        create_log_exporter,
        ExporterType,
    )
    from yoda_foundation.observability.config import TracingConfig

    # Create trace exporter
    config = TracingConfig(
        endpoint="http://jaeger:4317",
        exporter_type=ExporterType.OTLP,
    )
    exporter = create_trace_exporter(config)

    # Create metrics exporter
    metrics_exporter = create_metrics_exporter(metrics_config)

    # Create log exporter
    log_exporter = create_log_exporter(logging_config)
    ```
"""

from __future__ import annotations

from typing import Any

from yoda_foundation.observability.config import (
    ExporterType,
    LoggingConfig,
    MetricsConfig,
    TracingConfig,
)


# Try to import OpenTelemetry exporters
_OTEL_AVAILABLE = False
_OTLP_TRACE_AVAILABLE = False
_OTLP_METRICS_AVAILABLE = False
_JAEGER_AVAILABLE = False
_ZIPKIN_AVAILABLE = False

try:
    from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SpanExporter

    _OTEL_AVAILABLE = True
except ImportError:
    ConsoleSpanExporter = None
    SpanExporter = None

try:
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

    _OTLP_TRACE_AVAILABLE = True
except ImportError:
    OTLPSpanExporter = None

try:
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter

    _OTLP_METRICS_AVAILABLE = True
except ImportError:
    OTLPMetricExporter = None

try:
    from opentelemetry.exporter.jaeger.thrift import JaegerExporter

    _JAEGER_AVAILABLE = True
except ImportError:
    JaegerExporter = None

try:
    from opentelemetry.exporter.zipkin.json import ZipkinExporter

    _ZIPKIN_AVAILABLE = True
except ImportError:
    ZipkinExporter = None

try:
    from opentelemetry.sdk.metrics.export import (
        ConsoleMetricExporter,
        MetricExporter,
    )

    _METRICS_AVAILABLE = True
except ImportError:
    ConsoleMetricExporter = None
    MetricExporter = None
    _METRICS_AVAILABLE = False


class NoOpExporter:
    """
    No-operation exporter for when OpenTelemetry is not available.

    Accepts spans/metrics but does nothing with them.
    """

    def export(self, data: Any) -> None:
        """Export data (no-op)."""
        pass

    def shutdown(self) -> None:
        """Shutdown the exporter (no-op)."""
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Force flush (no-op)."""
        return True


def create_trace_exporter(
    config: TracingConfig,
) -> Any:
    """
    Create a trace exporter based on configuration.

    Supports OTLP, Jaeger, Zipkin, and Console exporters.
    Falls back to Console or NoOp if requested exporter is not available.

    Args:
        config: Tracing configuration

    Returns:
        Trace exporter instance

    Example:
        ```python
        config = TracingConfig(
            endpoint="http://jaeger:4317",
            exporter_type=ExporterType.OTLP,
        )
        exporter = create_trace_exporter(config)
        ```
    """
    if not _OTEL_AVAILABLE:
        return NoOpExporter()

    exporter_type = config.exporter_type

    if exporter_type == ExporterType.NONE:
        return NoOpExporter()

    if exporter_type == ExporterType.CONSOLE:
        return ConsoleSpanExporter()

    if exporter_type == ExporterType.OTLP:
        if not _OTLP_TRACE_AVAILABLE:
            # Log warning and fall back to console
            import logging

            logging.warning(
                "OTLP trace exporter not available. "
                "Install with: pip install opentelemetry-exporter-otlp-proto-grpc"
            )
            return ConsoleSpanExporter()

        return OTLPSpanExporter(
            endpoint=config.endpoint,
            headers=config.headers or None,
            timeout=config.export_timeout_ms // 1000,
        )

    if exporter_type == ExporterType.JAEGER:
        if not _JAEGER_AVAILABLE:
            import logging

            logging.warning(
                "Jaeger exporter not available. "
                "Install with: pip install opentelemetry-exporter-jaeger"
            )
            return ConsoleSpanExporter()

        # Parse endpoint for Jaeger
        # Jaeger expects collector_endpoint for Thrift
        return JaegerExporter(
            collector_endpoint=config.endpoint,
        )

    if exporter_type == ExporterType.ZIPKIN:
        if not _ZIPKIN_AVAILABLE:
            import logging

            logging.warning(
                "Zipkin exporter not available. "
                "Install with: pip install opentelemetry-exporter-zipkin-json"
            )
            return ConsoleSpanExporter()

        return ZipkinExporter(
            endpoint=config.endpoint,
        )

    # Default to console
    return ConsoleSpanExporter()


def create_metrics_exporter(
    config: MetricsConfig,
) -> Any:
    """
    Create a metrics exporter based on configuration.

    Supports OTLP and Console exporters.
    Falls back to Console or NoOp if requested exporter is not available.

    Args:
        config: Metrics configuration

    Returns:
        Metrics exporter instance

    Example:
        ```python
        config = MetricsConfig(
            endpoint="http://prometheus:4317",
            exporter_type=ExporterType.OTLP,
        )
        exporter = create_metrics_exporter(config)
        ```
    """
    if not _METRICS_AVAILABLE:
        return NoOpExporter()

    exporter_type = config.exporter_type

    if exporter_type == ExporterType.NONE:
        return NoOpExporter()

    if exporter_type == ExporterType.CONSOLE:
        return ConsoleMetricExporter()

    if exporter_type == ExporterType.OTLP:
        if not _OTLP_METRICS_AVAILABLE:
            import logging

            logging.warning(
                "OTLP metrics exporter not available. "
                "Install with: pip install opentelemetry-exporter-otlp-proto-grpc"
            )
            return ConsoleMetricExporter()

        return OTLPMetricExporter(
            endpoint=config.endpoint,
            headers=config.headers or None,
        )

    # Default to console
    return ConsoleMetricExporter()


def create_log_exporter(
    config: LoggingConfig,
) -> Any:
    """
    Create a log exporter based on configuration.

    Note: OpenTelemetry log export is still evolving.
    This currently returns a NoOp exporter for non-console types.

    Args:
        config: Logging configuration

    Returns:
        Log exporter instance

    Example:
        ```python
        config = LoggingConfig(
            endpoint="http://collector:4317",
            exporter_type=ExporterType.OTLP,
        )
        exporter = create_log_exporter(config)
        ```
    """
    if config.exporter_type == ExporterType.NONE:
        return NoOpExporter()

    if config.exporter_type == ExporterType.CONSOLE:
        # For console, we use Python's logging directly
        return NoOpExporter()

    if config.exporter_type == ExporterType.OTLP:
        # Try to use OTLP log exporter
        try:
            from opentelemetry.exporter.otlp.proto.grpc._log_exporter import (
                OTLPLogExporter,
            )

            return OTLPLogExporter(
                endpoint=config.endpoint,
            )
        except ImportError:
            import logging

            logging.warning(
                "OTLP log exporter not available. "
                "Install with: pip install opentelemetry-exporter-otlp-proto-grpc"
            )
            return NoOpExporter()

    return NoOpExporter()


def get_available_exporters() -> dict:
    """
    Get a dictionary of available exporters.

    Returns:
        Dictionary with exporter availability

    Example:
        ```python
        available = get_available_exporters()
        if available["otlp_trace"]:
            config.exporter_type = ExporterType.OTLP
        else:
            config.exporter_type = ExporterType.CONSOLE
        ```
    """
    return {
        "otel_base": _OTEL_AVAILABLE,
        "otlp_trace": _OTLP_TRACE_AVAILABLE,
        "otlp_metrics": _OTLP_METRICS_AVAILABLE,
        "jaeger": _JAEGER_AVAILABLE,
        "zipkin": _ZIPKIN_AVAILABLE,
        "metrics": _METRICS_AVAILABLE,
    }


def check_exporter_requirements(exporter_type: ExporterType) -> tuple[bool, str]:
    """
    Check if requirements for an exporter type are available.

    Args:
        exporter_type: The exporter type to check

    Returns:
        Tuple of (is_available, install_instructions)

    Example:
        ```python
        available, instructions = check_exporter_requirements(ExporterType.OTLP)
        if not available:
            print(f"Please install: {instructions}")
        ```
    """
    if exporter_type == ExporterType.CONSOLE:
        return _OTEL_AVAILABLE, "pip install opentelemetry-sdk"

    if exporter_type == ExporterType.NONE:
        return True, ""

    if exporter_type == ExporterType.OTLP:
        available = _OTLP_TRACE_AVAILABLE or _OTLP_METRICS_AVAILABLE
        return available, "pip install opentelemetry-exporter-otlp-proto-grpc"

    if exporter_type == ExporterType.JAEGER:
        return _JAEGER_AVAILABLE, "pip install opentelemetry-exporter-jaeger"

    if exporter_type == ExporterType.ZIPKIN:
        return _ZIPKIN_AVAILABLE, "pip install opentelemetry-exporter-zipkin-json"

    return False, "Unknown exporter type"
