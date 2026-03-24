"""
RBAC (Role-Based Access Control) module for the Agentic AI Component Library.

Provides comprehensive RBAC with:
- Role definitions and hierarchies
- Permission engine with caching
- Policy enforcement point
- Context-aware dynamic permissions (ABAC)

Example:
    ```python
    from yoda_foundation.security.rbac import (
        Role,
        RoleHierarchy,
        PermissionSet,
        StandardRoles,
        PermissionEngine,
        PolicyEnforcementPoint,
        PolicyContext,
        ContextAwareRBAC,
        DynamicPermission,
        TimeRule,
        LocationRule,
        AttributeRule,
    )

    # Setup role hierarchy
    hierarchy = RoleHierarchy()
    await hierarchy.add_role(StandardRoles.ADMIN)
    await hierarchy.add_role(StandardRoles.USER)

    # Create permission engine
    engine = PermissionEngine(
        role_store=role_store,
        role_hierarchy=hierarchy,
    )

    # Enforce policy
    pep = PolicyEnforcementPoint(permission_engine=engine)
    decision = await pep.enforce(
        context=PolicyContext(
            user_id="user_123",
            resource="document",
            action="write",
        ),
        security_context=sec_ctx,
    )

    # Use context-aware RBAC
    rbac = ContextAwareRBAC(permission_engine=engine)
    rbac.add_dynamic_permission(
        DynamicPermission(
            permission="sensitive_data.read",
            rules=[TimeRule(start_hour=9, end_hour=17)],
        )
    )
    ```
"""

from yoda_foundation.security.rbac.context_aware_rbac import (
    AttributeRule,
    ContextAwareRBAC,
    ContextRule,
    DataOwnershipRule,
    DynamicPermission,
    LocationRule,
    RuleContext,
    RuleEvaluationResult,
    TimeRule,
)
from yoda_foundation.security.rbac.permission_engine import (
    CachedPermissions,
    PermissionCache,
    PermissionEngine,
    PermissionEvaluationResult,
    PermissionEvaluator,
    RoleStore,
)
from yoda_foundation.security.rbac.policy_enforcement import (
    PolicyContext,
    PolicyDecision,
    PolicyDecisionType,
    PolicyEnforcementPoint,
    PolicyHook,
)
from yoda_foundation.security.rbac.role_definitions import (
    PermissionSet,
    Role,
    RoleHierarchy,
    StandardRoles,
)


__all__ = [
    # Role Definitions
    "Role",
    "RoleHierarchy",
    "PermissionSet",
    "StandardRoles",
    # Permission Engine
    "PermissionEngine",
    "PermissionEvaluator",
    "PermissionCache",
    "PermissionEvaluationResult",
    "RoleStore",
    "CachedPermissions",
    # Policy Enforcement
    "PolicyEnforcementPoint",
    "PolicyContext",
    "PolicyDecision",
    "PolicyDecisionType",
    "PolicyHook",
    # Context-Aware RBAC
    "ContextAwareRBAC",
    "DynamicPermission",
    "ContextRule",
    "TimeRule",
    "LocationRule",
    "AttributeRule",
    "DataOwnershipRule",
    "RuleContext",
    "RuleEvaluationResult",
]
