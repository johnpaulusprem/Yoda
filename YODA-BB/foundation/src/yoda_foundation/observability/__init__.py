"""
OpenTelemetry Observability module for the Agentic AI Component Library.

This module provides comprehensive observability capabilities including:
- Distributed tracing with OpenTelemetry
- Metrics collection (counters, histograms, gauges)
- Structured logging with trace context
- Context propagation for distributed systems
- Auto-instrumentation for library components

The module supports graceful degradation when OpenTelemetry is not installed,
allowing code to use observability features without hard dependencies.

Example:
    ```python
    from yoda_foundation.observability import (
        # Configuration
        ObservabilityConfig,
        TracingConfig,
        MetricsConfig,
        LoggingConfig,
        ExporterType,
        # Tracing
        AgentTracer,
        traced,
        get_tracer,
        set_tracer,
        SpanStatus,
        SpanKind,
        # Metrics
        AgentMetrics,
        get_metrics,
        set_metrics,
        # Logging
        TracedLogger,
        get_logger,
        configure_logging,
        # Propagation
        TraceContextPropagator,
        BaggagePropagator,
        CompositePropagator,
        inject_context,
        extract_context,
        # Middleware
        observable,
        TracingMiddleware,
        MetricsMiddleware,
        # Instrumentation
        instrument_all,
        uninstrument_all,
        AgentInstrumentor,
        ToolInstrumentor,
        LLMInstrumentor,
        RAGInstrumentor,
        # Span attributes
        AgentSpanAttributes,
        LLMSpanAttributes,
        ToolSpanAttributes,
        RAGSpanAttributes,
        # Exporters
        create_trace_exporter,
        create_metrics_exporter,
    )

    # Initialize observability
    config = ObservabilityConfig(
        service_name="my-agent-service",
        tracing=TracingConfig(
            endpoint="http://jaeger:4317",
            exporter_type=ExporterType.OTLP,
        ),
        metrics=MetricsConfig(
            endpoint="http://prometheus:4317",
        ),
    )

    tracer = AgentTracer(config.tracing)
    set_tracer(tracer)

    metrics = AgentMetrics(config.metrics)
    set_metrics(metrics)

    logger = TracedLogger("my_agent", config.logging)

    # Use decorator for automatic instrumentation
    @observable("process_request", collect_metrics=True, trace=True)
    async def process_request(request):
        with tracer.span("validate") as span:
            span.set_attribute("request.size", len(request))
            # ... validation logic

        logger.info("Processing request", request_id=request.id)
        return result

    # Pre-defined metrics
    metrics.agent_requests_total.add(1, {"agent": "summarizer"})
    metrics.agent_request_duration_seconds.record(0.5, {"agent": "summarizer"})

    # Auto-instrument all components
    instrument_all()
    ```

Quick Start:
    1. Create configuration using ObservabilityConfig
    2. Initialize tracer, metrics, and logger
    3. Use decorators (@traced, @observable) or context managers
    4. Call instrument_all() for automatic instrumentation

Dependencies:
    Required: None (graceful degradation when OpenTelemetry not installed)
    Optional:
    - opentelemetry-sdk: Base SDK for tracing and metrics
    - opentelemetry-exporter-otlp-proto-grpc: OTLP exporter
    - opentelemetry-exporter-jaeger: Jaeger exporter
    - opentelemetry-exporter-zipkin-json: Zipkin exporter
"""

# Configuration
from yoda_foundation.observability.config import (
    ExporterType,
    LoggingConfig,
    MetricsConfig,
    ObservabilityConfig,
    SamplerType,
    TracingConfig,
)

# Exporters
from yoda_foundation.observability.exporters import (
    NoOpExporter,
    check_exporter_requirements,
    create_log_exporter,
    create_metrics_exporter,
    create_trace_exporter,
    get_available_exporters,
)

# Instrumentation
from yoda_foundation.observability.instrumentor import (
    AgentInstrumentor,
    BaseInstrumentor,
    HTTPInstrumentor,
    InstrumentorConfig,
    LLMInstrumentor,
    RAGInstrumentor,
    ToolInstrumentor,
    get_instrumentor,
    instrument_all,
    uninstrument_all,
)

# Logging
from yoda_foundation.observability.logging import (
    JsonFormatter,
    LogRecord,
    TextFormatter,
    TracedLogger,
    configure_logging,
    get_default_logger,
    get_logger,
)

# Metrics
from yoda_foundation.observability.metrics import (
    AgentMetrics,
    NoOpCounter,
    NoOpGauge,
    NoOpHistogram,
    NoOpUpDownCounter,
    get_metrics,
    set_metrics,
)

# Middleware
from yoda_foundation.observability.middleware import (
    CombinedMiddleware,
    MetricsMiddleware,
    MiddlewareConfig,
    TracingMiddleware,
    observable,
)

# Propagation
from yoda_foundation.observability.propagation import (
    BaggagePropagator,
    CompositePropagator,
    Propagator,
    TraceContextPropagator,
    extract_context,
    get_propagator,
    inject_context,
    set_propagator,
)

# Span attributes and conventions
from yoda_foundation.observability.spans import (
    AgentSpanAttributes,
    LLMSpanAttributes,
    RAGSpanAttributes,
    SpanContext,
    SpanKind,
    ToolSpanAttributes,
    create_agent_span_attributes,
    create_llm_span_attributes,
    create_rag_span_attributes,
    create_tool_span_attributes,
)

# Tracing
from yoda_foundation.observability.tracer import (
    AgentTracer,
    NoOpSpan,
    SpanStatus,
    get_tracer,
    set_tracer,
    traced,
)


__all__ = [
    # Configuration
    "ObservabilityConfig",
    "TracingConfig",
    "MetricsConfig",
    "LoggingConfig",
    "ExporterType",
    "SamplerType",
    # Tracing
    "AgentTracer",
    "traced",
    "get_tracer",
    "set_tracer",
    "SpanStatus",
    "SpanKind",
    "SpanContext",
    "NoOpSpan",
    # Metrics
    "AgentMetrics",
    "get_metrics",
    "set_metrics",
    "NoOpCounter",
    "NoOpHistogram",
    "NoOpGauge",
    "NoOpUpDownCounter",
    # Logging
    "TracedLogger",
    "LogRecord",
    "JsonFormatter",
    "TextFormatter",
    "get_logger",
    "get_default_logger",
    "configure_logging",
    # Propagation
    "Propagator",
    "TraceContextPropagator",
    "BaggagePropagator",
    "CompositePropagator",
    "get_propagator",
    "set_propagator",
    "inject_context",
    "extract_context",
    # Middleware
    "observable",
    "TracingMiddleware",
    "MetricsMiddleware",
    "CombinedMiddleware",
    "MiddlewareConfig",
    # Instrumentation
    "BaseInstrumentor",
    "AgentInstrumentor",
    "ToolInstrumentor",
    "LLMInstrumentor",
    "RAGInstrumentor",
    "HTTPInstrumentor",
    "InstrumentorConfig",
    "instrument_all",
    "uninstrument_all",
    "get_instrumentor",
    # Span attributes
    "AgentSpanAttributes",
    "LLMSpanAttributes",
    "ToolSpanAttributes",
    "RAGSpanAttributes",
    "create_agent_span_attributes",
    "create_llm_span_attributes",
    "create_tool_span_attributes",
    "create_rag_span_attributes",
    # Exporters
    "create_trace_exporter",
    "create_metrics_exporter",
    "create_log_exporter",
    "get_available_exporters",
    "check_exporter_requirements",
    "NoOpExporter",
]
