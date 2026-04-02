"""
Configuration classes for OpenTelemetry observability.

This module provides configuration dataclasses for tracing, metrics, and logging.
Supports multiple exporter backends including OTLP, Jaeger, and Zipkin.

Example:
    ```python
    from yoda_foundation.observability.config import (
        ObservabilityConfig,
        TracingConfig,
        MetricsConfig,
        LoggingConfig,
        ExporterType,
    )

    config = ObservabilityConfig(
        service_name="my-agent-service",
        service_version="1.0.0",
        tracing=TracingConfig(
            enabled=True,
            endpoint="http://jaeger:4317",
            exporter_type=ExporterType.OTLP,
            sample_rate=1.0,
        ),
        metrics=MetricsConfig(
            enabled=True,
            endpoint="http://prometheus:4317",
            export_interval_ms=60000,
        ),
        logging=LoggingConfig(
            enabled=True,
            level="INFO",
            include_trace_context=True,
        ),
    )
    ```
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from yoda_foundation.exceptions import ValidationError


class ExporterType(Enum):
    """
    Type of telemetry exporter.

    Attributes:
        OTLP: OpenTelemetry Protocol exporter (recommended)
        JAEGER: Jaeger-specific exporter
        ZIPKIN: Zipkin-specific exporter
        CONSOLE: Console/stdout exporter for debugging
        NONE: No exporter (disabled)
    """

    OTLP = "otlp"
    JAEGER = "jaeger"
    ZIPKIN = "zipkin"
    CONSOLE = "console"
    NONE = "none"


class SamplerType(Enum):
    """
    Type of trace sampler.

    Attributes:
        ALWAYS_ON: Sample all traces
        ALWAYS_OFF: Sample no traces
        TRACE_ID_RATIO: Sample based on trace ID ratio
        PARENT_BASED: Use parent span sampling decision
    """

    ALWAYS_ON = "always_on"
    ALWAYS_OFF = "always_off"
    TRACE_ID_RATIO = "trace_id_ratio"
    PARENT_BASED = "parent_based"


@dataclass
class TracingConfig:
    """
    Configuration for distributed tracing.

    Attributes:
        enabled: Whether tracing is enabled
        service_name: Name of the service (used in spans)
        endpoint: Exporter endpoint URL
        exporter_type: Type of exporter to use
        sampler_type: Type of sampler to use
        sample_rate: Sampling rate (0.0-1.0) for TRACE_ID_RATIO sampler
        batch_size: Maximum batch size for span export
        export_timeout_ms: Timeout for exporting spans
        max_queue_size: Maximum queue size for pending spans
        headers: Additional headers for exporter
        resource_attributes: Additional resource attributes

    Example:
        ```python
        config = TracingConfig(
            enabled=True,
            service_name="agent-service",
            endpoint="http://jaeger:4317",
            exporter_type=ExporterType.OTLP,
            sample_rate=0.5,  # Sample 50% of traces
        )
        ```
    """

    enabled: bool = True
    service_name: str = "agentic-ai-service"
    endpoint: str | None = None
    exporter_type: ExporterType = ExporterType.CONSOLE
    sampler_type: SamplerType = SamplerType.ALWAYS_ON
    sample_rate: float = 1.0
    batch_size: int = 512
    export_timeout_ms: int = 30000
    max_queue_size: int = 2048
    headers: dict[str, str] = field(default_factory=dict)
    resource_attributes: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if not 0.0 <= self.sample_rate <= 1.0:
            raise ValidationError(
                message=f"sample_rate must be between 0.0 and 1.0, got {self.sample_rate}",
                field_name="sample_rate",
            )
        if self.batch_size < 1:
            raise ValidationError(
                message=f"batch_size must be at least 1, got {self.batch_size}",
                field_name="batch_size",
            )
        if self.export_timeout_ms < 1:
            raise ValidationError(
                message=f"export_timeout_ms must be at least 1, got {self.export_timeout_ms}",
                field_name="export_timeout_ms",
            )
        if self.max_queue_size < 1:
            raise ValidationError(
                message=f"max_queue_size must be at least 1, got {self.max_queue_size}",
                field_name="max_queue_size",
            )
        # Validate endpoint requirement for non-console exporters
        if (
            self.enabled
            and self.exporter_type not in (ExporterType.CONSOLE, ExporterType.NONE)
            and not self.endpoint
        ):
            raise ValidationError(
                message=f"endpoint is required for exporter type {self.exporter_type.value}",
                field_name="endpoint",
            )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "enabled": self.enabled,
            "service_name": self.service_name,
            "endpoint": self.endpoint,
            "exporter_type": self.exporter_type.value,
            "sampler_type": self.sampler_type.value,
            "sample_rate": self.sample_rate,
            "batch_size": self.batch_size,
            "export_timeout_ms": self.export_timeout_ms,
            "max_queue_size": self.max_queue_size,
            "headers": self.headers,
            "resource_attributes": self.resource_attributes,
        }


@dataclass
class MetricsConfig:
    """
    Configuration for metrics collection and export.

    Attributes:
        enabled: Whether metrics collection is enabled
        service_name: Name of the service (used in metrics)
        endpoint: Exporter endpoint URL
        exporter_type: Type of exporter to use
        export_interval_ms: Interval for metric export in milliseconds
        histogram_boundaries: Default histogram bucket boundaries
        headers: Additional headers for exporter
        resource_attributes: Additional resource attributes

    Example:
        ```python
        config = MetricsConfig(
            enabled=True,
            service_name="agent-service",
            endpoint="http://prometheus:4317",
            exporter_type=ExporterType.OTLP,
            export_interval_ms=60000,
            histogram_boundaries=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
        )
        ```
    """

    enabled: bool = True
    service_name: str = "agentic-ai-service"
    endpoint: str | None = None
    exporter_type: ExporterType = ExporterType.CONSOLE
    export_interval_ms: int = 60000
    histogram_boundaries: list[float] = field(
        default_factory=lambda: [
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
    )
    headers: dict[str, str] = field(default_factory=dict)
    resource_attributes: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if self.export_interval_ms < 1000:
            raise ValidationError(
                message=f"export_interval_ms must be at least 1000, got {self.export_interval_ms}",
                field_name="export_interval_ms",
            )
        if not self.histogram_boundaries:
            raise ValidationError(
                message="histogram_boundaries cannot be empty",
                field_name="histogram_boundaries",
            )
        # Validate endpoint requirement for non-console exporters
        if (
            self.enabled
            and self.exporter_type not in (ExporterType.CONSOLE, ExporterType.NONE)
            and not self.endpoint
        ):
            raise ValidationError(
                message=f"endpoint is required for exporter type {self.exporter_type.value}",
                field_name="endpoint",
            )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "enabled": self.enabled,
            "service_name": self.service_name,
            "endpoint": self.endpoint,
            "exporter_type": self.exporter_type.value,
            "export_interval_ms": self.export_interval_ms,
            "histogram_boundaries": self.histogram_boundaries,
            "headers": self.headers,
            "resource_attributes": self.resource_attributes,
        }


@dataclass
class LoggingConfig:
    """
    Configuration for structured logging with trace context.

    Attributes:
        enabled: Whether logging integration is enabled
        level: Default log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        format: Log format (json, text)
        include_trace_context: Whether to include trace context in logs
        endpoint: Log exporter endpoint (optional)
        exporter_type: Type of exporter for logs
        batch_size: Maximum batch size for log export
        export_timeout_ms: Timeout for exporting logs

    Example:
        ```python
        config = LoggingConfig(
            enabled=True,
            level="INFO",
            format="json",
            include_trace_context=True,
        )
        ```
    """

    enabled: bool = True
    level: str = "INFO"
    format: str = "json"
    include_trace_context: bool = True
    endpoint: str | None = None
    exporter_type: ExporterType = ExporterType.CONSOLE
    batch_size: int = 512
    export_timeout_ms: int = 30000

    _VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    _VALID_FORMATS = {"json", "text"}

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if self.level.upper() not in self._VALID_LEVELS:
            raise ValidationError(
                message=f"level must be one of {self._VALID_LEVELS}, got {self.level}",
                field_name="level",
            )
        if self.format.lower() not in self._VALID_FORMATS:
            raise ValidationError(
                message=f"format must be one of {self._VALID_FORMATS}, got {self.format}",
                field_name="format",
            )
        # Normalize values
        self.level = self.level.upper()
        self.format = self.format.lower()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "enabled": self.enabled,
            "level": self.level,
            "format": self.format,
            "include_trace_context": self.include_trace_context,
            "endpoint": self.endpoint,
            "exporter_type": self.exporter_type.value,
            "batch_size": self.batch_size,
            "export_timeout_ms": self.export_timeout_ms,
        }


@dataclass
class ObservabilityConfig:
    """
    Combined configuration for all observability features.

    Provides a single configuration object for tracing, metrics, and logging.
    Can be initialized from environment variables or configuration files.

    Attributes:
        service_name: Name of the service (applied to all components)
        service_version: Version of the service
        deployment_environment: Deployment environment (dev, staging, prod)
        tracing: Tracing configuration
        metrics: Metrics configuration
        logging: Logging configuration
        propagators: List of propagator types to use
        enabled: Global enable/disable for all observability

    Example:
        ```python
        config = ObservabilityConfig(
            service_name="my-agent-service",
            service_version="1.0.0",
            deployment_environment="production",
            tracing=TracingConfig(
                endpoint="http://jaeger:4317",
                exporter_type=ExporterType.OTLP,
            ),
            metrics=MetricsConfig(
                endpoint="http://prometheus:4317",
                exporter_type=ExporterType.OTLP,
            ),
            logging=LoggingConfig(
                level="INFO",
                include_trace_context=True,
            ),
        )
        ```
    """

    service_name: str = "agentic-ai-service"
    service_version: str = "1.0.0"
    deployment_environment: str = "development"
    tracing: TracingConfig = field(default_factory=TracingConfig)
    metrics: MetricsConfig = field(default_factory=MetricsConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    propagators: list[str] = field(default_factory=lambda: ["tracecontext", "baggage"])
    enabled: bool = True

    def __post_init__(self) -> None:
        """Apply service name to sub-configs and validate."""
        # Apply service name to sub-configs if using defaults
        if self.tracing.service_name == "agentic-ai-service":
            self.tracing.service_name = self.service_name
        if self.metrics.service_name == "agentic-ai-service":
            self.metrics.service_name = self.service_name

        # Validate propagators
        valid_propagators = {"tracecontext", "baggage", "b3", "b3multi", "jaeger"}
        for prop in self.propagators:
            if prop.lower() not in valid_propagators:
                raise ValidationError(
                    message=f"Invalid propagator: {prop}. Valid options: {valid_propagators}",
                    field_name="propagators",
                )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "service_name": self.service_name,
            "service_version": self.service_version,
            "deployment_environment": self.deployment_environment,
            "tracing": self.tracing.to_dict(),
            "metrics": self.metrics.to_dict(),
            "logging": self.logging.to_dict(),
            "propagators": self.propagators,
            "enabled": self.enabled,
        }

    @classmethod
    def from_env(cls) -> ObservabilityConfig:
        """
        Create configuration from environment variables.

        Environment variables:
            OTEL_SERVICE_NAME: Service name
            OTEL_SERVICE_VERSION: Service version
            OTEL_DEPLOYMENT_ENVIRONMENT: Deployment environment
            OTEL_EXPORTER_OTLP_ENDPOINT: OTLP endpoint
            OTEL_EXPORTER_OTLP_HEADERS: OTLP headers (comma-separated key=value)
            OTEL_TRACES_SAMPLER: Sampler type
            OTEL_TRACES_SAMPLER_ARG: Sampler argument (e.g., sample rate)
            OTEL_METRICS_EXPORTER: Metrics exporter type
            OTEL_LOGS_EXPORTER: Logs exporter type
            OTEL_PROPAGATORS: Propagators (comma-separated)

        Returns:
            ObservabilityConfig instance

        Example:
            ```python
            # Set environment variables
            os.environ["OTEL_SERVICE_NAME"] = "my-service"
            os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://collector:4317"

            config = ObservabilityConfig.from_env()
            ```
        """
        import os

        service_name = os.environ.get("OTEL_SERVICE_NAME", "agentic-ai-service")
        service_version = os.environ.get("OTEL_SERVICE_VERSION", "1.0.0")
        environment = os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "development")
        endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")

        # Parse headers
        headers_str = os.environ.get("OTEL_EXPORTER_OTLP_HEADERS", "")
        headers: dict[str, str] = {}
        if headers_str:
            for pair in headers_str.split(","):
                if "=" in pair:
                    key, value = pair.split("=", 1)
                    headers[key.strip()] = value.strip()

        # Parse sampler
        sampler_str = os.environ.get("OTEL_TRACES_SAMPLER", "always_on")
        sampler_type = SamplerType.ALWAYS_ON
        for st in SamplerType:
            if st.value == sampler_str:
                sampler_type = st
                break

        sample_rate = float(os.environ.get("OTEL_TRACES_SAMPLER_ARG", "1.0"))

        # Parse propagators
        propagators_str = os.environ.get("OTEL_PROPAGATORS", "tracecontext,baggage")
        propagators = [p.strip() for p in propagators_str.split(",")]

        # Determine exporter type
        exporter_type = ExporterType.CONSOLE if not endpoint else ExporterType.OTLP

        return cls(
            service_name=service_name,
            service_version=service_version,
            deployment_environment=environment,
            tracing=TracingConfig(
                enabled=True,
                service_name=service_name,
                endpoint=endpoint,
                exporter_type=exporter_type,
                sampler_type=sampler_type,
                sample_rate=sample_rate,
                headers=headers,
            ),
            metrics=MetricsConfig(
                enabled=True,
                service_name=service_name,
                endpoint=endpoint,
                exporter_type=exporter_type,
                headers=headers,
            ),
            logging=LoggingConfig(
                enabled=True,
                level=os.environ.get("OTEL_LOG_LEVEL", "INFO"),
                include_trace_context=True,
            ),
            propagators=propagators,
        )
