"""
Security context for the CXO AI Companion.

Provides SecurityContext that must be propagated through all operations
for authorization, audit, and compliance.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class ContextType(Enum):
    """Type of security context (user, service, system, or anonymous)."""

    USER = "user"
    SERVICE = "service"
    SYSTEM = "system"
    ANONYMOUS = "anonymous"


@dataclass(frozen=True)
class Permission:
    """Represents a permission in the RBAC system.

    Format: ``resource.action`` or ``resource.action:scope``.  Wildcard
    ``*`` matches any resource, action, or scope.

    Attributes:
        resource: The resource name (e.g. ``meetings``, ``documents``).
        action: The action name (e.g. ``read``, ``write``, ``*``).
        scope: Optional scope qualifier (e.g. a tenant or project ID).
    """

    resource: str
    action: str
    scope: str | None = None

    def __str__(self) -> str:
        if self.scope:
            return f"{self.resource}.{self.action}:{self.scope}"
        return f"{self.resource}.{self.action}"

    @classmethod
    def from_string(cls, permission_str: str) -> Permission:
        """Parse permission from string format (e.g. ``"documents.read:tenant1"``).

        Args:
            permission_str: A permission string in ``resource.action[:scope]`` format.

        Returns:
            A :class:`Permission` instance.
        """
        scope = None
        if ":" in permission_str:
            permission_str, scope = permission_str.rsplit(":", 1)

        if "." in permission_str:
            resource, action = permission_str.rsplit(".", 1)
        else:
            resource = permission_str
            action = "*"

        return cls(resource=resource, action=action, scope=scope)

    def matches(self, required: Permission) -> bool:
        """Check if this permission satisfies the required permission.

        Wildcards (``*``) in resource, action, or scope match anything.

        Args:
            required: The permission that must be satisfied.

        Returns:
            ``True`` if this permission grants the required access.
        """
        if self.resource != "*" and self.resource != required.resource:
            return False
        if self.action != "*" and self.action != required.action:
            return False
        if required.scope is not None:
            if self.scope is None or (self.scope != "*" and self.scope != required.scope):
                return False
        return True


@dataclass
class SecurityContext:
    """Security context propagated through all operations.

    Contains user identity, permissions, and metadata needed for
    authorization, audit logging, and multi-tenancy. Must be passed
    through all service and pipeline calls.

    Attributes:
        user_id: Unique user or service identifier.
        tenant_id: Azure AD tenant identifier for multi-tenancy.
        context_type: Whether this is a user, service, system, or anonymous context.
        permissions: Immutable set of RBAC permissions granted.
        roles: Immutable set of role names assigned.
        session_id: Unique session identifier for tracking.
        correlation_id: Request correlation ID for distributed tracing.
        metadata: Arbitrary metadata (name, email, auth method, etc.).
        created_at: UTC timestamp when the context was created.
        expires_at: Optional UTC expiration timestamp.
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
        if isinstance(self.permissions, (list, set)):
            object.__setattr__(self, "permissions", frozenset(self.permissions))
        if isinstance(self.roles, (list, set)):
            object.__setattr__(self, "roles", frozenset(self.roles))

    @property
    def is_authenticated(self) -> bool:
        return self.context_type != ContextType.ANONYMOUS

    @property
    def is_system(self) -> bool:
        return self.context_type == ContextType.SYSTEM

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.now(UTC) > self.expires_at

    def has_permission(self, permission: str) -> bool:
        """Check if the context has a specific permission.

        Args:
            permission: Permission string (e.g. ``"documents.read"``).

        Returns:
            ``True`` if any granted permission satisfies the requirement.
        """
        if self.is_expired:
            return False
        required = Permission.from_string(permission)
        return any(perm.matches(required) for perm in self.permissions)

    def has_all_permissions(self, permissions: list[str]) -> bool:
        """Return ``True`` if the context has every listed permission.

        Args:
            permissions: List of permission strings to check.
        """
        return all(self.has_permission(p) for p in permissions)

    def has_any_permission(self, permissions: list[str]) -> bool:
        """Return ``True`` if the context has at least one listed permission.

        Args:
            permissions: List of permission strings to check.
        """
        return any(self.has_permission(p) for p in permissions)

    def has_role(self, role: str) -> bool:
        """Return ``True`` if the context includes the given role.

        Args:
            role: Role name to check.
        """
        return role in self.roles

    def require_permission(self, permission: str) -> None:
        """Require a permission, raising an error if not granted.

        Args:
            permission: Permission string that must be satisfied.

        Raises:
            AuthorizationError: If the permission is not granted.
        """
        if not self.has_permission(permission):
            from cxo_ai_companion.exceptions import AuthorizationError

            raise AuthorizationError(
                message=f"Permission denied: {permission}",
                required_permission=permission,
                user_id=self.user_id,
            )

    def require_authenticated(self) -> None:
        """Raise ``AuthenticationError`` if the context is anonymous."""
        if not self.is_authenticated:
            from cxo_ai_companion.exceptions import AuthenticationError

            raise AuthenticationError(message="Authentication required", reason="anonymous_context")

    def with_correlation_id(self, correlation_id: str) -> SecurityContext:
        """Return a copy of this context with a new correlation ID.

        Args:
            correlation_id: The correlation ID to set.
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
        """Return a copy of this context with additional metadata merged in.

        Args:
            **kwargs: Key-value pairs to merge into the metadata dict.
        """
        return SecurityContext(
            user_id=self.user_id,
            tenant_id=self.tenant_id,
            context_type=self.context_type,
            permissions=self.permissions,
            roles=self.roles,
            session_id=self.session_id,
            correlation_id=self.correlation_id,
            metadata={**self.metadata, **kwargs},
            created_at=self.created_at,
            expires_at=self.expires_at,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the full context to a dictionary."""
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
        """Serialize identity fields for audit logging (no permissions)."""
        return {
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "context_type": self.context_type.value,
            "session_id": self.session_id,
            "correlation_id": self.correlation_id,
        }

    def to_log_dict(self) -> dict[str, Any]:
        """Serialize a compact subset of fields for structured logging."""
        return {
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "context_type": self.context_type.value,
            "roles": list(self.roles)[:5],
            "session_id": self.session_id,
            "correlation_id": self.correlation_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SecurityContext:
        """Deserialize a ``SecurityContext`` from a dictionary.

        Args:
            data: Dictionary as produced by :meth:`to_dict`.

        Returns:
            A reconstructed :class:`SecurityContext`.
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
    """Create a new security context for an authenticated user.

    Args:
        user_id: Unique user identifier.
        tenant_id: Azure AD tenant ID for multi-tenancy.
        permissions: List of permission strings to grant.
        roles: List of role names to assign.
        session_id: Session identifier (auto-generated UUID if omitted).
        correlation_id: Request correlation ID for tracing.
        metadata: Arbitrary metadata to attach.
        expires_in_seconds: Context TTL; ``None`` means no expiry.

    Returns:
        A fully initialized :class:`SecurityContext`.
    """
    from datetime import timedelta

    permission_set = frozenset(Permission.from_string(p) for p in (permissions or []))
    role_set = frozenset(roles or [])

    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=expires_in_seconds) if expires_in_seconds else None

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
    """Create a system context with wildcard (all) permissions.

    Args:
        service_name: Name of the background service or task.
        correlation_id: Optional correlation ID for tracing.

    Returns:
        A :class:`SecurityContext` with ``ContextType.SYSTEM`` and ``*.*`` permissions.
    """
    return SecurityContext(
        user_id=f"system:{service_name}",
        context_type=ContextType.SYSTEM,
        permissions=frozenset([Permission("*", "*")]),
        roles=frozenset(["system"]),
        correlation_id=correlation_id,
        metadata={"service_name": service_name},
    )


def create_anonymous_context(correlation_id: str | None = None) -> SecurityContext:
    """Create an anonymous context with no permissions.

    Args:
        correlation_id: Optional correlation ID for tracing.

    Returns:
        A :class:`SecurityContext` with ``ContextType.ANONYMOUS`` and empty permissions.
    """
    return SecurityContext(
        user_id="anonymous",
        context_type=ContextType.ANONYMOUS,
        permissions=frozenset(),
        roles=frozenset(),
        correlation_id=correlation_id,
    )
