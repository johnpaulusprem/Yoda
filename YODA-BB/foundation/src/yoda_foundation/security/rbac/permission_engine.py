"""
Permission engine for evaluating RBAC permissions.

This module provides the core permission evaluation logic including
caching, batch checks, and audit logging.

Example:
    ```python
    from yoda_foundation.security.rbac import (
        PermissionEngine,
        RoleStore,
    )

    # Initialize engine
    engine = PermissionEngine(
        role_store=role_store,
        cache_ttl_seconds=300,
    )

    # Check permission
    can_write = await engine.has_permission(
        user_id="user_123",
        permission="document.write",
        security_context=ctx,
    )

    # Batch check
    permissions = await engine.check_permissions(
        user_id="user_123",
        permissions=["doc.read", "doc.write", "doc.delete"],
        security_context=ctx,
    )
    ```
"""

from __future__ import annotations

import asyncio
import builtins
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from yoda_foundation.exceptions import (
    AuthorizationError,
)
from yoda_foundation.security.context import Permission, SecurityContext
from yoda_foundation.security.data_governance.audit_logger import (
    AuditAction,
    AuditLogger,
    AuditStatus,
)
from yoda_foundation.security.rbac.role_definitions import (
    PermissionSet,
    Role,
    RoleHierarchy,
)
from yoda_foundation.observability.logging import get_logger


logger = get_logger(__name__)


class RoleStore(Protocol):
    """
    Protocol for role storage backends.

    Implementations should handle persistence of roles and user-role mappings.

    Example:
        ```python
        class RedisRoleStore:
            async def get_user_roles(self, user_id: str) -> List[str]:
                return await self.redis.smembers(f"user:{user_id}:roles")

            async def get_role(self, role_id: str) -> Optional[Role]:
                data = await self.redis.get(f"role:{role_id}")
                return Role.from_dict(data) if data else None
        ```
    """

    async def get_user_roles(
        self,
        user_id: str,
        tenant_id: str | None = None,
    ) -> list[str]:
        """
        Get role IDs assigned to a user.

        Args:
            user_id: User identifier
            tenant_id: Optional tenant scope

        Returns:
            List of role IDs
        """
        ...

    async def get_role(self, role_id: str) -> Role | None:
        """
        Get role definition by ID.

        Args:
            role_id: Role identifier

        Returns:
            Role object or None
        """
        ...

    async def assign_role(
        self,
        user_id: str,
        role_id: str,
        tenant_id: str | None = None,
    ) -> None:
        """
        Assign a role to a user.

        Args:
            user_id: User identifier
            role_id: Role identifier
            tenant_id: Optional tenant scope
        """
        ...

    async def revoke_role(
        self,
        user_id: str,
        role_id: str,
        tenant_id: str | None = None,
    ) -> None:
        """
        Revoke a role from a user.

        Args:
            user_id: User identifier
            role_id: Role identifier
            tenant_id: Optional tenant scope
        """
        ...


@dataclass
class CachedPermissions:
    """
    Cached permission set with expiry.

    Attributes:
        permissions: Set of permission strings
        cached_at: When the permissions were cached
        expires_at: When the cache entry expires
    """

    permissions: set[str]
    cached_at: datetime
    expires_at: datetime

    def is_expired(self) -> bool:
        """Check if cache entry has expired."""
        return datetime.now(UTC) >= self.expires_at


class PermissionCache:
    """
    TTL-based cache for permission evaluations.

    Caches user permissions to reduce database lookups and
    improve performance for frequent permission checks.

    Example:
        ```python
        cache = PermissionCache(ttl_seconds=300)

        # Cache permissions
        await cache.set(
            "user_123",
            {"doc.read", "doc.write"},
        )

        # Get cached permissions
        perms = await cache.get("user_123")
        if perms:
            print(f"Cache hit: {perms}")
        ```
    """

    def __init__(self, ttl_seconds: int = 300) -> None:
        """
        Initialize permission cache.

        Args:
            ttl_seconds: Time-to-live for cache entries in seconds
        """
        self._cache: dict[str, CachedPermissions] = {}
        self._ttl_seconds = ttl_seconds
        self._lock = asyncio.Lock()

    async def get(self, cache_key: str) -> builtins.set[str] | None:
        """
        Get cached permissions.

        Args:
            cache_key: Cache key (typically user_id or user_id:tenant_id)

        Returns:
            Set of permission strings or None if not cached/expired

        Example:
            ```python
            perms = await cache.get("user_123")
            ```
        """
        async with self._lock:
            entry = self._cache.get(cache_key)
            if entry and not entry.is_expired():
                return entry.permissions

            # Remove expired entry
            if entry:
                del self._cache[cache_key]

            return None

    async def set(
        self,
        cache_key: str,
        permissions: builtins.set[str],
    ) -> None:
        """
        Cache permissions for a user.

        Args:
            cache_key: Cache key
            permissions: Set of permission strings to cache

        Example:
            ```python
            await cache.set(
                "user_123",
                {"doc.read", "doc.write"},
            )
            ```
        """
        async with self._lock:
            now = datetime.now(UTC)
            expires_at = now + timedelta(seconds=self._ttl_seconds)

            self._cache[cache_key] = CachedPermissions(
                permissions=permissions,
                cached_at=now,
                expires_at=expires_at,
            )

    async def invalidate(self, cache_key: str) -> None:
        """
        Invalidate cached permissions.

        Args:
            cache_key: Cache key to invalidate

        Example:
            ```python
            # After role change
            await cache.invalidate("user_123")
            ```
        """
        async with self._lock:
            self._cache.pop(cache_key, None)

    async def clear(self) -> None:
        """
        Clear all cached permissions.

        Example:
            ```python
            # After role definition changes
            await cache.clear()
            ```
        """
        async with self._lock:
            self._cache.clear()

    async def cleanup_expired(self) -> int:
        """
        Remove expired cache entries.

        Returns:
            Number of entries removed

        Example:
            ```python
            # Run periodically
            removed = await cache.cleanup_expired()
            logger.info(f"Removed {removed} expired cache entries")
            ```
        """
        async with self._lock:
            expired_keys = [key for key, entry in self._cache.items() if entry.is_expired()]

            for key in expired_keys:
                del self._cache[key]

            return len(expired_keys)


@dataclass
class PermissionEvaluationResult:
    """
    Result of a permission evaluation.

    Attributes:
        granted: Whether the permission was granted
        permission: The permission that was checked
        user_id: User who requested the permission
        roles: Roles that contributed to the decision
        source: How the permission was granted (direct, inherited, wildcard)
        evaluated_at: When the evaluation occurred
        cached: Whether the result came from cache
    """

    granted: bool
    permission: str
    user_id: str
    roles: list[str] = field(default_factory=list)
    source: str = "direct"
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    cached: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            "granted": self.granted,
            "permission": self.permission,
            "user_id": self.user_id,
            "roles": self.roles,
            "source": self.source,
            "evaluated_at": self.evaluated_at.isoformat(),
            "cached": self.cached,
        }


class PermissionEvaluator:
    """
    Evaluates permissions based on roles and hierarchy.

    Example:
        ```python
        evaluator = PermissionEvaluator(role_hierarchy)

        result = await evaluator.evaluate(
            user_roles=["editor", "viewer"],
            required_permission="document.write",
        )

        if result.granted:
            print(f"Permission granted via {result.source}")
        ```
    """

    def __init__(self, role_hierarchy: RoleHierarchy) -> None:
        """
        Initialize permission evaluator.

        Args:
            role_hierarchy: Role hierarchy for inheritance
        """
        self._hierarchy = role_hierarchy

    async def evaluate(
        self,
        user_roles: list[str],
        required_permission: str | Permission,
        user_id: str | None = None,
    ) -> PermissionEvaluationResult:
        """
        Evaluate if user roles grant the required permission.

        Args:
            user_roles: List of role IDs assigned to the user
            required_permission: Permission to check
            user_id: Optional user ID for logging

        Returns:
            PermissionEvaluationResult with decision details

        Example:
            ```python
            result = await evaluator.evaluate(
                user_roles=["editor"],
                required_permission="document.write",
                user_id="user_123",
            )
            ```
        """
        if isinstance(required_permission, str):
            required_perm = Permission.from_string(required_permission)
        else:
            required_perm = required_permission

        # Collect effective permissions from all roles
        effective_perms = PermissionSet.empty()
        contributing_roles = []

        for role_id in user_roles:
            role_perms = await self._hierarchy.get_effective_permissions(role_id)
            if role_perms.includes(required_perm):
                contributing_roles.append(role_id)
                effective_perms = effective_perms.merge(role_perms)

        granted = effective_perms.includes(required_perm)

        # Determine source
        source = "none"
        if granted:
            # Check if it's a wildcard match
            has_wildcard = any(
                p.resource == "*" or p.action == "*" for p in effective_perms.permissions
            )
            if has_wildcard:
                source = "wildcard"
            elif len(contributing_roles) > 1:
                source = "inherited"
            else:
                source = "direct"

        return PermissionEvaluationResult(
            granted=granted,
            permission=str(required_perm),
            user_id=user_id or "unknown",
            roles=contributing_roles,
            source=source,
        )

    async def batch_evaluate(
        self,
        user_roles: list[str],
        required_permissions: list[str],
        user_id: str | None = None,
    ) -> dict[str, PermissionEvaluationResult]:
        """
        Evaluate multiple permissions at once.

        Args:
            user_roles: List of role IDs
            required_permissions: List of permissions to check
            user_id: Optional user ID for logging

        Returns:
            Dictionary mapping permission to evaluation result

        Example:
            ```python
            results = await evaluator.batch_evaluate(
                user_roles=["editor"],
                required_permissions=["doc.read", "doc.write", "doc.delete"],
            )

            for perm, result in results.items():
                print(f"{perm}: {result.granted}")
            ```
        """
        results = {}

        for permission in required_permissions:
            result = await self.evaluate(
                user_roles=user_roles,
                required_permission=permission,
                user_id=user_id,
            )
            results[permission] = result

        return results


class PermissionEngine:
    """
    Main permission engine for RBAC evaluation.

    Coordinates role storage, hierarchy, caching, and auditing
    for complete permission evaluation.

    Example:
        ```python
        engine = PermissionEngine(
            role_store=role_store,
            role_hierarchy=hierarchy,
            cache_ttl_seconds=300,
            enable_audit=True,
        )

        # Single permission check
        has_perm = await engine.has_permission(
            user_id="user_123",
            permission="document.write",
            security_context=ctx,
        )

        # Batch check
        results = await engine.check_permissions(
            user_id="user_123",
            permissions=["doc.read", "doc.write"],
            security_context=ctx,
        )

        # Enforce permission (raises if denied)
        await engine.require_permission(
            user_id="user_123",
            permission="admin.settings",
            security_context=ctx,
        )
        ```
    """

    def __init__(
        self,
        role_store: RoleStore,
        role_hierarchy: RoleHierarchy | None = None,
        cache_ttl_seconds: int = 300,
        enable_audit: bool = True,
        audit_logger: AuditLogger | None = None,
    ) -> None:
        """
        Initialize permission engine.

        Args:
            role_store: Storage backend for roles
            role_hierarchy: Optional pre-configured role hierarchy
            cache_ttl_seconds: Cache TTL in seconds
            enable_audit: Whether to log permission evaluations
            audit_logger: Optional audit logger for security audit trail
        """
        self._role_store = role_store
        self._hierarchy = role_hierarchy or RoleHierarchy()
        self._cache = PermissionCache(ttl_seconds=cache_ttl_seconds)
        self._evaluator = PermissionEvaluator(self._hierarchy)
        self._enable_audit = enable_audit
        self._audit_logger = audit_logger

    async def has_permission(
        self,
        user_id: str,
        permission: str,
        security_context: SecurityContext,
    ) -> bool:
        """
        Check if a user has a specific permission.

        Args:
            user_id: User identifier
            permission: Permission to check
            security_context: Security context for tenant scope and audit

        Returns:
            True if permission is granted

        Example:
            ```python
            if await engine.has_permission(
                user_id="user_123",
                permission="document.write",
                security_context=ctx,
            ):
                await write_document(doc)
            ```
        """
        result = await self._evaluate_permission(
            user_id=user_id,
            permission=permission,
            tenant_id=security_context.tenant_id,
        )

        if self._enable_audit:
            await self._audit_permission_check(result, security_context)

        return result.granted

    async def check_permissions(
        self,
        user_id: str,
        permissions: list[str],
        security_context: SecurityContext,
    ) -> dict[str, bool]:
        """
        Check multiple permissions at once.

        Args:
            user_id: User identifier
            permissions: List of permissions to check
            security_context: Security context

        Returns:
            Dictionary mapping permission to granted status

        Example:
            ```python
            perms = await engine.check_permissions(
                user_id="user_123",
                permissions=["doc.read", "doc.write", "doc.delete"],
                security_context=ctx,
            )

            if all(perms.values()):
                print("User has all permissions")
            ```
        """
        user_roles = await self._get_user_roles(
            user_id,
            security_context.tenant_id,
        )

        results = await self._evaluator.batch_evaluate(
            user_roles=user_roles,
            required_permissions=permissions,
            user_id=user_id,
        )

        if self._enable_audit:
            for result in results.values():
                await self._audit_permission_check(result, security_context)

        return {perm: result.granted for perm, result in results.items()}

    async def require_permission(
        self,
        user_id: str,
        permission: str,
        security_context: SecurityContext,
        resource: str | None = None,
    ) -> None:
        """
        Require a permission, raising an error if not granted.

        Args:
            user_id: User identifier
            permission: Required permission
            security_context: Security context
            resource: Optional resource being accessed

        Raises:
            AuthorizationError: If permission is not granted

        Example:
            ```python
            await engine.require_permission(
                user_id="user_123",
                permission="admin.settings",
                security_context=ctx,
                resource="system_settings",
            )
            # Only reached if permission granted
            ```
        """
        has_perm = await self.has_permission(
            user_id=user_id,
            permission=permission,
            security_context=security_context,
        )

        if not has_perm:
            raise AuthorizationError(
                message=f"Permission denied: {permission}",
                required_permission=permission,
                resource=resource,
                user_id=user_id,
            )

    async def get_user_permissions(
        self,
        user_id: str,
        security_context: SecurityContext,
    ) -> PermissionSet:
        """
        Get all effective permissions for a user.

        Args:
            user_id: User identifier
            security_context: Security context

        Returns:
            PermissionSet with all effective permissions

        Example:
            ```python
            perms = await engine.get_user_permissions(
                user_id="user_123",
                security_context=ctx,
            )

            print(f"User has {len(perms)} permissions")
            for perm in perms.to_strings():
                print(f"  - {perm}")
            ```
        """
        user_roles = await self._get_user_roles(
            user_id,
            security_context.tenant_id,
        )

        effective = PermissionSet.empty()
        for role_id in user_roles:
            role_perms = await self._hierarchy.get_effective_permissions(role_id)
            effective = effective.merge(role_perms)

        return effective

    async def invalidate_user_cache(
        self,
        user_id: str,
        tenant_id: str | None = None,
    ) -> None:
        """
        Invalidate cached permissions for a user.

        Call this after role assignments change.

        Args:
            user_id: User identifier
            tenant_id: Optional tenant scope

        Example:
            ```python
            await engine.invalidate_user_cache("user_123")
            ```
        """
        cache_key = self._make_cache_key(user_id, tenant_id)
        await self._cache.invalidate(cache_key)

    async def _evaluate_permission(
        self,
        user_id: str,
        permission: str,
        tenant_id: str | None = None,
    ) -> PermissionEvaluationResult:
        """
        Internal permission evaluation with caching.

        Args:
            user_id: User identifier
            permission: Permission to check
            tenant_id: Optional tenant scope

        Returns:
            PermissionEvaluationResult
        """
        user_roles = await self._get_user_roles(user_id, tenant_id)

        result = await self._evaluator.evaluate(
            user_roles=user_roles,
            required_permission=permission,
            user_id=user_id,
        )

        return result

    async def _get_user_roles(
        self,
        user_id: str,
        tenant_id: str | None = None,
    ) -> list[str]:
        """
        Get user roles from store.

        Args:
            user_id: User identifier
            tenant_id: Optional tenant scope

        Returns:
            List of role IDs
        """
        return await self._role_store.get_user_roles(user_id, tenant_id)

    def _make_cache_key(
        self,
        user_id: str,
        tenant_id: str | None = None,
    ) -> str:
        """
        Create cache key for user permissions.

        Args:
            user_id: User identifier
            tenant_id: Optional tenant scope

        Returns:
            Cache key string
        """
        if tenant_id:
            return f"{user_id}:{tenant_id}"
        return user_id

    async def _audit_permission_check(
        self,
        result: PermissionEvaluationResult,
        security_context: SecurityContext,
    ) -> None:
        """
        Audit a permission evaluation.

        Logs permission check results to the audit logger for security
        compliance and forensic analysis.

        Args:
            result: Evaluation result
            security_context: Security context

        Example:
            ```python
            # Internal method called automatically when enable_audit=True
            await engine._audit_permission_check(result, security_context)
            ```

        Note:
            If no audit_logger is configured, falls back to structured logging.
        """
        # Determine audit status based on evaluation result
        if result.granted:
            audit_status = AuditStatus.SUCCESS
        else:
            audit_status = AuditStatus.DENIED

        # Build metadata for the audit entry
        metadata = {
            "source": result.source,
            "roles": result.roles,
            "cached": result.cached,
            "evaluated_at": result.evaluated_at.isoformat(),
        }

        # If audit logger is configured, use it for full audit trail
        if self._audit_logger:
            try:
                await self._audit_logger.log(
                    action=AuditAction.EXECUTE,
                    resource_type="permission",
                    resource_id=result.permission,
                    status=audit_status,
                    security_context=security_context,
                    metadata=metadata,
                )
            except (AuthorizationError, ValueError) as e:
                # Log error but don't fail the permission check
                logger.warning(
                    "Failed to write permission audit entry",
                    extra={
                        "error": str(e),
                        "permission": result.permission,
                        "user_id": result.user_id,
                    },
                )
        else:
            # Fallback to structured logging when no audit logger configured
            logger.debug(
                "Permission check evaluated",
                extra={
                    "granted": result.granted,
                    "permission": result.permission,
                    "user_id": result.user_id,
                    "roles": result.roles,
                    "source": result.source,
                },
            )
