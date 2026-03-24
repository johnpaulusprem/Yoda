"""
Policy enforcement point for centralized access control.

This module provides the Policy Enforcement Point (PEP) pattern for
making authorization decisions with rich context and audit logging.

Example:
    ```python
    from yoda_foundation.security.rbac import (
        PolicyEnforcementPoint,
        PolicyContext,
        PolicyDecision,
    )

    pep = PolicyEnforcementPoint(permission_engine=engine)

    # Create policy context
    context = PolicyContext(
        user_id="user_123",
        resource="document",
        resource_id="doc_456",
        action="write",
        environment={"ip_address": "192.168.1.1"},
    )

    # Enforce policy
    decision = await pep.enforce(
        context=context,
        security_context=sec_ctx,
    )

    if decision.allow:
        await perform_action()
    else:
        raise decision.to_exception()
    ```
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from yoda_foundation.exceptions import (
    AuthorizationError,
    ValidationError,
)
from yoda_foundation.security.context import SecurityContext
from yoda_foundation.security.data_governance.audit_logger import (
    AuditAction,
    AuditLogger,
    AuditStatus,
)
from yoda_foundation.security.rbac.permission_engine import PermissionEngine
from yoda_foundation.observability.logging import get_logger


logger = get_logger(__name__)


class PolicyDecisionType(Enum):
    """Type of policy decision."""

    ALLOW = "allow"
    DENY = "deny"
    NOT_APPLICABLE = "not_applicable"


@dataclass
class PolicyContext:
    """
    Rich context for policy evaluation.

    Contains all information needed to make an authorization decision
    including user, resource, action, and environmental factors.

    Attributes:
        user_id: User requesting access
        resource: Type of resource being accessed
        resource_id: Specific resource identifier
        action: Action being performed
        environment: Environmental context (IP, time, location, etc.)
        attributes: Additional attributes for ABAC
        metadata: Extra metadata for logging

    Example:
        ```python
        context = PolicyContext(
            user_id="user_123",
            resource="patient_record",
            resource_id="patient_456",
            action="read",
            environment={
                "ip_address": "10.0.0.1",
                "timestamp": datetime.now(),
                "location": "office",
            },
            attributes={
                "department": "cardiology",
                "role": "doctor",
            },
        )
        ```
    """

    user_id: str
    resource: str
    action: str
    resource_id: str | None = None
    environment: dict[str, Any] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """
        Convert to dictionary for logging.

        Returns:
            Dictionary representation
        """
        return {
            "user_id": self.user_id,
            "resource": self.resource,
            "resource_id": self.resource_id,
            "action": self.action,
            "environment": self.environment,
            "attributes": self.attributes,
            "metadata": self.metadata,
        }

    def get_permission_string(self) -> str:
        """
        Get RBAC permission string from context.

        Returns:
            Permission string in format "resource.action"

        Example:
            ```python
            context = PolicyContext(
                user_id="user_123",
                resource="document",
                action="write",
            )
            perm = context.get_permission_string()
            # Returns: "document.write"
            ```
        """
        return f"{self.resource}.{self.action}"


@dataclass
class PolicyDecision:
    """
    Result of a policy evaluation.

    Attributes:
        decision: The decision type (allow/deny/not_applicable)
        reason: Human-readable reason for the decision
        context: The policy context that was evaluated
        evaluated_at: When the decision was made
        details: Additional decision details
        suggestions: Suggestions if denied

    Example:
        ```python
        decision = PolicyDecision(
            decision=PolicyDecisionType.DENY,
            reason="User lacks 'admin.delete' permission",
            context=policy_context,
            suggestions=["Request admin access from your manager"],
        )

        if decision.deny:
            raise decision.to_exception()
        ```
    """

    decision: PolicyDecisionType
    reason: str
    context: PolicyContext
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    details: dict[str, Any] = field(default_factory=dict)
    suggestions: list[str] = field(default_factory=list)

    @property
    def allow(self) -> bool:
        """Check if decision is ALLOW."""
        return self.decision == PolicyDecisionType.ALLOW

    @property
    def deny(self) -> bool:
        """Check if decision is DENY."""
        return self.decision == PolicyDecisionType.DENY

    @property
    def not_applicable(self) -> bool:
        """Check if decision is NOT_APPLICABLE."""
        return self.decision == PolicyDecisionType.NOT_APPLICABLE

    def to_dict(self) -> dict[str, Any]:
        """
        Convert to dictionary for logging.

        Returns:
            Dictionary representation
        """
        return {
            "decision": self.decision.value,
            "reason": self.reason,
            "context": self.context.to_dict(),
            "evaluated_at": self.evaluated_at.isoformat(),
            "details": self.details,
            "suggestions": self.suggestions,
        }

    def to_exception(self) -> AuthorizationError:
        """
        Convert deny decision to AuthorizationError.

        Returns:
            AuthorizationError with decision details

        Example:
            ```python
            if decision.deny:
                raise decision.to_exception()
            ```
        """
        return AuthorizationError(
            message=self.reason,
            required_permission=self.context.get_permission_string(),
            resource=self.context.resource_id or self.context.resource,
            action=self.context.action,
            user_id=self.context.user_id,
            suggestions=self.suggestions,
            details=self.details,
        )


# Type alias for policy hooks
PolicyHook = Callable[[PolicyContext, PolicyDecision], Awaitable[None]]


class PolicyEnforcementPoint:
    """
    Central policy enforcement point for access control.

    Coordinates permission evaluation, contextual rules,
    and pre/post enforcement hooks for comprehensive
    authorization decisions.

    Example:
        ```python
        pep = PolicyEnforcementPoint(
            permission_engine=engine,
            enable_audit=True,
        )

        # Register hooks
        async def log_denial(ctx: PolicyContext, decision: PolicyDecision):
            if decision.deny:
                logger.warning(f"Access denied: {ctx.user_id} -> {ctx.resource}")

        pep.add_post_enforcement_hook(log_denial)

        # Enforce policy
        decision = await pep.enforce(
            context=PolicyContext(
                user_id="user_123",
                resource="admin_panel",
                action="access",
            ),
            security_context=sec_ctx,
        )
        ```
    """

    def __init__(
        self,
        permission_engine: PermissionEngine,
        enable_audit: bool = True,
        audit_logger: AuditLogger | None = None,
    ) -> None:
        """
        Initialize policy enforcement point.

        Args:
            permission_engine: Permission engine for RBAC evaluation
            enable_audit: Whether to log policy decisions
            audit_logger: Optional audit logger for security audit trail
        """
        self._permission_engine = permission_engine
        self._enable_audit = enable_audit
        self._audit_logger = audit_logger
        self._pre_enforcement_hooks: list[PolicyHook] = []
        self._post_enforcement_hooks: list[PolicyHook] = []

    def add_pre_enforcement_hook(self, hook: PolicyHook) -> None:
        """
        Add a hook to run before policy enforcement.

        Pre-enforcement hooks can be used for logging, rate limiting,
        or custom validation before the authorization decision.

        Args:
            hook: Async function taking PolicyContext and PolicyDecision

        Example:
            ```python
            async def rate_limit_check(ctx: PolicyContext, _):
                if await is_rate_limited(ctx.user_id):
                    raise RateLimitError("Too many requests")

            pep.add_pre_enforcement_hook(rate_limit_check)
            ```
        """
        self._pre_enforcement_hooks.append(hook)

    def add_post_enforcement_hook(self, hook: PolicyHook) -> None:
        """
        Add a hook to run after policy enforcement.

        Post-enforcement hooks can be used for audit logging,
        metrics collection, or notifications.

        Args:
            hook: Async function taking PolicyContext and PolicyDecision

        Example:
            ```python
            async def audit_decision(ctx: PolicyContext, decision: PolicyDecision):
                await audit_log.record({
                    "user": ctx.user_id,
                    "resource": ctx.resource,
                    "decision": decision.decision.value,
                })

            pep.add_post_enforcement_hook(audit_decision)
            ```
        """
        self._post_enforcement_hooks.append(hook)

    async def enforce(
        self,
        context: PolicyContext,
        security_context: SecurityContext,
        require_allow: bool = False,
    ) -> PolicyDecision:
        """
        Evaluate and enforce policy for the given context.

        Args:
            context: Policy context with request details
            security_context: Security context for tenant scope
            require_allow: If True, raise exception on deny

        Returns:
            PolicyDecision with the authorization decision

        Raises:
            AuthorizationError: If require_allow=True and decision is DENY

        Example:
            ```python
            decision = await pep.enforce(
                context=PolicyContext(
                    user_id="user_123",
                    resource="document",
                    resource_id="doc_456",
                    action="delete",
                ),
                security_context=sec_ctx,
                require_allow=True,  # Raise if denied
            )
            ```
        """
        # Validate context
        await self._validate_context(context)

        # Initial decision (will be updated)
        decision = PolicyDecision(
            decision=PolicyDecisionType.NOT_APPLICABLE,
            reason="Policy evaluation not started",
            context=context,
        )

        # Run pre-enforcement hooks
        await self._run_hooks(self._pre_enforcement_hooks, context, decision)

        # Evaluate RBAC permission
        decision = await self._evaluate_rbac(context, security_context)

        # Run post-enforcement hooks
        await self._run_hooks(self._post_enforcement_hooks, context, decision)

        # Audit decision if enabled
        if self._enable_audit:
            await self._audit_decision(decision, security_context)

        # Raise exception if required and denied
        if require_allow and decision.deny:
            raise decision.to_exception()

        return decision

    async def check_access(
        self,
        context: PolicyContext,
        security_context: SecurityContext,
    ) -> bool:
        """
        Simple access check returning boolean.

        Args:
            context: Policy context
            security_context: Security context

        Returns:
            True if access is allowed

        Example:
            ```python
            allowed = await pep.check_access(
                context=PolicyContext(
                    user_id="user_123",
                    resource="report",
                    action="read",
                ),
                security_context=sec_ctx,
            )

            if allowed:
                return await get_report()
            ```
        """
        decision = await self.enforce(
            context=context,
            security_context=security_context,
            require_allow=False,
        )

        return decision.allow

    async def require_access(
        self,
        context: PolicyContext,
        security_context: SecurityContext,
    ) -> None:
        """
        Require access, raising exception if denied.

        Args:
            context: Policy context
            security_context: Security context

        Raises:
            AuthorizationError: If access is denied

        Example:
            ```python
            await pep.require_access(
                context=PolicyContext(
                    user_id="user_123",
                    resource="admin_panel",
                    action="access",
                ),
                security_context=sec_ctx,
            )
            # Only reached if access granted
            ```
        """
        await self.enforce(
            context=context,
            security_context=security_context,
            require_allow=True,
        )

    async def batch_check(
        self,
        contexts: list[PolicyContext],
        security_context: SecurityContext,
    ) -> dict[str, PolicyDecision]:
        """
        Check multiple policy contexts at once.

        Args:
            contexts: List of policy contexts to evaluate
            security_context: Security context

        Returns:
            Dictionary mapping context identifier to decision

        Example:
            ```python
            contexts = [
                PolicyContext(user_id="user_123", resource="doc", action="read"),
                PolicyContext(user_id="user_123", resource="doc", action="write"),
                PolicyContext(user_id="user_123", resource="doc", action="delete"),
            ]

            decisions = await pep.batch_check(contexts, sec_ctx)
            for key, decision in decisions.items():
                print(f"{key}: {decision.decision.value}")
            ```
        """
        decisions = {}

        for context in contexts:
            key = f"{context.resource}.{context.action}"
            if context.resource_id:
                key = f"{key}:{context.resource_id}"

            decision = await self.enforce(
                context=context,
                security_context=security_context,
                require_allow=False,
            )

            decisions[key] = decision

        return decisions

    async def _validate_context(self, context: PolicyContext) -> None:
        """
        Validate policy context.

        Args:
            context: Policy context to validate

        Raises:
            ValidationError: If context is invalid
        """
        if not context.user_id:
            raise ValidationError(
                message="Policy context must have user_id",
                field_name="user_id",
            )

        if not context.resource:
            raise ValidationError(
                message="Policy context must have resource",
                field_name="resource",
            )

        if not context.action:
            raise ValidationError(
                message="Policy context must have action",
                field_name="action",
            )

    async def _evaluate_rbac(
        self,
        context: PolicyContext,
        security_context: SecurityContext,
    ) -> PolicyDecision:
        """
        Evaluate RBAC permissions.

        Args:
            context: Policy context
            security_context: Security context

        Returns:
            PolicyDecision based on RBAC evaluation
        """
        permission = context.get_permission_string()

        has_permission = await self._permission_engine.has_permission(
            user_id=context.user_id,
            permission=permission,
            security_context=security_context,
        )

        if has_permission:
            return PolicyDecision(
                decision=PolicyDecisionType.ALLOW,
                reason=f"User has required permission: {permission}",
                context=context,
                details={"permission": permission},
            )
        else:
            return PolicyDecision(
                decision=PolicyDecisionType.DENY,
                reason=f"User lacks required permission: {permission}",
                context=context,
                details={"required_permission": permission},
                suggestions=[
                    f"Request the '{permission}' permission from your administrator",
                    "Verify you're using the correct account",
                ],
            )

    async def _run_hooks(
        self,
        hooks: list[PolicyHook],
        context: PolicyContext,
        decision: PolicyDecision,
    ) -> None:
        """
        Run enforcement hooks.

        Args:
            hooks: List of hooks to run
            context: Policy context
            decision: Current decision
        """
        for hook in hooks:
            try:
                await hook(context, decision)
            except (AuthorizationError, ValueError) as e:
                # Log hook error but don't fail enforcement
                logger.warning(
                    "Policy enforcement hook failed",
                    extra={
                        "hook": hook.__name__ if hasattr(hook, "__name__") else str(hook),
                        "error": str(e),
                        "user_id": context.user_id,
                        "resource": context.resource,
                        "action": context.action,
                    },
                )

    async def _audit_decision(
        self,
        decision: PolicyDecision,
        security_context: SecurityContext,
    ) -> None:
        """
        Audit a policy decision.

        Logs policy enforcement decisions to the audit logger for
        security compliance and forensic analysis.

        Args:
            decision: Policy decision to audit
            security_context: Security context

        Example:
            ```python
            # Internal method called automatically when enable_audit=True
            await pep._audit_decision(decision, security_context)
            ```

        Note:
            If no audit_logger is configured, falls back to structured logging.
        """
        context = decision.context

        # Map decision type to audit status
        if decision.allow:
            audit_status = AuditStatus.SUCCESS
        elif decision.deny:
            audit_status = AuditStatus.DENIED
        else:
            audit_status = AuditStatus.PARTIAL

        # Build metadata for audit entry
        metadata = {
            "decision_type": decision.decision.value,
            "reason": decision.reason,
            "details": decision.details,
            "suggestions": decision.suggestions,
            "environment": context.environment,
            "attributes": context.attributes,
            "evaluated_at": decision.evaluated_at.isoformat(),
        }

        # If audit logger is configured, use it for full audit trail
        if self._audit_logger:
            try:
                await self._audit_logger.log(
                    action=AuditAction.EXECUTE,
                    resource_type=context.resource,
                    resource_id=context.resource_id or context.get_permission_string(),
                    status=audit_status,
                    security_context=security_context,
                    metadata=metadata,
                )
            except (AuthorizationError, ValueError) as e:
                # Log error but don't fail the policy enforcement
                logger.warning(
                    "Failed to write policy audit entry",
                    extra={
                        "error": str(e),
                        "resource": context.resource,
                        "action": context.action,
                        "user_id": context.user_id,
                    },
                )
        else:
            # Fallback to structured logging when no audit logger configured
            logger.debug(
                "Policy decision",
                extra={
                    "decision": decision.decision.value,
                    "resource": context.resource,
                    "resource_id": context.resource_id,
                    "action": context.action,
                    "user_id": context.user_id,
                    "reason": decision.reason,
                },
            )
