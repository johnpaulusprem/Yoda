"""
Metrics collection for the Agentic AI Component Library.

This module provides metrics collection with OpenTelemetry support
and pre-defined metrics for agentic AI systems.

Example:
    ```python
    from yoda_foundation.observability import (
        AgentMetrics,
        MetricsConfig,
    )

    # Initialize metrics
    config = MetricsConfig(
        service_name="my-agent",
        endpoint="http://prometheus:4317",
    )
    metrics = AgentMetrics(config)

    # Use pre-defined metrics
    metrics.agent_requests_total.add(1, {"agent": "summarizer", "status": "success"})
    metrics.agent_request_duration_seconds.record(0.5, {"agent": "summarizer"})
    metrics.llm_request_duration_seconds.record(1.2, {"model": "gpt-4"})

    # Create custom metrics
    custom_counter = metrics.counter(
        "custom_events_total",
        description="Custom event counter",
        unit="1",
    )
    custom_counter.add(1, {"event_type": "user_action"})
    ```
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from yoda_foundation.observability.config import ExporterType, MetricsConfig


# Try to import OpenTelemetry metrics
_OTEL_METRICS_AVAILABLE = False
try:
    from opentelemetry import metrics as otel_metrics
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import (
        ConsoleMetricExporter,
        PeriodicExportingMetricReader,
    )
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource

    _OTEL_METRICS_AVAILABLE = True
except ImportError:
    otel_metrics = None
    MeterProvider = None
    ConsoleMetricExporter = None
    PeriodicExportingMetricReader = None
    Resource = None
    SERVICE_NAME = None


@dataclass
class MetricValue:
    """A single metric data point."""

    value: float
    labels: dict[str, str]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


class NoOpCounter:
    """No-operation counter for when OpenTelemetry is not available."""

    def __init__(self, name: str, description: str = "", unit: str = "1") -> None:
        self.name = name
        self.description = description
        self.unit = unit
        self._values: dict[tuple, float] = {}

    def add(
        self,
        amount: float,
        attributes: dict[str, str] | None = None,
    ) -> None:
        """Add to the counter."""
        key = tuple(sorted((attributes or {}).items()))
        self._values[key] = self._values.get(key, 0) + amount

    def get_value(self, attributes: dict[str, str] | None = None) -> float:
        """Get current counter value (for testing)."""
        key = tuple(sorted((attributes or {}).items()))
        return self._values.get(key, 0)


class NoOpHistogram:
    """No-operation histogram for when OpenTelemetry is not available."""

    def __init__(
        self,
        name: str,
        description: str = "",
        unit: str = "1",
        boundaries: list[float] | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.unit = unit
        self.boundaries = boundaries or [
            0.005,
            0.01,
            0.025,
            0.05,
            0.1,
            0.25,
            0.5,
            1.0,
            2.5,
            5.0,
            10.0,
        ]
        self._values: dict[tuple, list[float]] = {}

    def record(
        self,
        value: float,
        attributes: dict[str, str] | None = None,
    ) -> None:
        """Record a value in the histogram."""
        key = tuple(sorted((attributes or {}).items()))
        if key not in self._values:
            self._values[key] = []
        self._values[key].append(value)

    def get_values(self, attributes: dict[str, str] | None = None) -> list[float]:
        """Get recorded values (for testing)."""
        key = tuple(sorted((attributes or {}).items()))
        return self._values.get(key, [])


class NoOpGauge:
    """No-operation gauge for when OpenTelemetry is not available."""

    def __init__(
        self,
        name: str,
        description: str = "",
        unit: str = "1",
        callback: Callable[[], float] | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.unit = unit
        self._callback = callback
        self._values: dict[tuple, float] = {}

    def set(
        self,
        value: float,
        attributes: dict[str, str] | None = None,
    ) -> None:
        """Set the gauge value."""
        key = tuple(sorted((attributes or {}).items()))
        self._values[key] = value

    def get_value(self, attributes: dict[str, str] | None = None) -> float:
        """Get current gauge value."""
        if self._callback:
            return self._callback()
        key = tuple(sorted((attributes or {}).items()))
        return self._values.get(key, 0)


class NoOpUpDownCounter:
    """No-operation up/down counter for when OpenTelemetry is not available."""

    def __init__(self, name: str, description: str = "", unit: str = "1") -> None:
        self.name = name
        self.description = description
        self.unit = unit
        self._values: dict[tuple, float] = {}

    def add(
        self,
        amount: float,
        attributes: dict[str, str] | None = None,
    ) -> None:
        """Add to the counter (can be negative)."""
        key = tuple(sorted((attributes or {}).items()))
        self._values[key] = self._values.get(key, 0) + amount

    def get_value(self, attributes: dict[str, str] | None = None) -> float:
        """Get current counter value."""
        key = tuple(sorted((attributes or {}).items()))
        return self._values.get(key, 0)


class AgentMetrics:
    """
    Metrics collector for agent operations with OpenTelemetry support.

    Provides pre-defined metrics for agents, LLM calls, tools, and RAG
    operations, with graceful degradation when OpenTelemetry is not available.

    Attributes:
        config: Metrics configuration
        agent_requests_total: Total agent requests counter
        agent_request_duration_seconds: Agent request duration histogram
        agent_errors_total: Agent errors counter
        agent_tokens_used_total: Token usage counter
        agent_active_tasks: Active tasks gauge
        llm_request_duration_seconds: LLM request duration histogram
        tool_execution_duration_seconds: Tool execution duration histogram
        rag_retrieval_duration_seconds: RAG retrieval duration histogram

    Example:
        ```python
        metrics = AgentMetrics(config)

        # Record agent request
        metrics.agent_requests_total.add(1, {"agent": "summarizer"})

        # Record duration
        start = time.time()
        result = await agent.run()
        duration = time.time() - start
        metrics.agent_request_duration_seconds.record(duration, {"agent": "summarizer"})

        # Record errors
        metrics.agent_errors_total.add(1, {"agent": "summarizer", "error_type": "timeout"})
        ```
    """

    def __init__(self, config: MetricsConfig | None = None) -> None:
        """
        Initialize the metrics collector.

        Args:
            config: Metrics configuration

        Example:
            ```python
            metrics = AgentMetrics(MetricsConfig(
                service_name="agent-service",
                endpoint="http://prometheus:4317",
            ))
            ```
        """
        self.config = config or MetricsConfig()
        self._enabled = self.config.enabled and _OTEL_METRICS_AVAILABLE
        self._meter: Any = None
        self._provider: Any = None

        if self._enabled:
            self._setup_meter()

        # Initialize pre-defined metrics
        self._init_predefined_metrics()

    def _setup_meter(self) -> None:
        """Set up the OpenTelemetry meter."""
        if not _OTEL_METRICS_AVAILABLE:
            return

        # Create resource
        resource = Resource.create(
            {
                SERVICE_NAME: self.config.service_name,
                **self.config.resource_attributes,
            }
        )

        # Create exporter based on config
        exporter = self._create_exporter()

        # Create reader
        reader = PeriodicExportingMetricReader(
            exporter,
            export_interval_millis=self.config.export_interval_ms,
        )

        # Create provider
        self._provider = MeterProvider(
            resource=resource,
            metric_readers=[reader],
        )

        # Set as global provider
        otel_metrics.set_meter_provider(self._provider)

        # Get meter
        self._meter = otel_metrics.get_meter(
            self.config.service_name,
            schema_url="https://opentelemetry.io/schemas/1.21.0",
        )

    def _create_exporter(self) -> Any:
        """Create the appropriate exporter based on configuration."""
        if not _OTEL_METRICS_AVAILABLE:
            return None

        if self.config.exporter_type == ExporterType.CONSOLE:
            return ConsoleMetricExporter()

        elif self.config.exporter_type == ExporterType.OTLP:
            try:
                from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
                    OTLPMetricExporter,
                )

                return OTLPMetricExporter(
                    endpoint=self.config.endpoint,
                    headers=self.config.headers or None,
                )
            except ImportError:
                return ConsoleMetricExporter()

        elif self.config.exporter_type == ExporterType.NONE:
            return None

        return ConsoleMetricExporter()

    def _init_predefined_metrics(self) -> None:
        """Initialize pre-defined metrics for agent operations."""
        # Agent metrics
        self.agent_requests_total = self.counter(
            "agent_requests_total",
            description="Total number of agent requests",
            unit="1",
        )

        self.agent_request_duration_seconds = self.histogram(
            "agent_request_duration_seconds",
            description="Duration of agent requests in seconds",
            unit="s",
            boundaries=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0],
        )

        self.agent_errors_total = self.counter(
            "agent_errors_total",
            description="Total number of agent errors",
            unit="1",
        )

        self.agent_tokens_used_total = self.counter(
            "agent_tokens_used_total",
            description="Total number of tokens used by agents",
            unit="1",
        )

        self.agent_active_tasks = self.up_down_counter(
            "agent_active_tasks",
            description="Number of currently active agent tasks",
            unit="1",
        )

        self.agent_iterations_total = self.counter(
            "agent_iterations_total",
            description="Total number of agent iterations",
            unit="1",
        )

        # LLM metrics
        self.llm_request_duration_seconds = self.histogram(
            "llm_request_duration_seconds",
            description="Duration of LLM requests in seconds",
            unit="s",
            boundaries=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
        )

        self.llm_requests_total = self.counter(
            "llm_requests_total",
            description="Total number of LLM requests",
            unit="1",
        )

        self.llm_tokens_total = self.counter(
            "llm_tokens_total",
            description="Total number of LLM tokens (input + output)",
            unit="1",
        )

        self.llm_cost_cents_total = self.counter(
            "llm_cost_cents_total",
            description="Total LLM cost in cents",
            unit="cents",
        )

        self.llm_errors_total = self.counter(
            "llm_errors_total",
            description="Total number of LLM errors",
            unit="1",
        )

        # Tool metrics
        self.tool_execution_duration_seconds = self.histogram(
            "tool_execution_duration_seconds",
            description="Duration of tool executions in seconds",
            unit="s",
            boundaries=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
        )

        self.tool_executions_total = self.counter(
            "tool_executions_total",
            description="Total number of tool executions",
            unit="1",
        )

        self.tool_errors_total = self.counter(
            "tool_errors_total",
            description="Total number of tool errors",
            unit="1",
        )

        self.tool_cache_hits_total = self.counter(
            "tool_cache_hits_total",
            description="Total number of tool cache hits",
            unit="1",
        )

        # RAG metrics
        self.rag_retrieval_duration_seconds = self.histogram(
            "rag_retrieval_duration_seconds",
            description="Duration of RAG retrievals in seconds",
            unit="s",
            boundaries=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
        )

        self.rag_retrievals_total = self.counter(
            "rag_retrievals_total",
            description="Total number of RAG retrievals",
            unit="1",
        )

        self.rag_documents_retrieved_total = self.counter(
            "rag_documents_retrieved_total",
            description="Total number of documents retrieved",
            unit="1",
        )

        self.rag_embedding_duration_seconds = self.histogram(
            "rag_embedding_duration_seconds",
            description="Duration of RAG embeddings in seconds",
            unit="s",
            boundaries=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
        )

        # Memory metrics
        self.memory_operations_total = self.counter(
            "memory_operations_total",
            description="Total number of memory operations",
            unit="1",
        )

        self.memory_size_bytes = self.up_down_counter(
            "memory_size_bytes",
            description="Current memory usage in bytes",
            unit="bytes",
        )

    def counter(
        self,
        name: str,
        description: str = "",
        unit: str = "1",
    ) -> Any | NoOpCounter:
        """
        Create a counter metric.

        Args:
            name: Metric name
            description: Metric description
            unit: Metric unit

        Returns:
            Counter metric

        Example:
            ```python
            requests = metrics.counter(
                "http_requests_total",
                description="Total HTTP requests",
                unit="1",
            )
            requests.add(1, {"method": "GET", "status": "200"})
            ```
        """
        if not self._enabled or self._meter is None:
            return NoOpCounter(name, description, unit)

        return self._meter.create_counter(
            name=name,
            description=description,
            unit=unit,
        )

    def histogram(
        self,
        name: str,
        description: str = "",
        unit: str = "1",
        boundaries: list[float] | None = None,
    ) -> Any | NoOpHistogram:
        """
        Create a histogram metric.

        Args:
            name: Metric name
            description: Metric description
            unit: Metric unit
            boundaries: Histogram bucket boundaries

        Returns:
            Histogram metric

        Example:
            ```python
            latency = metrics.histogram(
                "request_latency_seconds",
                description="Request latency in seconds",
                unit="s",
                boundaries=[0.1, 0.5, 1.0, 5.0],
            )
            latency.record(0.35, {"endpoint": "/api/chat"})
            ```
        """
        if not self._enabled or self._meter is None:
            return NoOpHistogram(
                name,
                description,
                unit,
                boundaries or self.config.histogram_boundaries,
            )

        return self._meter.create_histogram(
            name=name,
            description=description,
            unit=unit,
        )

    def gauge(
        self,
        name: str,
        description: str = "",
        unit: str = "1",
        callback: Callable[[], float] | None = None,
    ) -> Any | NoOpGauge:
        """
        Create a gauge metric.

        Note: OpenTelemetry uses observable gauges with callbacks.
        For simple gauges, use up_down_counter instead.

        Args:
            name: Metric name
            description: Metric description
            unit: Metric unit
            callback: Callback function to get current value

        Returns:
            Gauge metric

        Example:
            ```python
            def get_memory_usage():
                return psutil.Process().memory_info().rss

            memory_gauge = metrics.gauge(
                "process_memory_bytes",
                description="Process memory usage",
                unit="bytes",
                callback=get_memory_usage,
            )
            ```
        """
        if not self._enabled or self._meter is None:
            return NoOpGauge(name, description, unit, callback)

        if callback:

            def observable_callback(options):
                yield otel_metrics.Observation(callback())

            return self._meter.create_observable_gauge(
                name=name,
                description=description,
                unit=unit,
                callbacks=[observable_callback],
            )

        # For non-callback gauges, return NoOp (use up_down_counter instead)
        return NoOpGauge(name, description, unit)

    def up_down_counter(
        self,
        name: str,
        description: str = "",
        unit: str = "1",
    ) -> Any | NoOpUpDownCounter:
        """
        Create an up/down counter metric.

        Unlike regular counters, up/down counters can decrease.
        Useful for tracking values like active connections or queue size.

        Args:
            name: Metric name
            description: Metric description
            unit: Metric unit

        Returns:
            UpDownCounter metric

        Example:
            ```python
            active_connections = metrics.up_down_counter(
                "active_connections",
                description="Number of active connections",
                unit="1",
            )
            active_connections.add(1, {"service": "api"})  # New connection
            active_connections.add(-1, {"service": "api"})  # Connection closed
            ```
        """
        if not self._enabled or self._meter is None:
            return NoOpUpDownCounter(name, description, unit)

        return self._meter.create_up_down_counter(
            name=name,
            description=description,
            unit=unit,
        )

    def record_agent_request(
        self,
        agent_name: str,
        duration_seconds: float,
        success: bool = True,
        tokens_used: int | None = None,
        iterations: int | None = None,
        error_type: str | None = None,
    ) -> None:
        """
        Record metrics for an agent request.

        Convenience method to record multiple related metrics at once.

        Args:
            agent_name: Name of the agent
            duration_seconds: Request duration in seconds
            success: Whether the request was successful
            tokens_used: Total tokens used
            iterations: Number of iterations
            error_type: Type of error (if failed)

        Example:
            ```python
            start = time.time()
            try:
                result = await agent.run(input)
                metrics.record_agent_request(
                    agent_name="summarizer",
                    duration_seconds=time.time() - start,
                    success=True,
                    tokens_used=result.tokens_used,
                    iterations=result.iterations,
                )
            except (RuntimeError, ConnectionError, TimeoutError, OSError) as e:
                metrics.record_agent_request(
                    agent_name="summarizer",
                    duration_seconds=time.time() - start,
                    success=False,
                    error_type=type(e).__name__,
                )
            ```
        """
        status = "success" if success else "error"
        labels = {"agent": agent_name, "status": status}

        self.agent_requests_total.add(1, labels)
        self.agent_request_duration_seconds.record(duration_seconds, {"agent": agent_name})

        if not success and error_type:
            self.agent_errors_total.add(1, {"agent": agent_name, "error_type": error_type})

        if tokens_used is not None:
            self.agent_tokens_used_total.add(tokens_used, {"agent": agent_name})

        if iterations is not None:
            self.agent_iterations_total.add(iterations, {"agent": agent_name})

    def record_llm_request(
        self,
        model: str,
        duration_seconds: float,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_cents: float | None = None,
        success: bool = True,
        error_type: str | None = None,
    ) -> None:
        """
        Record metrics for an LLM request.

        Args:
            model: Model name
            duration_seconds: Request duration in seconds
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            cost_cents: Cost in cents
            success: Whether the request was successful
            error_type: Type of error (if failed)

        Example:
            ```python
            start = time.time()
            response = await llm.complete(request)
            metrics.record_llm_request(
                model="gpt-4",
                duration_seconds=time.time() - start,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                cost_cents=response.cost_cents,
            )
            ```
        """
        status = "success" if success else "error"
        labels = {"model": model, "status": status}

        self.llm_requests_total.add(1, labels)
        self.llm_request_duration_seconds.record(duration_seconds, {"model": model})

        total_tokens = input_tokens + output_tokens
        if total_tokens > 0:
            self.llm_tokens_total.add(
                total_tokens,
                {"model": model, "type": "total"},
            )
            self.llm_tokens_total.add(
                input_tokens,
                {"model": model, "type": "input"},
            )
            self.llm_tokens_total.add(
                output_tokens,
                {"model": model, "type": "output"},
            )

        if cost_cents is not None:
            self.llm_cost_cents_total.add(cost_cents, {"model": model})

        if not success and error_type:
            self.llm_errors_total.add(1, {"model": model, "error_type": error_type})

    def record_tool_execution(
        self,
        tool_name: str,
        duration_seconds: float,
        success: bool = True,
        cache_hit: bool = False,
        error_type: str | None = None,
    ) -> None:
        """
        Record metrics for a tool execution.

        Args:
            tool_name: Name of the tool
            duration_seconds: Execution duration in seconds
            success: Whether execution was successful
            cache_hit: Whether the result was from cache
            error_type: Type of error (if failed)

        Example:
            ```python
            start = time.time()
            result = await tool.execute(params)
            metrics.record_tool_execution(
                tool_name="search",
                duration_seconds=time.time() - start,
                success=result.success,
                cache_hit=result.from_cache,
            )
            ```
        """
        status = "success" if success else "error"
        labels = {"tool": tool_name, "status": status}

        self.tool_executions_total.add(1, labels)
        self.tool_execution_duration_seconds.record(duration_seconds, {"tool": tool_name})

        if cache_hit:
            self.tool_cache_hits_total.add(1, {"tool": tool_name})

        if not success and error_type:
            self.tool_errors_total.add(1, {"tool": tool_name, "error_type": error_type})

    def record_rag_retrieval(
        self,
        collection: str,
        duration_seconds: float,
        documents_retrieved: int,
        embedding_duration_seconds: float | None = None,
    ) -> None:
        """
        Record metrics for a RAG retrieval operation.

        Args:
            collection: Vector store collection name
            duration_seconds: Total retrieval duration
            documents_retrieved: Number of documents retrieved
            embedding_duration_seconds: Duration of embedding step

        Example:
            ```python
            start = time.time()
            embed_start = time.time()
            embedding = await embedder.embed(query)
            embed_duration = time.time() - embed_start

            docs = await retriever.retrieve(embedding)
            total_duration = time.time() - start

            metrics.record_rag_retrieval(
                collection="knowledge_base",
                duration_seconds=total_duration,
                documents_retrieved=len(docs),
                embedding_duration_seconds=embed_duration,
            )
            ```
        """
        self.rag_retrievals_total.add(1, {"collection": collection})
        self.rag_retrieval_duration_seconds.record(
            duration_seconds,
            {"collection": collection},
        )
        self.rag_documents_retrieved_total.add(
            documents_retrieved,
            {"collection": collection},
        )

        if embedding_duration_seconds is not None:
            self.rag_embedding_duration_seconds.record(
                embedding_duration_seconds,
                {"collection": collection},
            )

    async def shutdown(self) -> None:
        """
        Shutdown the metrics provider and flush pending metrics.

        Example:
            ```python
            # On application shutdown
            await metrics.shutdown()
            ```
        """
        if self._provider and _OTEL_METRICS_AVAILABLE:
            self._provider.shutdown()

    @property
    def is_enabled(self) -> bool:
        """Check if metrics collection is enabled."""
        return self._enabled

    @property
    def is_otel_available(self) -> bool:
        """Check if OpenTelemetry metrics is available."""
        return _OTEL_METRICS_AVAILABLE


# Global metrics instance
_global_metrics: AgentMetrics | None = None


def get_metrics() -> AgentMetrics:
    """
    Get the global metrics instance.

    Returns:
        The global AgentMetrics instance

    Example:
        ```python
        metrics = get_metrics()
        metrics.agent_requests_total.add(1, {"agent": "summarizer"})
        ```
    """
    global _global_metrics
    if _global_metrics is None:
        _global_metrics = AgentMetrics()
    return _global_metrics


def set_metrics(metrics: AgentMetrics) -> None:
    """
    Set the global metrics instance.

    Args:
        metrics: The metrics instance to set as global

    Example:
        ```python
        config = MetricsConfig(
            service_name="my-service",
            endpoint="http://prometheus:4317",
        )
        metrics = AgentMetrics(config)
        set_metrics(metrics)
        ```
    """
    global _global_metrics
    _global_metrics = metrics
