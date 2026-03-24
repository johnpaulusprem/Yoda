"""
Authentication and authorization exceptions for the Agentic AI Component Library.

This module provides exceptions for authentication failures (401),
authorization failures (403), and permission-related errors.

Example:
    ```python
    from yoda_foundation.exceptions import (
        AuthenticationError,
        AuthorizationError,
        PermissionDeniedError,
    )

    async def protected_operation(security_context: SecurityContext) -> None:
        if not security_context.is_authenticated:
            raise AuthenticationError(
                message="User is not authenticated",
                auth_method="bearer_token",
            )

        if not security_context.has_permission("admin.write"):
            raise PermissionDeniedError(
                required_permission="admin.write",
                resource="settings",
                action="update",
            )
    ```
"""

from __future__ import annotations

from typing import Any

from yoda_foundation.exceptions.base import (
    AgenticBaseException,
    ErrorCategory,
    ErrorSeverity,
)


class AuthenticationError(AgenticBaseException):
    """
    Authentication error (HTTP 401 equivalent).

    Raised when a user or agent fails to authenticate,
    such as invalid credentials, expired tokens, or missing auth.

    Attributes:
        auth_method: The authentication method that failed
        reason: Specific reason for authentication failure

    Example:
        ```python
        raise AuthenticationError(
            message="Invalid API key",
            auth_method="api_key",
            reason="key_expired",
        )
        ```
    """

    def __init__(
        self,
        message: str = "Authentication failed",
        *,
        auth_method: str | None = None,
        reason: str | None = None,
        suggestions: list[str] | None = None,
        cause: Exception | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize authentication error.

        Args:
            message: Human-readable error description
            auth_method: The authentication method that failed (e.g., "bearer_token", "api_key")
            reason: Specific reason for failure (e.g., "token_expired", "invalid_signature")
            suggestions: Actionable remediation steps
            cause: Original exception
            details: Additional context
        """
        self.auth_method = auth_method
        self.reason = reason

        extra_details = {
            "auth_method": auth_method,
            "reason": reason,
            "http_status": 401,
        }

        merged_details = {**extra_details, **(details or {})}

        default_suggestions = [
            "Verify your credentials are correct",
            "Check if your token has expired",
            "Ensure you're using the correct authentication method",
        ]

        super().__init__(
            message=message,
            category=ErrorCategory.AUTHENTICATION,
            severity=ErrorSeverity.MEDIUM,
            retryable=False,
            user_message="Authentication failed. Please check your credentials.",
            suggestions=suggestions or default_suggestions,
            cause=cause,
            details=merged_details,
        )


class AuthorizationError(AgenticBaseException):
    """
    Authorization error (HTTP 403 equivalent).

    Raised when an authenticated user or agent lacks permission
    to perform the requested operation.

    Attributes:
        required_permission: The permission that was required
        resource: The resource that access was attempted on
        action: The action that was attempted

    Example:
        ```python
        raise AuthorizationError(
            message="User does not have permission to delete records",
            required_permission="records.delete",
            resource="patient_records",
            action="delete",
        )
        ```
    """

    def __init__(
        self,
        message: str = "Access denied",
        *,
        required_permission: str | None = None,
        resource: str | None = None,
        action: str | None = None,
        user_id: str | None = None,
        suggestions: list[str] | None = None,
        cause: Exception | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize authorization error.

        Args:
            message: Human-readable error description
            required_permission: The permission that was required
            resource: The resource that access was attempted on
            action: The action that was attempted
            user_id: The user who attempted the action (for logging)
            suggestions: Actionable remediation steps
            cause: Original exception
            details: Additional context
        """
        self.required_permission = required_permission
        self.resource = resource
        self.action = action
        self.user_id = user_id

        extra_details = {
            "required_permission": required_permission,
            "resource": resource,
            "action": action,
            "http_status": 403,
        }
        if user_id:
            extra_details["user_id"] = user_id

        merged_details = {**extra_details, **(details or {})}

        default_suggestions = [
            "Contact your administrator to request access",
            "Verify you're using the correct account",
        ]
        if required_permission:
            default_suggestions.insert(0, f"Request the '{required_permission}' permission")

        super().__init__(
            message=message,
            category=ErrorCategory.AUTHORIZATION,
            severity=ErrorSeverity.MEDIUM,
            retryable=False,
            user_message="You don't have permission to perform this action.",
            suggestions=suggestions or default_suggestions,
            cause=cause,
            details=merged_details,
        )


class PermissionDeniedError(AuthorizationError):
    """
    Specific permission denied error.

    A more specific form of AuthorizationError when a specific
    permission check fails.

    Example:
        ```python
        if not security_context.has_permission("phi.read"):
            raise PermissionDeniedError(
                required_permission="phi.read",
                resource=f"patient:{patient_id}",
                action="read",
            )
        ```
    """

    def __init__(
        self,
        *,
        required_permission: str,
        resource: str | None = None,
        action: str | None = None,
        user_id: str | None = None,
        suggestions: list[str] | None = None,
        cause: Exception | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize permission denied error.

        Args:
            required_permission: The specific permission that was required
            resource: The resource that access was attempted on
            action: The action that was attempted
            user_id: The user who attempted the action
            suggestions: Actionable remediation steps
            cause: Original exception
            details: Additional context
        """
        message = f"Permission denied: '{required_permission}' required"
        if resource:
            message += f" for resource '{resource}'"
        if action:
            message += f" (action: {action})"

        super().__init__(
            message=message,
            required_permission=required_permission,
            resource=resource,
            action=action,
            user_id=user_id,
            suggestions=suggestions,
            cause=cause,
            details=details,
        )
