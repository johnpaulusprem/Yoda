"""
Security context for the Agentic AI Component Library.

This module provides the SecurityContext class that must be propagated
through all operations for authorization, audit, and compliance.

Example:
    ```python
    from yoda_foundation.security import (
        SecurityContext,
        create_security_context,
    )

    async def protected_operation(
        data: dict,
        security_context: SecurityContext,
    ) -> Result:
        # Check permission
        if not security_context.has_permission("data.write"):
            raise AuthorizationError(required_permission="data.write")

        # Log access for audit
        logger.info(
            "Data operation",
            user_id=security_context.user_id,
            operation="write",
        )

        return await process(data)
    ```
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class ContextType(Enum):
    """Type of security context."""

    USER = "user"
    SERVICE = "service"
    SYSTEM = "system"
    ANONYMOUS = "anonymous"


@dataclass(frozen=True)
class Permission:
    """
    Represents a permission in the RBAC system.

    Permissions follow the format: resource.action or resource.action:scope

    Attributes:
        resource: The resource type (e.g., "document", "user", "agent")
        action: The action type (e.g., "read", "write", "delete", "execute")
        scope: Optional scope restriction (e.g., "own", "team", "org")

    Example:
        ```python
        # Basic permission
        read_docs = Permission("document", "read")

        # Scoped permission
        edit_own = Permission("document", "write", scope="own")

        # Wildcard permission
        admin = Permission("*", "*")
        ```
    """

    resource: str
    action: str
    scope: str | None = None

    def __str__(self) -> str:
        """Return string representation."""
        if self.scope:
            return f"{self.resource}.{self.action}:{self.scope}"
        return f"{self.resource}.{self.action}"

    @classmethod
    def from_string(cls, permission_str: str) -> Permission:
        """
        Parse permission from string format.

        Args:
            permission_str: Permission string (e.g., "document.read:own")

        Returns:
            Permission instance

        Example:
            ```python
            perm = Permission.from_string("document.write:team")
            assert perm.resource == "document"
            assert perm.action == "write"
            assert perm.scope == "team"
            ```
        """
        # Handle scope
        scope = None
        if ":" in permission_str:
            permission_str, scope = permission_str.rsplit(":", 1)

        # Handle resource.action
        if "." in permission_str:
            resource, action = permission_str.rsplit(".", 1)
        else:
            resource = permission_str
            action = "*"

        return cls(resource=resource, action=action, scope=scope)

    def matches(self, required: Permission) -> bool:
        """
        Check if this permission satisfies the required permission.

        Wildcards (*) match any value.

        Args:
            required: The required permission to check against

        Returns:
            True if this permission satisfies the requirement

        Example:
            ```python
            admin = Permission("*", "*")
            read_doc = Permission("document", "read")

            assert admin.matches(read_doc)  # Wildcard matches all
            assert read_doc.matches(read_doc)  # Exact match
            ```
        """
        # Check resource
        if self.resource != "*" and self.resource != required.resource:
            return False

        # Check action
        if self.action != "*" and self.action != required.action:
            return False

        # Check scope: if required has a scope, held permission must have
        # matching scope or wildcard scope. A scopeless held permission does
        # NOT implicitly match all scopes (prevents privilege escalation).
        if required.scope is not None:
            if self.scope is None or (self.scope != "*" and self.scope != required.scope):
                return False

        return True


@dataclass
class SecurityContext:
    """
    Security context that must be propagated through all operations.

    Contains user identity, permissions, and metadata needed for
    authorization, audit logging, and multi-tenancy.

    Attributes:
        user_id: Unique identifier for the user or service
        tenant_id: Tenant identifier for multi-tenancy
        context_type: Type of context (user, service, system, anonymous)
        permissions: Set of granted permissions
        roles: Set of assigned roles
        session_id: Current session identifier
        correlation_id: Request correlation ID for tracing
        metadata: Additional context metadata
        created_at: When the context was created
        expires_at: When the context expires

    Example:
        ```python
        context = SecurityContext(
            user_id="user_123",
            tenant_id="tenant_456",
            permissions=frozenset([
                Permission("document", "read"),
                Permission("document", "write"),
            ]),
            roles=frozenset(["editor"]),
        )

        # Check permission
        if context.has_permission("document.delete"):
            await delete_document(doc_id)

        # Get audit info
        audit_info = context.to_audit_dict()
        ```
    """

    user_id: str
    tenant_id: str | None = None
    context_type: ContextType = ContextType.USER
    permissions: frozenset[Permission] = field(default_factory=frozenset)
    roles: frozenset[str] = field(default_factory=frozenset)
    session_id: str | None = None
    correlation_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate and normalize the context."""
        # Ensure permissions is a frozenset
        if isinstance(self.permissions, (list, set)):
            object.__setattr__(
                self,
                "permissions",
                frozenset(self.permissions),
            )

        # Ensure roles is a frozenset
        if isinstance(self.roles, (list, set)):
            object.__setattr__(self, "roles", frozenset(self.roles))

    @property
    def is_authenticated(self) -> bool:
        """Check if the context represents an authenticated user."""
        return self.context_type != ContextType.ANONYMOUS

    @property
    def is_system(self) -> bool:
        """Check if this is a system context."""
        return self.context_type == ContextType.SYSTEM

    @property
    def is_expired(self) -> bool:
        """Check if the context has expired."""
        if self.expires_at is None:
            return False
        return datetime.now(UTC) > self.expires_at

    def has_permission(self, permission: str) -> bool:
        """
        Check if the context has a specific permission.

        Args:
            permission: Permission string (e.g., "document.read")

        Returns:
            True if the permission is granted

        Example:
            ```python
            if context.has_permission("document.write"):
                await save_document(doc)
            else:
                raise AuthorizationError(
                    required_permission="document.write"
                )
            ```
        """
        if self.is_expired:
            return False

        required = Permission.from_string(permission)

        # Check if any granted permission satisfies the requirement
        return any(perm.matches(required) for perm in self.permissions)

    def has_all_permissions(self, permissions: list[str]) -> bool:
        """
        Check if the context has all specified permissions.

        Args:
            permissions: List of permission strings

        Returns:
            True if all permissions are granted

        Example:
            ```python
            if context.has_all_permissions(["user.read", "user.write"]):
                await update_user(user_id, data)
            ```
        """
        return all(self.has_permission(p) for p in permissions)

    def has_any_permission(self, permissions: list[str]) -> bool:
        """
        Check if the context has any of the specified permissions.

        Args:
            permissions: List of permission strings

        Returns:
            True if any permission is granted

        Example:
            ```python
            if context.has_any_permission(["admin.*", "moderator.*"]):
                await moderate_content(content_id)
            ```
        """
        return any(self.has_permission(p) for p in permissions)

    def has_role(self, role: str) -> bool:
        """
        Check if the context has a specific role.

        Args:
            role: Role name

        Returns:
            True if the role is assigned

        Example:
            ```python
            if context.has_role("admin"):
                show_admin_panel()
            ```
        """
        return role in self.roles

    def require_permission(self, permission: str) -> None:
        """
        Require a permission, raising an error if not granted.

        Args:
            permission: Permission string

        Raises:
            AuthorizationError: If permission is not granted

        Example:
            ```python
            context.require_permission("admin.settings")
            # Only reached if permission is granted
            await update_settings(settings)
            ```
        """
        if not self.has_permission(permission):
            from yoda_foundation.exceptions import AuthorizationError

            raise AuthorizationError(
                message=f"Permission denied: {permission}",
                required_permission=permission,
                user_id=self.user_id,
            )

    def require_authenticated(self) -> None:
        """
        Require authentication, raising an error if not authenticated.

        Raises:
            AuthenticationError: If not authenticated

        Example:
            ```python
            context.require_authenticated()
            # Only reached if authenticated
            user_profile = await get_profile(context.user_id)
            ```
        """
        if not self.is_authenticated:
            from yoda_foundation.exceptions import AuthenticationError

            raise AuthenticationError(
                message="Authentication required",
                reason="anonymous_context",
            )

    def with_correlation_id(self, correlation_id: str) -> SecurityContext:
        """
        Create a new context with an updated correlation ID.

        Args:
            correlation_id: New correlation ID

        Returns:
            New SecurityContext with updated correlation ID

        Example:
            ```python
            request_context = context.with_correlation_id(request.id)
            await process_request(request, request_context)
            ```
        """
        return SecurityContext(
            user_id=self.user_id,
            tenant_id=self.tenant_id,
            context_type=self.context_type,
            permissions=self.permissions,
            roles=self.roles,
            session_id=self.session_id,
            correlation_id=correlation_id,
            metadata=self.metadata.copy(),
            created_at=self.created_at,
            expires_at=self.expires_at,
        )

    def with_metadata(self, **kwargs: Any) -> SecurityContext:
        """
        Create a new context with additional metadata.

        Args:
            **kwargs: Metadata to add

        Returns:
            New SecurityContext with updated metadata

        Example:
            ```python
            agent_context = context.with_metadata(
                agent_name="research_agent",
                run_id="run_123",
            )
            ```
        """
        new_metadata = {**self.metadata, **kwargs}
        return SecurityContext(
            user_id=self.user_id,
            tenant_id=self.tenant_id,
            context_type=self.context_type,
            permissions=self.permissions,
            roles=self.roles,
            session_id=self.session_id,
            correlation_id=self.correlation_id,
            metadata=new_metadata,
            created_at=self.created_at,
            expires_at=self.expires_at,
        )

    def to_dict(self) -> dict[str, Any]:
        """
        Convert context to dictionary for serialization.

        Returns:
            Dictionary representation of the context

        Example:
            ```python
            context_dict = context.to_dict()
            await cache.set(f"context:{session_id}", context_dict)
            ```
        """
        return {
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "context_type": self.context_type.value,
            "permissions": [str(p) for p in self.permissions],
            "roles": list(self.roles),
            "session_id": self.session_id,
            "correlation_id": self.correlation_id,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }

    def to_audit_dict(self) -> dict[str, Any]:
        """
        Convert context to dictionary for audit logging.

        Returns a minimal dictionary safe for audit logs.

        Returns:
            Dictionary with audit-relevant fields

        Example:
            ```python
            await audit_log.record(
                action="document.delete",
                resource_id=doc_id,
                context=context.to_audit_dict(),
            )
            ```
        """
        return {
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "context_type": self.context_type.value,
            "session_id": self.session_id,
            "correlation_id": self.correlation_id,
        }

    def to_log_dict(self) -> dict[str, Any]:
        """
        Convert context to dictionary for structured logging.

        Returns:
            Dictionary suitable for log context
        """
        return {
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "context_type": self.context_type.value,
            "roles": list(self.roles)[:5],  # Limit for log size
            "session_id": self.session_id,
            "correlation_id": self.correlation_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SecurityContext:
        """
        Create context from dictionary.

        Args:
            data: Dictionary representation

        Returns:
            SecurityContext instance

        Example:
            ```python
            context_dict = await cache.get(f"context:{session_id}")
            context = SecurityContext.from_dict(context_dict)
            ```
        """
        permissions = frozenset(Permission.from_string(p) for p in data.get("permissions", []))
        roles = frozenset(data.get("roles", []))

        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)

        expires_at = data.get("expires_at")
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at)

        return cls(
            user_id=data["user_id"],
            tenant_id=data.get("tenant_id"),
            context_type=ContextType(data.get("context_type", "user")),
            permissions=permissions,
            roles=roles,
            session_id=data.get("session_id"),
            correlation_id=data.get("correlation_id"),
            metadata=data.get("metadata", {}),
            created_at=created_at or datetime.now(UTC),
            expires_at=expires_at,
        )


def create_security_context(
    user_id: str,
    tenant_id: str | None = None,
    permissions: list[str] | None = None,
    roles: list[str] | None = None,
    session_id: str | None = None,
    correlation_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    expires_in_seconds: int | None = None,
) -> SecurityContext:
    """
    Create a new security context for a user.

    Args:
        user_id: User identifier
        tenant_id: Tenant identifier
        permissions: List of permission strings
        roles: List of role names
        session_id: Session identifier
        correlation_id: Correlation ID for tracing
        metadata: Additional metadata
        expires_in_seconds: Context expiry time

    Returns:
        SecurityContext instance

    Example:
        ```python
        context = create_security_context(
            user_id="user_123",
            tenant_id="tenant_456",
            permissions=["document.read", "document.write"],
            roles=["editor"],
            expires_in_seconds=3600,
        )
        ```
    """
    from datetime import timedelta

    permission_set = frozenset(Permission.from_string(p) for p in (permissions or []))
    role_set = frozenset(roles or [])

    now = datetime.now(UTC)
    expires_at = None
    if expires_in_seconds:
        expires_at = now + timedelta(seconds=expires_in_seconds)

    return SecurityContext(
        user_id=user_id,
        tenant_id=tenant_id,
        context_type=ContextType.USER,
        permissions=permission_set,
        roles=role_set,
        session_id=session_id or str(uuid.uuid4()),
        correlation_id=correlation_id,
        metadata=metadata or {},
        created_at=now,
        expires_at=expires_at,
    )


def create_system_context(
    service_name: str = "system",
    correlation_id: str | None = None,
) -> SecurityContext:
    """
    Create a system context with all permissions.

    System contexts are used for background jobs, migrations,
    and internal operations that require full access.

    Args:
        service_name: Name of the service/job
        correlation_id: Correlation ID for tracing

    Returns:
        SecurityContext with full permissions

    Example:
        ```python
        # For a background job
        system_ctx = create_system_context(
            service_name="data_sync_job",
            correlation_id=job_id,
        )
        await sync_data(system_ctx)
        ```
    """
    return SecurityContext(
        user_id=f"system:{service_name}",
        context_type=ContextType.SYSTEM,
        permissions=frozenset([Permission("*", "*")]),
        roles=frozenset(["system"]),
        correlation_id=correlation_id,
        metadata={"service_name": service_name},
    )


def create_anonymous_context(
    correlation_id: str | None = None,
) -> SecurityContext:
    """
    Create an anonymous context with no permissions.

    Used for unauthenticated requests or public endpoints.

    Args:
        correlation_id: Correlation ID for tracing

    Returns:
        SecurityContext with no permissions

    Example:
        ```python
        # For public API endpoints
        anon_ctx = create_anonymous_context()
        public_data = await get_public_info(anon_ctx)
        ```
    """
    return SecurityContext(
        user_id="anonymous",
        context_type=ContextType.ANONYMOUS,
        permissions=frozenset(),
        roles=frozenset(),
        correlation_id=correlation_id,
    )
