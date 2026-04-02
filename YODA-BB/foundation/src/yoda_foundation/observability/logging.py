"""
Structured logging with trace context for the Agentic AI Component Library.

This module provides logging that automatically includes trace context
from OpenTelemetry spans for correlation between logs and traces.

Example:
    ```python
    from yoda_foundation.observability import (
        TracedLogger,
        LoggingConfig,
    )

    # Create logger
    config = LoggingConfig(
        level="INFO",
        format="json",
        include_trace_context=True,
    )
    logger = TracedLogger("my_agent", config)

    # Log with automatic trace context
    logger.info("Processing request", request_id="req_123")
    logger.warning("Slow operation", duration_ms=1500.5)

    # Log with additional context
    with logger.with_context(user_id="user_456"):
        logger.info("User authenticated")
        logger.debug("Loading preferences")
    ```
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from yoda_foundation.observability.config import LoggingConfig


# Try to import OpenTelemetry
_OTEL_AVAILABLE = False
try:
    from opentelemetry import trace as otel_trace

    _OTEL_AVAILABLE = True
except ImportError:
    otel_trace = None


# Context variable for additional log context
_log_context: ContextVar[dict[str, Any]] = ContextVar("log_context", default={})


@dataclass
class LogRecord:
    """
    Structured log record with trace context.

    Attributes:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        message: Log message
        timestamp: When the log was created
        logger_name: Name of the logger
        trace_id: OpenTelemetry trace ID (if available)
        span_id: OpenTelemetry span ID (if available)
        attributes: Additional log attributes
        exception: Exception information (if any)

    Example:
        ```python
        record = LogRecord(
            level="INFO",
            message="Processing complete",
            logger_name="agent.processor",
            trace_id="abc123",
            span_id="def456",
            attributes={"items_processed": 100},
        )
        ```
    """

    level: str
    message: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    logger_name: str = "agentic_ai"
    trace_id: str | None = None
    span_id: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    exception: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "timestamp": self.timestamp.isoformat(),
            "level": self.level,
            "message": self.message,
            "logger": self.logger_name,
        }

        if self.trace_id:
            result["trace_id"] = self.trace_id
        if self.span_id:
            result["span_id"] = self.span_id
        if self.attributes:
            result.update(self.attributes)
        if self.exception:
            result["exception"] = self.exception

        return result

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), default=str)


class JsonFormatter(logging.Formatter):
    """
    JSON log formatter with trace context support.

    Formats log records as JSON with OpenTelemetry trace context included.

    Example:
        ```python
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        ```
    """

    def __init__(
        self,
        include_trace_context: bool = True,
        include_timestamp: bool = True,
    ) -> None:
        """
        Initialize the formatter.

        Args:
            include_trace_context: Whether to include trace context
            include_timestamp: Whether to include timestamp
        """
        super().__init__()
        self.include_trace_context = include_trace_context
        self.include_timestamp = include_timestamp

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as JSON."""
        log_data: dict[str, Any] = {
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }

        if self.include_timestamp:
            log_data["timestamp"] = datetime.fromtimestamp(record.created, tz=UTC).isoformat()

        # Add trace context
        if self.include_trace_context:
            trace_id, span_id = self._get_trace_context()
            if trace_id:
                log_data["trace_id"] = trace_id
            if span_id:
                log_data["span_id"] = span_id

        # Add extra attributes
        if hasattr(record, "extra_attributes"):
            log_data.update(record.extra_attributes)

        # Add context variables
        context = _log_context.get()
        if context:
            log_data.update(context)

        # Add exception info
        if record.exc_info:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": self.formatException(record.exc_info),
            }

        return json.dumps(log_data, default=str)

    def _get_trace_context(self) -> tuple[str | None, str | None]:
        """Get current trace and span IDs."""
        if not _OTEL_AVAILABLE:
            return None, None

        span = otel_trace.get_current_span()
        if span is None:
            return None, None

        ctx = span.get_span_context()
        if not ctx.is_valid:
            return None, None

        trace_id = format(ctx.trace_id, "032x")
        span_id = format(ctx.span_id, "016x")

        return trace_id, span_id


class TextFormatter(logging.Formatter):
    """
    Text log formatter with trace context support.

    Formats log records as human-readable text with trace context included.

    Example:
        ```python
        handler = logging.StreamHandler()
        handler.setFormatter(TextFormatter())
        logger.addHandler(handler)
        ```
    """

    def __init__(
        self,
        include_trace_context: bool = True,
        include_timestamp: bool = True,
    ) -> None:
        """
        Initialize the formatter.

        Args:
            include_trace_context: Whether to include trace context
            include_timestamp: Whether to include timestamp
        """
        fmt = ""
        if include_timestamp:
            fmt = "%(asctime)s - "
        fmt += "%(levelname)s - %(name)s - %(message)s"

        super().__init__(fmt)
        self.include_trace_context = include_trace_context

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as text."""
        # Get base formatted message
        formatted = super().format(record)

        # Add trace context
        if self.include_trace_context:
            trace_id, span_id = self._get_trace_context()
            if trace_id:
                formatted = f"[trace_id={trace_id[:8]}] {formatted}"

        # Add extra attributes
        if hasattr(record, "extra_attributes") and record.extra_attributes:
            attrs_str = " ".join(f"{k}={v}" for k, v in record.extra_attributes.items())
            formatted = f"{formatted} | {attrs_str}"

        return formatted

    def _get_trace_context(self) -> tuple[str | None, str | None]:
        """Get current trace and span IDs."""
        if not _OTEL_AVAILABLE:
            return None, None

        span = otel_trace.get_current_span()
        if span is None:
            return None, None

        ctx = span.get_span_context()
        if not ctx.is_valid:
            return None, None

        trace_id = format(ctx.trace_id, "032x")
        span_id = format(ctx.span_id, "016x")

        return trace_id, span_id


class TracedLogger:
    """
    Logger with automatic trace context injection.

    Wraps Python's standard logging with OpenTelemetry trace context
    for correlation between logs and traces.

    Attributes:
        name: Logger name
        config: Logging configuration
        _logger: Underlying Python logger

    Example:
        ```python
        logger = TracedLogger("my_agent")

        # Basic logging
        logger.info("Starting agent")
        logger.debug("Loaded configuration", config_path="/etc/agent.yaml")

        # With context
        with logger.with_context(request_id="req_123"):
            logger.info("Processing request")
            # ... work ...
            logger.info("Request complete")

        # Error logging
        try:
            risky_operation()
        except (RuntimeError, ConnectionError, TimeoutError, OSError) as e:
            logger.exception("Operation failed", operation="risky")
        ```
    """

    def __init__(
        self,
        name: str,
        config: LoggingConfig | None = None,
    ) -> None:
        """
        Initialize the traced logger.

        Args:
            name: Logger name
            config: Logging configuration

        Example:
            ```python
            logger = TracedLogger("agent.processor", LoggingConfig(
                level="DEBUG",
                format="json",
                include_trace_context=True,
            ))
            ```
        """
        self.name = name
        self.config = config or LoggingConfig()
        self._logger = logging.getLogger(name)
        self._setup_logger()

    def _setup_logger(self) -> None:
        """Configure the underlying logger."""
        # Set level
        level = getattr(logging, self.config.level, logging.INFO)
        self._logger.setLevel(level)

        # Avoid adding duplicate handlers
        if self._logger.handlers:
            return

        # Create handler
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level)

        # Create formatter based on config
        if self.config.format == "json":
            formatter = JsonFormatter(
                include_trace_context=self.config.include_trace_context,
            )
        else:
            formatter = TextFormatter(
                include_trace_context=self.config.include_trace_context,
            )

        handler.setFormatter(formatter)
        self._logger.addHandler(handler)

        # Don't propagate to root logger
        self._logger.propagate = False

    def _get_trace_context(self) -> dict[str, str | None]:
        """Get current trace context."""
        if not _OTEL_AVAILABLE or not self.config.include_trace_context:
            return {}

        span = otel_trace.get_current_span()
        if span is None:
            return {}

        ctx = span.get_span_context()
        if not ctx.is_valid:
            return {}

        return {
            "trace_id": format(ctx.trace_id, "032x"),
            "span_id": format(ctx.span_id, "016x"),
        }

    def _log(
        self,
        level: int,
        message: str,
        exc_info: Any = None,
        **kwargs: Any,
    ) -> None:
        """Internal log method."""
        # Create log record with extra attributes
        extra = {"extra_attributes": kwargs}

        # Add trace context
        trace_ctx = self._get_trace_context()
        if trace_ctx:
            extra["extra_attributes"].update(trace_ctx)

        # Add context variables
        context = _log_context.get()
        if context:
            extra["extra_attributes"].update(context)

        self._logger.log(level, message, exc_info=exc_info, extra=extra)

    def debug(self, message: str, **kwargs: Any) -> None:
        """
        Log a debug message.

        Args:
            message: Log message
            **kwargs: Additional attributes to include

        Example:
            ```python
            logger.debug("Cache lookup", key="user_123", hit=True)
            ```
        """
        self._log(logging.DEBUG, message, **kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        """
        Log an info message.

        Args:
            message: Log message
            **kwargs: Additional attributes to include

        Example:
            ```python
            logger.info("Request processed", duration_ms=125.5, status="success")
            ```
        """
        self._log(logging.INFO, message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        """
        Log a warning message.

        Args:
            message: Log message
            **kwargs: Additional attributes to include

        Example:
            ```python
            logger.warning("High latency detected", latency_ms=5000, threshold_ms=1000)
            ```
        """
        self._log(logging.WARNING, message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        """
        Log an error message.

        Args:
            message: Log message
            **kwargs: Additional attributes to include

        Example:
            ```python
            logger.error("Failed to connect", host="db.example.com", port=5432)
            ```
        """
        self._log(logging.ERROR, message, **kwargs)

    def critical(self, message: str, **kwargs: Any) -> None:
        """
        Log a critical message.

        Args:
            message: Log message
            **kwargs: Additional attributes to include

        Example:
            ```python
            logger.critical("System failure", component="database", recoverable=False)
            ```
        """
        self._log(logging.CRITICAL, message, **kwargs)

    def exception(self, message: str, **kwargs: Any) -> None:
        """
        Log an exception with traceback.

        Should be called from an exception handler.

        Args:
            message: Log message
            **kwargs: Additional attributes to include

        Example:
            ```python
            try:
                process_data()
            except (RuntimeError, ConnectionError, TimeoutError, OSError) as e:
                logger.exception("Processing failed", data_id="data_123")
            ```
        """
        self._log(logging.ERROR, message, exc_info=True, **kwargs)

    @contextmanager
    def with_context(self, **context: Any) -> Iterator[None]:
        """
        Add context to all logs within a block.

        Args:
            **context: Context attributes to add

        Yields:
            None

        Example:
            ```python
            with logger.with_context(request_id="req_123", user_id="user_456"):
                logger.info("Starting request")
                # ... work ...
                logger.info("Request complete")
            # Context is automatically removed after the block
            ```
        """
        # Get current context
        current = _log_context.get()

        # Create new context with additions
        new_context = {**current, **context}

        # Set new context
        token = _log_context.set(new_context)

        try:
            yield
        finally:
            # Restore previous context
            _log_context.reset(token)

    def bind(self, **context: Any) -> TracedLogger:
        """
        Create a new logger with additional bound context.

        Args:
            **context: Context to bind to the new logger

        Returns:
            New TracedLogger with bound context

        Example:
            ```python
            request_logger = logger.bind(request_id="req_123")
            request_logger.info("Processing")  # Includes request_id
            ```
        """
        # Create new logger with same config
        TracedLogger(self.name, self.config)

        # The context will be added via context manager when logging
        # For now, we create a wrapper that uses with_context
        class BoundLogger:
            def __init__(self, logger: TracedLogger, ctx: dict[str, Any]):
                self._logger = logger
                self._context = ctx

            def debug(self, message: str, **kwargs: Any) -> None:
                with self._logger.with_context(**self._context):
                    self._logger.debug(message, **kwargs)

            def info(self, message: str, **kwargs: Any) -> None:
                with self._logger.with_context(**self._context):
                    self._logger.info(message, **kwargs)

            def warning(self, message: str, **kwargs: Any) -> None:
                with self._logger.with_context(**self._context):
                    self._logger.warning(message, **kwargs)

            def error(self, message: str, **kwargs: Any) -> None:
                with self._logger.with_context(**self._context):
                    self._logger.error(message, **kwargs)

            def critical(self, message: str, **kwargs: Any) -> None:
                with self._logger.with_context(**self._context):
                    self._logger.critical(message, **kwargs)

            def exception(self, message: str, **kwargs: Any) -> None:
                with self._logger.with_context(**self._context):
                    self._logger.exception(message, **kwargs)

            def with_context(self, **ctx: Any) -> Iterator[None]:
                return self._logger.with_context(**{**self._context, **ctx})

            def bind(self, **ctx: Any) -> BoundLogger:
                return BoundLogger(self._logger, {**self._context, **ctx})

        return BoundLogger(self, context)  # type: ignore

    def set_level(self, level: str) -> None:
        """
        Set the log level.

        Args:
            level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)

        Example:
            ```python
            logger.set_level("DEBUG")
            ```
        """
        log_level = getattr(logging, level.upper(), logging.INFO)
        self._logger.setLevel(log_level)
        for handler in self._logger.handlers:
            handler.setLevel(log_level)

    def get_level(self) -> str:
        """
        Get the current log level.

        Returns:
            Current log level name

        Example:
            ```python
            level = logger.get_level()  # "INFO"
            ```
        """
        return logging.getLevelName(self._logger.level)


def get_logger(name: str) -> TracedLogger:
    """
    Get or create a traced logger.

    Args:
        name: Logger name

    Returns:
        TracedLogger instance

    Example:
        ```python
        logger = get_logger("agent.processor")
        logger.info("Processing started")
        ```
    """
    return TracedLogger(name)


# Global logger for convenience
_default_logger: TracedLogger | None = None


def get_default_logger() -> TracedLogger:
    """
    Get the default traced logger.

    Returns:
        Default TracedLogger instance

    Example:
        ```python
        logger = get_default_logger()
        logger.info("Application started")
        ```
    """
    global _default_logger
    if _default_logger is None:
        _default_logger = TracedLogger("agentic_ai")
    return _default_logger


def configure_logging(config: LoggingConfig) -> None:
    """
    Configure the default logger.

    Args:
        config: Logging configuration

    Example:
        ```python
        configure_logging(LoggingConfig(
            level="DEBUG",
            format="json",
            include_trace_context=True,
        ))
        ```
    """
    global _default_logger
    _default_logger = TracedLogger("agentic_ai", config)
