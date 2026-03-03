"""DSPy-related exceptions for the CXO AI Companion."""

from __future__ import annotations

from typing import Any

from cxo_ai_companion.exceptions.base import (
    CXOBaseException,
    ErrorCategory,
    ErrorSeverity,
)


class DSPyError(CXOBaseException):
    """Base exception for DSPy-related errors."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        kwargs.setdefault("category", ErrorCategory.AI_PROCESSING)
        kwargs.setdefault("severity", ErrorSeverity.MEDIUM)
        super().__init__(message=message, **kwargs)


class SignatureError(DSPyError):
    """Raised when signature validation fails."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        kwargs.setdefault("severity", ErrorSeverity.LOW)
        super().__init__(message=message, **kwargs)


class ProgramExecutionError(DSPyError):
    """Raised when a DSPy module execution fails."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        kwargs.setdefault("severity", ErrorSeverity.HIGH)
        kwargs.setdefault("retryable", True)
        super().__init__(message=message, **kwargs)
