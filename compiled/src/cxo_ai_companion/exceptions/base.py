"""
Base exception classes for the CXO AI Companion.

Defines the foundational exception hierarchy. Every exception includes:
- Unique error ID for distributed tracing
- Category and severity classification
- Retryable flag for automatic retry logic
- User-safe messages for API responses
- Actionable suggestions for remediation
"""

from __future__ import annotations

import traceback
import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class ErrorCategory(Enum):
    """Categorization of error types for routing and handling."""

    VALIDATION = "validation"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    RATE_LIMIT = "rate_limit"
    MEETING = "meeting"
    TRANSCRIPTION = "transcription"
    AI_PROCESSING = "ai_processing"
    CALENDAR = "calendar"
    ACS = "acs"
    DELIVERY = "delivery"
    CONFIGURATION = "configuration"
    INTERNAL = "internal"
    NETWORK = "network"
    DATABASE = "database"
    CACHE = "cache"
    GRAPH_API = "graph_api"


class ErrorSeverity(Enum):
    """Severity level of errors for alerting and prioritization."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class CXOBaseException(Exception):
    """
    Base exception class for all CXO AI Companion exceptions.

    All exceptions in the application inherit from this class, ensuring
    consistent error handling, logging, and API response formatting.
    """

    def __init__(
        self,
        message: str,
        *,
        error_id: str | None = None,
        category: ErrorCategory = ErrorCategory.INTERNAL,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        retryable: bool = False,
        user_message: str | None = None,
        suggestions: list[str] | None = None,
        cause: Exception | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)

        self.message = message
        self.error_id = error_id or self._generate_error_id()
        self.timestamp = datetime.now(UTC)
        self.category = category
        self.severity = severity
        self.retryable = retryable
        self.user_message = user_message or "An error occurred. Please try again."
        self.suggestions = suggestions or []
        self.cause = cause
        self.details = details or {}

        if cause is not None:
            self.__cause__ = cause

    @staticmethod
    def _generate_error_id() -> str:
        """Generate a unique 8-character error ID."""
        return uuid.uuid4().hex[:8]

    def to_dict(self) -> dict[str, Any]:
        """Convert exception to dictionary for API responses."""
        return {
            "error": {
                "id": self.error_id,
                "message": self.user_message,
                "category": self.category.value,
                "severity": self.severity.value,
                "retryable": self.retryable,
                "suggestions": self.suggestions,
                "timestamp": self.timestamp.isoformat(),
            }
        }

    def to_log_dict(self) -> dict[str, Any]:
        """Convert exception to dictionary for logging."""
        result: dict[str, Any] = {
            "error_id": self.error_id,
            "message": self.message,
            "category": self.category.value,
            "severity": self.severity.value,
            "retryable": self.retryable,
            "user_message": self.user_message,
            "suggestions": self.suggestions,
            "timestamp": self.timestamp.isoformat(),
            "details": self.details,
            "exception_type": self.__class__.__name__,
        }

        if self.cause is not None:
            result["cause"] = {
                "type": type(self.cause).__name__,
                "message": str(self.cause),
                "traceback": traceback.format_exception(
                    type(self.cause), self.cause, self.cause.__traceback__
                ),
            }

        return result

    def with_details(self, **kwargs: Any) -> CXOBaseException:
        """Add additional details to the exception."""
        self.details.update(kwargs)
        return self

    def __str__(self) -> str:
        return f"[{self.error_id}] {self.message}"

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"message={self.message!r}, "
            f"error_id={self.error_id!r}, "
            f"category={self.category.value!r}, "
            f"severity={self.severity.value!r}, "
            f"retryable={self.retryable!r})"
        )


def create_exception(
    exception_class: type[CXOBaseException],
    message: str,
    **kwargs: Any,
) -> CXOBaseException:
    """Factory function for creating exceptions with context."""
    return exception_class(message, **kwargs)
