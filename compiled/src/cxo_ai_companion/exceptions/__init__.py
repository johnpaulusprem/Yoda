"""CXO AI Companion exception hierarchy."""

from __future__ import annotations
from typing import Any
from cxo_ai_companion.exceptions.base import (
    CXOBaseException, ErrorCategory, ErrorSeverity, create_exception,
)

class AuthenticationError(CXOBaseException):
    def __init__(self, message: str = "Authentication failed", *, reason: str | None = None, auth_method: str | None = None, **kwargs: Any) -> None:
        details = kwargs.pop("details", {}); details.update({"reason": reason, "auth_method": auth_method})
        super().__init__(message, category=ErrorCategory.AUTHENTICATION, severity=ErrorSeverity.HIGH, retryable=False, user_message="Authentication failed.", details=details, **kwargs)

class AuthorizationError(CXOBaseException):
    def __init__(self, message: str = "Permission denied", *, required_permission: str | None = None, user_id: str | None = None, **kwargs: Any) -> None:
        details = kwargs.pop("details", {}); details.update({"required_permission": required_permission, "user_id": user_id})
        super().__init__(message, category=ErrorCategory.AUTHORIZATION, severity=ErrorSeverity.MEDIUM, retryable=False, user_message="Permission denied.", details=details, **kwargs)

class ValidationError(CXOBaseException):
    def __init__(self, message: str = "Validation failed", *, field_name: str | None = None, field_value: Any = None, constraints: list[str] | None = None, **kwargs: Any) -> None:
        details = kwargs.pop("details", {}); details.update({"field_name": field_name})
        super().__init__(message, category=ErrorCategory.VALIDATION, severity=ErrorSeverity.LOW, retryable=False, details=details, **kwargs)

class RateLimitError(CXOBaseException):
    def __init__(self, message: str = "Rate limit exceeded", *, limit: int | None = None, window_seconds: int | None = None, retry_after_seconds: int | None = None, limit_type: str = "requests", **kwargs: Any) -> None:
        details = kwargs.pop("details", {}); details.update({"limit": limit, "retry_after_seconds": retry_after_seconds})
        super().__init__(message, category=ErrorCategory.RATE_LIMIT, severity=ErrorSeverity.LOW, retryable=True, details=details, **kwargs)

class MeetingError(CXOBaseException):
    def __init__(self, message: str = "Meeting operation failed", *, meeting_id: str | None = None, **kwargs: Any) -> None:
        details = kwargs.pop("details", {}); details["meeting_id"] = meeting_id
        super().__init__(message, category=ErrorCategory.MEETING, severity=ErrorSeverity.MEDIUM, details=details, **kwargs)

class TranscriptionError(CXOBaseException):
    def __init__(self, message: str = "Transcription failed", *, meeting_id: str | None = None, segment_info: str | None = None, **kwargs: Any) -> None:
        details = kwargs.pop("details", {}); details.update({"meeting_id": meeting_id, "segment_info": segment_info})
        super().__init__(message, category=ErrorCategory.TRANSCRIPTION, severity=ErrorSeverity.HIGH, retryable=True, details=details, **kwargs)

class AIProcessingError(CXOBaseException):
    def __init__(self, message: str = "AI processing failed", *, model: str | None = None, prompt_tokens: int | None = None, **kwargs: Any) -> None:
        details = kwargs.pop("details", {}); details.update({"model": model, "prompt_tokens": prompt_tokens})
        super().__init__(message, category=ErrorCategory.AI_PROCESSING, severity=ErrorSeverity.HIGH, retryable=True, details=details, **kwargs)

class CalendarError(CXOBaseException):
    def __init__(self, message: str = "Calendar operation failed", *, subscription_id: str | None = None, event_type: str | None = None, **kwargs: Any) -> None:
        details = kwargs.pop("details", {}); details.update({"subscription_id": subscription_id})
        super().__init__(message, category=ErrorCategory.CALENDAR, severity=ErrorSeverity.MEDIUM, retryable=True, details=details, **kwargs)

class ACSError(CXOBaseException):
    def __init__(self, message: str = "ACS operation failed", *, call_connection_id: str | None = None, operation: str | None = None, **kwargs: Any) -> None:
        details = kwargs.pop("details", {}); details.update({"call_connection_id": call_connection_id, "operation": operation})
        super().__init__(message, category=ErrorCategory.ACS, severity=ErrorSeverity.HIGH, retryable=True, details=details, **kwargs)

class DeliveryError(CXOBaseException):
    def __init__(self, message: str = "Delivery failed", *, channel: str | None = None, recipient: str | None = None, **kwargs: Any) -> None:
        details = kwargs.pop("details", {}); details.update({"channel": channel, "recipient": recipient})
        super().__init__(message, category=ErrorCategory.DELIVERY, severity=ErrorSeverity.MEDIUM, retryable=True, details=details, **kwargs)

class ConfigurationError(CXOBaseException):
    def __init__(self, message: str = "Configuration error", *, setting_name: str | None = None, **kwargs: Any) -> None:
        details = kwargs.pop("details", {}); details["setting_name"] = setting_name
        super().__init__(message, category=ErrorCategory.CONFIGURATION, severity=ErrorSeverity.CRITICAL, retryable=False, details=details, **kwargs)

class GraphAPIError(CXOBaseException):
    def __init__(self, message: str = "Graph API error", *, endpoint: str | None = None, status_code: int | None = None, response_body: str | None = None, **kwargs: Any) -> None:
        details = kwargs.pop("details", {}); details.update({"endpoint": endpoint, "status_code": status_code})
        retryable = status_code in (429, 500, 502, 503, 504) if status_code else False
        super().__init__(message, category=ErrorCategory.GRAPH_API, severity=ErrorSeverity.HIGH, retryable=retryable, details=details, **kwargs)
        self.status_code = status_code

class DatabaseError(CXOBaseException):
    def __init__(self, message: str = "Database error", *, operation: str | None = None, table_name: str | None = None, **kwargs: Any) -> None:
        details = kwargs.pop("details", {}); details.update({"operation": operation, "table_name": table_name})
        super().__init__(message, category=ErrorCategory.DATABASE, severity=ErrorSeverity.HIGH, retryable=True, details=details, **kwargs)

class CacheError(CXOBaseException):
    def __init__(self, message: str = "Cache error", *, operation: str | None = None, key: str | None = None, **kwargs: Any) -> None:
        details = kwargs.pop("details", {}); details.update({"operation": operation, "key": key})
        super().__init__(message, category=ErrorCategory.CACHE, severity=ErrorSeverity.LOW, retryable=True, details=details, **kwargs)

class ConnectorError(CXOBaseException):
    def __init__(self, message: str = "Connector operation failed", *, connector_id: str | None = None, connector_type: str | None = None, **kwargs: Any) -> None:
        details = kwargs.pop("details", {}); details.update({"connector_id": connector_id, "connector_type": connector_type})
        super().__init__(message, category=ErrorCategory.NETWORK, severity=ErrorSeverity.MEDIUM, retryable=True, details=details, **kwargs)

class ConnectorNotConnectedError(ConnectorError):
    def __init__(self, message: str = "Connector is not connected", **kwargs: Any) -> None:
        super().__init__(message, user_message="Service not available.", **kwargs)

class ConnectorTimeoutError(ConnectorError):
    def __init__(self, message: str = "Connector operation timed out", *, timeout_seconds: float | None = None, operation: str | None = None, **kwargs: Any) -> None:
        details = kwargs.pop("details", {}); details.update({"timeout_seconds": timeout_seconds, "operation": operation})
        super().__init__(message, user_message="Operation timed out.", details=details, **kwargs)

from cxo_ai_companion.exceptions.dspy import (
    DSPyError,
    SignatureError,
    ProgramExecutionError,
)

__all__ = [
    "CXOBaseException", "ErrorCategory", "ErrorSeverity", "create_exception",
    "AuthenticationError", "AuthorizationError", "ValidationError", "RateLimitError",
    "MeetingError", "TranscriptionError", "AIProcessingError", "CalendarError",
    "ACSError", "DeliveryError", "ConfigurationError", "GraphAPIError",
    "DatabaseError", "CacheError", "ConnectorError", "ConnectorNotConnectedError", "ConnectorTimeoutError",
    "DSPyError", "SignatureError", "ProgramExecutionError",
]
