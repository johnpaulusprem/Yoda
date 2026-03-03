"""Structured JSON logging with trace context."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any


class JsonFormatter(logging.Formatter):
    """Outputs log records as JSON with trace context."""

    def __init__(self, service_name: str = "cxo-ai-companion") -> None:
        super().__init__()
        self._service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self._service_name,
        }

        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = {
                "type": type(record.exc_info[1]).__name__,
                "message": str(record.exc_info[1]),
            }

        # Add trace context if available
        trace_id = getattr(record, "trace_id", None)
        if trace_id:
            log_entry["trace_id"] = trace_id
        span_id = getattr(record, "span_id", None)
        if span_id:
            log_entry["span_id"] = span_id

        # Add extra fields
        for key in ("user_id", "tenant_id", "correlation_id", "meeting_id", "request_id", "duration_ms", "status_code"):
            val = getattr(record, key, None)
            if val is not None:
                log_entry[key] = val

        # Add any extra dict passed via `extra=`
        if hasattr(record, "extra_data"):
            log_entry.update(record.extra_data)

        return json.dumps(log_entry, default=str)


class TextFormatter(logging.Formatter):
    """Human-readable log formatter with trace context."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        correlation = getattr(record, "correlation_id", "")
        prefix = f"[{ts}] {record.levelname:8s} {record.name}"
        if correlation:
            prefix += f" [{correlation[:8]}]"
        return f"{prefix} — {record.getMessage()}"


class TracedLogger:
    """Logger wrapper that adds security context info."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def _log(self, level: int, msg: str, *args: Any, **kwargs: Any) -> None:
        extra = kwargs.pop("extra", {})
        security_context = kwargs.pop("security_context", None)
        if security_context is not None:
            extra.update(security_context.to_log_dict())
        kwargs["extra"] = extra
        self._logger.log(level, msg, *args, **kwargs)

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.DEBUG, msg, *args, **kwargs)

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.INFO, msg, *args, **kwargs)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.WARNING, msg, *args, **kwargs)

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.ERROR, msg, *args, **kwargs)

    def exception(self, msg: str, *args: Any, **kwargs: Any) -> None:
        kwargs["exc_info"] = True
        self._log(logging.ERROR, msg, *args, **kwargs)


def get_logger(name: str) -> TracedLogger:
    """Get a traced logger instance."""
    return TracedLogger(logging.getLogger(name))


def configure_logging(
    level: str = "INFO",
    json_format: bool = True,
    service_name: str = "cxo-ai-companion",
) -> None:
    """Configure structured logging for the application."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    if json_format:
        handler.setFormatter(JsonFormatter(service_name=service_name))
    else:
        handler.setFormatter(TextFormatter())

    root.addHandler(handler)

    # Suppress noisy libraries
    for lib in ("httpx", "httpcore", "asyncio", "azure"):
        logging.getLogger(lib).setLevel(logging.WARNING)
