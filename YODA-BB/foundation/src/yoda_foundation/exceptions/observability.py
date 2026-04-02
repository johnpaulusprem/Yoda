"""
Exception classes for observability components.

This module defines exceptions specific to tracing, metrics,
logging, and context propagation operations.

Example:
    ```python
    from yoda_foundation.exceptions.observability import (
        ObservabilityError,
        TracingError,
        MetricsError,
        ExporterError,
        PropagationError,
    )

    try:
        await tracer.start_span("operation")
    except TracingError as e:
        logger.error(f"Tracing failed: {e.error_id}", extra=e.to_log_dict())
    ```
"""

from __future__ import annotations

from typing import Any

from yoda_foundation.exceptions.base import (
    AgenticBaseException,
    ErrorCategory,
    ErrorSeverity,
)


class ObservabilityError(AgenticBaseException):
    """
    Base exception for all observability-related errors.

    This is the parent class for tracing, metrics, logging,
    and propagation errors.

    Attributes:
        component: The observability component that failed
        operation: The operation that failed

    Example:
        ```python
        raise ObservabilityError(
            message="Failed to initialize observability",
            component="tracer",
            operation="init",
        )
        ```
    """

    def __init__(
        self,
        message: str,
        *,
        component: str | None = None,
        operation: str | None = None,
        error_id: str | None = None,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        retryable: bool = True,
        user_message: str | None = None,
        suggestions: list[str] | None = None,
        cause: Exception | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize the observability error.

        Args:
            message: Error description
            component: The component that failed (tracer, metrics, etc.)
            operation: The operation that failed
            error_id: Unique error ID
            severity: Error severity
            retryable: Whether the operation can be retried
            user_message: Safe message for end users
            suggestions: Actionable remediation steps
            cause: Original exception
            details: Additional context
        """
        self.component = component
        self.operation = operation

        # Build details
        full_details = details or {}
        if component:
            full_details["component"] = component
        if operation:
            full_details["operation"] = operation

        super().__init__(
            message=message,
            error_id=error_id,
            category=ErrorCategory.INTERNAL,
            severity=severity,
            retryable=retryable,
            user_message=user_message or "An observability error occurred.",
            suggestions=suggestions
            or [
                "Check observability configuration",
                "Verify backend connectivity",
                "Check OpenTelemetry SDK installation",
            ],
            cause=cause,
            details=full_details,
        )


class TracingError(ObservabilityError):
    """
    Exception for tracing-related errors.

    Raised when span creation, context management, or trace
    export operations fail.

    Attributes:
        span_name: Name of the span that failed
        trace_id: The trace ID if available

    Example:
        ```python
        raise TracingError(
            message="Failed to create span",
            span_name="process_request",
            trace_id="abc123",
        )
        ```
    """

    def __init__(
        self,
        message: str,
        *,
        span_name: str | None = None,
        trace_id: str | None = None,
        error_id: str | None = None,
        severity: ErrorSeverity = ErrorSeverity.LOW,
        retryable: bool = True,
        user_message: str | None = None,
        suggestions: list[str] | None = None,
        cause: Exception | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize the tracing error.

        Args:
            message: Error description
            span_name: Name of the failing span
            trace_id: The trace ID
            error_id: Unique error ID
            severity: Error severity
            retryable: Whether the operation can be retried
            user_message: Safe message for end users
            suggestions: Actionable remediation steps
            cause: Original exception
            details: Additional context
        """
        self.span_name = span_name
        self.trace_id = trace_id

        full_details = details or {}
        if span_name:
            full_details["span_name"] = span_name
        if trace_id:
            full_details["trace_id"] = trace_id

        super().__init__(
            message=message,
            component="tracer",
            operation="span",
            error_id=error_id,
            severity=severity,
            retryable=retryable,
            user_message=user_message or "A tracing error occurred.",
            suggestions=suggestions
            or [
                "Check tracer configuration",
                "Verify trace exporter connectivity",
                "Check if OpenTelemetry SDK is installed",
            ],
            cause=cause,
            details=full_details,
        )


class MetricsError(ObservabilityError):
    """
    Exception for metrics-related errors.

    Raised when metric recording, export, or configuration fails.

    Attributes:
        metric_name: Name of the failing metric
        metric_type: Type of the metric (counter, histogram, etc.)

    Example:
        ```python
        raise MetricsError(
            message="Failed to record histogram",
            metric_name="request_duration",
            metric_type="histogram",
        )
        ```
    """

    def __init__(
        self,
        message: str,
        *,
        metric_name: str | None = None,
        metric_type: str | None = None,
        error_id: str | None = None,
        severity: ErrorSeverity = ErrorSeverity.LOW,
        retryable: bool = True,
        user_message: str | None = None,
        suggestions: list[str] | None = None,
        cause: Exception | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize the metrics error.

        Args:
            message: Error description
            metric_name: Name of the failing metric
            metric_type: Type of metric
            error_id: Unique error ID
            severity: Error severity
            retryable: Whether the operation can be retried
            user_message: Safe message for end users
            suggestions: Actionable remediation steps
            cause: Original exception
            details: Additional context
        """
        self.metric_name = metric_name
        self.metric_type = metric_type

        full_details = details or {}
        if metric_name:
            full_details["metric_name"] = metric_name
        if metric_type:
            full_details["metric_type"] = metric_type

        super().__init__(
            message=message,
            component="metrics",
            operation="record",
            error_id=error_id,
            severity=severity,
            retryable=retryable,
            user_message=user_message or "A metrics error occurred.",
            suggestions=suggestions
            or [
                "Check metrics configuration",
                "Verify metrics exporter connectivity",
                "Ensure metric name follows naming conventions",
            ],
            cause=cause,
            details=full_details,
        )


class ExporterError(ObservabilityError):
    """
    Exception for exporter-related errors.

    Raised when telemetry export to backends fails.

    Attributes:
        exporter_type: Type of exporter (otlp, jaeger, etc.)
        endpoint: The endpoint that failed

    Example:
        ```python
        raise ExporterError(
            message="Failed to export spans",
            exporter_type="otlp",
            endpoint="http://jaeger:4317",
        )
        ```
    """

    def __init__(
        self,
        message: str,
        *,
        exporter_type: str | None = None,
        endpoint: str | None = None,
        error_id: str | None = None,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        retryable: bool = True,
        user_message: str | None = None,
        suggestions: list[str] | None = None,
        cause: Exception | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize the exporter error.

        Args:
            message: Error description
            exporter_type: Type of exporter
            endpoint: The failing endpoint
            error_id: Unique error ID
            severity: Error severity
            retryable: Whether the operation can be retried
            user_message: Safe message for end users
            suggestions: Actionable remediation steps
            cause: Original exception
            details: Additional context
        """
        self.exporter_type = exporter_type
        self.endpoint = endpoint

        full_details = details or {}
        if exporter_type:
            full_details["exporter_type"] = exporter_type
        if endpoint:
            full_details["endpoint"] = endpoint

        super().__init__(
            message=message,
            component="exporter",
            operation="export",
            error_id=error_id,
            severity=severity,
            retryable=retryable,
            user_message=user_message or "Failed to export telemetry data.",
            suggestions=suggestions
            or [
                "Check endpoint connectivity",
                "Verify exporter configuration",
                "Check if the backend service is running",
                "Review network/firewall settings",
            ],
            cause=cause,
            details=full_details,
        )


class PropagationError(ObservabilityError):
    """
    Exception for context propagation errors.

    Raised when injecting or extracting trace context fails.

    Attributes:
        propagator_type: Type of propagator (tracecontext, baggage, etc.)
        direction: Direction of propagation (inject, extract)

    Example:
        ```python
        raise PropagationError(
            message="Failed to extract trace context",
            propagator_type="tracecontext",
            direction="extract",
        )
        ```
    """

    def __init__(
        self,
        message: str,
        *,
        propagator_type: str | None = None,
        direction: str | None = None,
        error_id: str | None = None,
        severity: ErrorSeverity = ErrorSeverity.LOW,
        retryable: bool = True,
        user_message: str | None = None,
        suggestions: list[str] | None = None,
        cause: Exception | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize the propagation error.

        Args:
            message: Error description
            propagator_type: Type of propagator
            direction: inject or extract
            error_id: Unique error ID
            severity: Error severity
            retryable: Whether the operation can be retried
            user_message: Safe message for end users
            suggestions: Actionable remediation steps
            cause: Original exception
            details: Additional context
        """
        self.propagator_type = propagator_type
        self.direction = direction

        full_details = details or {}
        if propagator_type:
            full_details["propagator_type"] = propagator_type
        if direction:
            full_details["direction"] = direction

        super().__init__(
            message=message,
            component="propagator",
            operation=direction or "propagate",
            error_id=error_id,
            severity=severity,
            retryable=retryable,
            user_message=user_message or "Failed to propagate trace context.",
            suggestions=suggestions
            or [
                "Check propagator configuration",
                "Verify carrier format",
                "Ensure headers are properly formatted",
            ],
            cause=cause,
            details=full_details,
        )


class InstrumentationError(ObservabilityError):
    """
    Exception for instrumentation errors.

    Raised when auto-instrumentation fails to apply or remove.

    Attributes:
        target_class: The class being instrumented
        target_method: The method being instrumented

    Example:
        ```python
        raise InstrumentationError(
            message="Failed to instrument BaseAgent.run",
            target_class="BaseAgent",
            target_method="run",
        )
        ```
    """

    def __init__(
        self,
        message: str,
        *,
        target_class: str | None = None,
        target_method: str | None = None,
        error_id: str | None = None,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        retryable: bool = False,
        user_message: str | None = None,
        suggestions: list[str] | None = None,
        cause: Exception | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize the instrumentation error.

        Args:
            message: Error description
            target_class: Class being instrumented
            target_method: Method being instrumented
            error_id: Unique error ID
            severity: Error severity
            retryable: Whether the operation can be retried
            user_message: Safe message for end users
            suggestions: Actionable remediation steps
            cause: Original exception
            details: Additional context
        """
        self.target_class = target_class
        self.target_method = target_method

        full_details = details or {}
        if target_class:
            full_details["target_class"] = target_class
        if target_method:
            full_details["target_method"] = target_method

        super().__init__(
            message=message,
            component="instrumentor",
            operation="instrument",
            error_id=error_id,
            severity=severity,
            retryable=retryable,
            user_message=user_message or "Failed to apply instrumentation.",
            suggestions=suggestions
            or [
                "Check if the target class is available",
                "Verify instrumentation order",
                "Ensure no conflicting instrumentation exists",
            ],
            cause=cause,
            details=full_details,
        )
