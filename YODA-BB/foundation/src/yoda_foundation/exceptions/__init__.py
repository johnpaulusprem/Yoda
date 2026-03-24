"""CXO AI Companion exception hierarchy."""

from __future__ import annotations
from typing import Any
from yoda_foundation.exceptions.base import (
    YodaBaseException, ErrorCategory, ErrorSeverity, create_exception,
)

class AuthenticationError(YodaBaseException):
    def __init__(self, message: str = "Authentication failed", *, reason: str | None = None, auth_method: str | None = None, **kwargs: Any) -> None:
        details = kwargs.pop("details", {}); details.update({"reason": reason, "auth_method": auth_method})
        super().__init__(message, category=ErrorCategory.AUTHENTICATION, severity=ErrorSeverity.HIGH, retryable=False, user_message="Authentication failed.", details=details, **kwargs)

class AuthorizationError(YodaBaseException):
    def __init__(self, message: str = "Permission denied", *, required_permission: str | None = None, user_id: str | None = None, **kwargs: Any) -> None:
        details = kwargs.pop("details", {}); details.update({"required_permission": required_permission, "user_id": user_id})
        super().__init__(message, category=ErrorCategory.AUTHORIZATION, severity=ErrorSeverity.MEDIUM, retryable=False, user_message="Permission denied.", details=details, **kwargs)

class ValidationError(YodaBaseException):
    def __init__(self, message: str = "Validation failed", *, field_name: str | None = None, field_value: Any = None, constraints: list[str] | None = None, **kwargs: Any) -> None:
        details = kwargs.pop("details", {}); details.update({"field_name": field_name})
        super().__init__(message, category=ErrorCategory.VALIDATION, severity=ErrorSeverity.LOW, retryable=False, details=details, **kwargs)

class RateLimitError(YodaBaseException):
    def __init__(self, message: str = "Rate limit exceeded", *, limit: int | None = None, window_seconds: int | None = None, retry_after_seconds: int | None = None, limit_type: str = "requests", **kwargs: Any) -> None:
        details = kwargs.pop("details", {}); details.update({"limit": limit, "retry_after_seconds": retry_after_seconds})
        super().__init__(message, category=ErrorCategory.RATE_LIMIT, severity=ErrorSeverity.LOW, retryable=True, details=details, **kwargs)

class MeetingError(YodaBaseException):
    def __init__(self, message: str = "Meeting operation failed", *, meeting_id: str | None = None, **kwargs: Any) -> None:
        details = kwargs.pop("details", {}); details["meeting_id"] = meeting_id
        super().__init__(message, category=ErrorCategory.MEETING, severity=ErrorSeverity.MEDIUM, details=details, **kwargs)

class TranscriptionError(YodaBaseException):
    def __init__(self, message: str = "Transcription failed", *, meeting_id: str | None = None, segment_info: str | None = None, **kwargs: Any) -> None:
        details = kwargs.pop("details", {}); details.update({"meeting_id": meeting_id, "segment_info": segment_info})
        super().__init__(message, category=ErrorCategory.TRANSCRIPTION, severity=ErrorSeverity.HIGH, retryable=True, details=details, **kwargs)

class AIProcessingError(YodaBaseException):
    def __init__(self, message: str = "AI processing failed", *, model: str | None = None, prompt_tokens: int | None = None, **kwargs: Any) -> None:
        details = kwargs.pop("details", {}); details.update({"model": model, "prompt_tokens": prompt_tokens})
        super().__init__(message, category=ErrorCategory.AI_PROCESSING, severity=ErrorSeverity.HIGH, retryable=True, details=details, **kwargs)

class CalendarError(YodaBaseException):
    def __init__(self, message: str = "Calendar operation failed", *, subscription_id: str | None = None, event_type: str | None = None, **kwargs: Any) -> None:
        details = kwargs.pop("details", {}); details.update({"subscription_id": subscription_id})
        super().__init__(message, category=ErrorCategory.CALENDAR, severity=ErrorSeverity.MEDIUM, retryable=True, details=details, **kwargs)

class ACSError(YodaBaseException):
    def __init__(self, message: str = "ACS operation failed", *, call_connection_id: str | None = None, operation: str | None = None, **kwargs: Any) -> None:
        details = kwargs.pop("details", {}); details.update({"call_connection_id": call_connection_id, "operation": operation})
        super().__init__(message, category=ErrorCategory.ACS, severity=ErrorSeverity.HIGH, retryable=True, details=details, **kwargs)

class DeliveryError(YodaBaseException):
    def __init__(self, message: str = "Delivery failed", *, channel: str | None = None, recipient: str | None = None, **kwargs: Any) -> None:
        details = kwargs.pop("details", {}); details.update({"channel": channel, "recipient": recipient})
        super().__init__(message, category=ErrorCategory.DELIVERY, severity=ErrorSeverity.MEDIUM, retryable=True, details=details, **kwargs)

class ConfigurationError(YodaBaseException):
    def __init__(self, message: str = "Configuration error", *, setting_name: str | None = None, **kwargs: Any) -> None:
        details = kwargs.pop("details", {}); details["setting_name"] = setting_name
        super().__init__(message, category=ErrorCategory.CONFIGURATION, severity=ErrorSeverity.CRITICAL, retryable=False, details=details, **kwargs)

class GraphAPIError(YodaBaseException):
    def __init__(self, message: str = "Graph API error", *, endpoint: str | None = None, status_code: int | None = None, response_body: str | None = None, **kwargs: Any) -> None:
        details = kwargs.pop("details", {}); details.update({"endpoint": endpoint, "status_code": status_code})
        retryable = status_code in (429, 500, 502, 503, 504) if status_code else False
        super().__init__(message, category=ErrorCategory.GRAPH_API, severity=ErrorSeverity.HIGH, retryable=retryable, details=details, **kwargs)
        self.status_code = status_code

class DatabaseError(YodaBaseException):
    def __init__(self, message: str = "Database error", *, operation: str | None = None, table_name: str | None = None, **kwargs: Any) -> None:
        details = kwargs.pop("details", {}); details.update({"operation": operation, "table_name": table_name})
        super().__init__(message, category=ErrorCategory.DATABASE, severity=ErrorSeverity.HIGH, retryable=True, details=details, **kwargs)

class CacheError(YodaBaseException):
    def __init__(self, message: str = "Cache error", *, operation: str | None = None, key: str | None = None, **kwargs: Any) -> None:
        details = kwargs.pop("details", {}); details.update({"operation": operation, "key": key})
        super().__init__(message, category=ErrorCategory.CACHE, severity=ErrorSeverity.LOW, retryable=True, details=details, **kwargs)

class ConnectorError(YodaBaseException):
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

class GovernanceError(YodaBaseException):
    def __init__(self, message: str = "Governance policy violation", *, policy_name: str | None = None, **kwargs: Any) -> None:
        details = kwargs.pop("details", {}); details["policy_name"] = policy_name
        super().__init__(message, category=ErrorCategory.GOVERNANCE, severity=ErrorSeverity.HIGH, retryable=False, details=details, **kwargs)

class ResourceError(YodaBaseException):
    def __init__(self, message: str = "Resource error", *, resource_id: str | None = None, resource_type: str | None = None, **kwargs: Any) -> None:
        details = kwargs.pop("details", {}); details.update({"resource_id": resource_id, "resource_type": resource_type})
        super().__init__(message, category=ErrorCategory.RESOURCE, severity=ErrorSeverity.MEDIUM, retryable=False, details=details, **kwargs)

class ResourceNotFoundError(ResourceError):
    def __init__(self, message: str = "Resource not found", *, resource_id: str | None = None, resource_type: str | None = None, **kwargs: Any) -> None:
        super().__init__(message, resource_id=resource_id, resource_type=resource_type, **kwargs)

from yoda_foundation.exceptions.dspy import (
    DSPyError,
    SignatureError,
    ProgramExecutionError,
)

# --- Exception submodules ported from dhurunthur ---
from yoda_foundation.exceptions.memory import (  # noqa: E402
    MemoryError as MemoryError,
    MemoryStorageError,
    MemoryRetrievalError,
    MemoryNotFoundError,
    MemoryCapacityError,
    MemorySerializationError,
    MemoryPruningError,
    MemoryConsolidationError,
    MemoryContextError,
    MemoryDecayError,
    MemoryTierError,
)
from yoda_foundation.exceptions.guardrails import (  # noqa: E402
    GuardrailError,
    ContentBlockedError,
    JailbreakDetectedError,
    PolicyViolationError,
    TopicViolationError,
    FactCheckError,
    ModerationError,
    GuardrailTimeoutError,
)
from yoda_foundation.exceptions.resilience import (  # noqa: E402
    ResilienceError,
    RetryError,
    RetryExhaustedError,
    RetryBudgetExceededError,
    CircuitBreakerError,
    CircuitBreakerOpenError,
    FallbackError,
    FallbackFailedError,
    RecoveryError,
    StateRecoveryError,
    CheckpointError,
)
from yoda_foundation.exceptions.events import (  # noqa: E402
    EventError,
    EventPublishError,
    EventSubscriptionError,
    EventHandlerError,
    EventTimeoutError,
    EventDeliveryError,
    EventTriggerError,
    EventValidationError,
)
from yoda_foundation.exceptions.data_access import (  # noqa: E402
    DataAccessError,
    DatabaseConnectionError,
    QueryExecutionError,
    TransactionError,
    ConnectionPoolError,
    DocumentNotFoundError,
    DocumentAccessError,
    GraphTraversalError,
    NoSQLError,
)
from yoda_foundation.exceptions.observability import (  # noqa: E402
    ObservabilityError,
    TracingError,
    MetricsError,
    ExporterError,
    PropagationError,
    InstrumentationError,
)
from yoda_foundation.exceptions.auth import (  # noqa: E402
    AuthenticationError as DhurunthurAuthenticationError,
    AuthorizationError as DhurunthurAuthorizationError,
    PermissionDeniedError,
)

__all__ = [
    "YodaBaseException", "ErrorCategory", "ErrorSeverity", "create_exception",
    "AuthenticationError", "AuthorizationError", "ValidationError", "RateLimitError",
    "MeetingError", "TranscriptionError", "AIProcessingError", "CalendarError",
    "ACSError", "DeliveryError", "ConfigurationError", "GraphAPIError",
    "DatabaseError", "CacheError", "ConnectorError", "ConnectorNotConnectedError", "ConnectorTimeoutError",
    "GovernanceError", "ResourceError", "ResourceNotFoundError",
    "DSPyError", "SignatureError", "ProgramExecutionError",
    # memory
    "MemoryError", "MemoryStorageError", "MemoryRetrievalError", "MemoryNotFoundError",
    "MemoryCapacityError", "MemorySerializationError", "MemoryPruningError",
    "MemoryConsolidationError", "MemoryContextError", "MemoryDecayError", "MemoryTierError",
    # guardrails
    "GuardrailError", "ContentBlockedError", "JailbreakDetectedError",
    "PolicyViolationError", "TopicViolationError", "FactCheckError",
    "ModerationError", "GuardrailTimeoutError",
    # resilience
    "ResilienceError", "RetryError", "RetryExhaustedError", "RetryBudgetExceededError",
    "CircuitBreakerError", "CircuitBreakerOpenError", "FallbackError", "FallbackFailedError",
    "RecoveryError", "StateRecoveryError", "CheckpointError",
    # events
    "EventError", "EventPublishError", "EventSubscriptionError", "EventHandlerError",
    "EventTimeoutError", "EventDeliveryError", "EventTriggerError", "EventValidationError",
    # data_access
    "DataAccessError", "DatabaseConnectionError", "QueryExecutionError", "TransactionError",
    "ConnectionPoolError", "DocumentNotFoundError", "DocumentAccessError",
    "GraphTraversalError", "NoSQLError",
    # observability
    "ObservabilityError", "TracingError", "MetricsError", "ExporterError",
    "PropagationError", "InstrumentationError",
    # auth (dhurunthur — aliased to avoid conflict with existing classes)
    "DhurunthurAuthenticationError", "DhurunthurAuthorizationError", "PermissionDeniedError",
]

# Aliases for dhurunthur modules that reference these names
AgenticConnectionError = ConnectorError

class WebhookDeliveryError(DeliveryError):
    def __init__(self, message: str = "Webhook delivery failed", **kwargs: Any) -> None:
        super().__init__(message, channel="webhook", **kwargs)

class StreamBufferFullError(EventError):
    def __init__(self, message: str = "Stream buffer full", **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
