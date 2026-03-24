"""
Example usage of the RBAC components.

This file demonstrates how to use the RBAC system for comprehensive
access control in agentic AI applications.

Example:
    ```bash
    # Run the example
    python -m yoda_foundation.security.rbac.examples
    ```
"""

import asyncio
from datetime import datetime

from yoda_foundation.security.context import (
    create_security_context,
)
from yoda_foundation.security.rbac import (
    AttributeRule,
    # Context-Aware RBAC
    ContextAwareRBAC,
    DynamicPermission,
    LocationRule,
    # Permission Engine
    PermissionEngine,
    PermissionSet,
    PolicyContext,
    # Policy Enforcement
    PolicyEnforcementPoint,
    # Role Definitions
    Role,
    RoleHierarchy,
    StandardRoles,
    TimeRule,
)


# Example RoleStore implementation (in-memory)
class InMemoryRoleStore:
    """Simple in-memory role store for demonstration."""

    def __init__(self) -> None:
        self._user_roles: dict[str, set[str]] = {}
        self._roles: dict[str, Role] = {}

    async def get_user_roles(
        self,
        user_id: str,
        tenant_id: str | None = None,
    ) -> list[str]:
        """Get role IDs for a user."""
        key = f"{user_id}:{tenant_id}" if tenant_id else user_id
        return list(self._user_roles.get(key, set()))

    async def get_role(self, role_id: str) -> Role | None:
        """Get role by ID."""
        return self._roles.get(role_id)

    async def assign_role(
        self,
        user_id: str,
        role_id: str,
        tenant_id: str | None = None,
    ) -> None:
        """Assign role to user."""
        key = f"{user_id}:{tenant_id}" if tenant_id else user_id
        if key not in self._user_roles:
            self._user_roles[key] = set()
        self._user_roles[key].add(role_id)

    async def revoke_role(
        self,
        user_id: str,
        role_id: str,
        tenant_id: str | None = None,
    ) -> None:
        """Revoke role from user."""
        key = f"{user_id}:{tenant_id}" if tenant_id else user_id
        if key in self._user_roles:
            self._user_roles[key].discard(role_id)

    def add_role_definition(self, role: Role) -> None:
        """Add role definition to store."""
        self._roles[role.id] = role


async def example_basic_rbac():
    """Example 1: Basic RBAC with roles and permissions."""
    print("\n=== Example 1: Basic RBAC ===\n")

    # Create role hierarchy
    hierarchy = RoleHierarchy()

    # Add standard roles
    await hierarchy.add_role(StandardRoles.ADMIN)
    await hierarchy.add_role(StandardRoles.USER)
    await hierarchy.add_role(StandardRoles.VIEWER)

    # Create custom role
    editor = Role(
        id="editor",
        name="Editor",
        description="Can read and write documents",
        permissions=PermissionSet.from_strings(
            [
                "document.read",
                "document.write",
                "comment.create",
            ]
        ),
        parent_role_ids=["viewer"],  # Inherits from viewer
    )
    await hierarchy.add_role(editor)

    # Check effective permissions (includes inheritance)
    editor_perms = await hierarchy.get_effective_permissions("editor")
    print(f"Editor permissions: {editor_perms.to_strings()}")

    # Check role hierarchy
    ancestors = await hierarchy.get_ancestor_roles("editor")
    print(f"Editor ancestors: {ancestors}")


async def example_permission_engine():
    """Example 2: Permission engine with caching."""
    print("\n=== Example 2: Permission Engine ===\n")

    # Setup
    role_store = InMemoryRoleStore()
    hierarchy = RoleHierarchy()

    # Add roles
    await hierarchy.add_role(StandardRoles.ADMIN)
    await hierarchy.add_role(StandardRoles.USER)

    # Add role definitions to store
    role_store.add_role_definition(StandardRoles.ADMIN)
    role_store.add_role_definition(StandardRoles.USER)

    # Assign roles to user
    await role_store.assign_role("user_123", "user")

    # Create permission engine
    engine = PermissionEngine(
        role_store=role_store,
        role_hierarchy=hierarchy,
        cache_ttl_seconds=300,
    )

    # Create security context
    sec_ctx = create_security_context(
        user_id="user_123",
        tenant_id="tenant_456",
    )

    # Check permissions
    can_read = await engine.has_permission(
        user_id="user_123",
        permission="profile.read:own",
        security_context=sec_ctx,
    )
    print(f"User can read own profile: {can_read}")

    can_delete_all = await engine.has_permission(
        user_id="user_123",
        permission="user.delete",
        security_context=sec_ctx,
    )
    print(f"User can delete users: {can_delete_all}")

    # Batch check
    perms_to_check = [
        "profile.read:own",
        "profile.write:own",
        "resource.read:own",
        "admin.settings",
    ]
    results = await engine.check_permissions(
        user_id="user_123",
        permissions=perms_to_check,
        security_context=sec_ctx,
    )
    print("\nBatch permission check:")
    for perm, granted in results.items():
        print(f"  {perm}: {granted}")


async def example_policy_enforcement():
    """Example 3: Policy enforcement point."""
    print("\n=== Example 3: Policy Enforcement Point ===\n")

    # Setup
    role_store = InMemoryRoleStore()
    hierarchy = RoleHierarchy()

    await hierarchy.add_role(StandardRoles.ADMIN)
    role_store.add_role_definition(StandardRoles.ADMIN)
    await role_store.assign_role("admin_user", "admin")

    engine = PermissionEngine(
        role_store=role_store,
        role_hierarchy=hierarchy,
    )

    # Create PEP
    pep = PolicyEnforcementPoint(permission_engine=engine)

    # Add audit hook
    async def audit_hook(ctx: PolicyContext, decision):
        print(f"  [AUDIT] {ctx.user_id} -> {ctx.resource}.{ctx.action}: {decision.decision.value}")

    pep.add_post_enforcement_hook(audit_hook)

    # Create security context
    sec_ctx = create_security_context(user_id="admin_user")

    # Enforce policy
    decision = await pep.enforce(
        context=PolicyContext(
            user_id="admin_user",
            resource="system",
            resource_id="settings",
            action="write",
        ),
        security_context=sec_ctx,
    )

    print(f"Decision: {decision.decision.value}")
    print(f"Reason: {decision.reason}")

    # Try unauthorized access
    decision2 = await pep.enforce(
        context=PolicyContext(
            user_id="unauthorized_user",
            resource="admin",
            action="access",
        ),
        security_context=create_security_context(user_id="unauthorized_user"),
    )

    print(f"\nUnauthorized decision: {decision2.decision.value}")
    print(f"Reason: {decision2.reason}")


async def example_context_aware_rbac():
    """Example 4: Context-aware RBAC with dynamic permissions."""
    print("\n=== Example 4: Context-Aware RBAC ===\n")

    # Setup
    role_store = InMemoryRoleStore()
    hierarchy = RoleHierarchy()

    # Create role with sensitive data access
    sensitive_reader = Role(
        id="sensitive_reader",
        name="Sensitive Data Reader",
        description="Can read sensitive data with restrictions",
        permissions=PermissionSet.from_strings(
            [
                "sensitive_data.read",
                "sensitive_data.export",
            ]
        ),
    )
    await hierarchy.add_role(sensitive_reader)
    role_store.add_role_definition(sensitive_reader)
    await role_store.assign_role("user_456", "sensitive_reader")

    engine = PermissionEngine(
        role_store=role_store,
        role_hierarchy=hierarchy,
    )

    # Create context-aware RBAC
    rbac = ContextAwareRBAC(permission_engine=engine)

    # Add dynamic permission with time and location rules
    rbac.add_dynamic_permission(
        DynamicPermission(
            permission="sensitive_data.read",
            rules=[
                TimeRule(
                    start_hour=9,
                    end_hour=17,
                    days_of_week=[0, 1, 2, 3, 4],  # Monday-Friday
                ),
                LocationRule(
                    allowed_networks=["10.0.0.0/8"],
                ),
            ],
            require_all_rules=True,
            description="Sensitive data can only be read during business hours from office network",
        )
    )

    # Test during business hours from office
    sec_ctx = create_security_context(user_id="user_456")
    policy_ctx_office = PolicyContext(
        user_id="user_456",
        resource="sensitive_data",
        action="read",
        environment={
            "timestamp": datetime.now().replace(hour=14),  # 2 PM
            "ip_address": "10.0.1.100",
        },
    )

    allowed = await rbac.has_permission_with_context(
        user_id="user_456",
        permission="sensitive_data.read",
        policy_context=policy_ctx_office,
        security_context=sec_ctx,
    )
    print(f"Access during business hours from office: {allowed}")

    # Test outside business hours
    policy_ctx_night = PolicyContext(
        user_id="user_456",
        resource="sensitive_data",
        action="read",
        environment={
            "timestamp": datetime.now().replace(hour=22),  # 10 PM
            "ip_address": "10.0.1.100",
        },
    )

    allowed_night = await rbac.has_permission_with_context(
        user_id="user_456",
        permission="sensitive_data.read",
        policy_context=policy_ctx_night,
        security_context=sec_ctx,
    )
    print(f"Access outside business hours: {allowed_night}")


async def example_attribute_based_access():
    """Example 5: Attribute-based access control."""
    print("\n=== Example 5: Attribute-Based Access Control ===\n")

    # Setup
    role_store = InMemoryRoleStore()
    hierarchy = RoleHierarchy()

    hr_role = Role(
        id="hr_staff",
        name="HR Staff",
        description="HR department staff",
        permissions=PermissionSet.from_strings(
            [
                "employee_data.read",
                "employee_data.write",
            ]
        ),
    )
    await hierarchy.add_role(hr_role)
    role_store.add_role_definition(hr_role)
    await role_store.assign_role("hr_user", "hr_staff")

    engine = PermissionEngine(
        role_store=role_store,
        role_hierarchy=hierarchy,
    )

    rbac = ContextAwareRBAC(permission_engine=engine)

    # Add attribute-based permission
    rbac.add_dynamic_permission(
        DynamicPermission(
            permission="employee_data.read",
            rules=[
                AttributeRule(
                    attribute_path="department",
                    operator="eq",
                    value="hr",
                    attribute_source="user",
                ),
                AttributeRule(
                    attribute_path="sensitivity",
                    operator="in",
                    value=["public", "internal"],
                    attribute_source="resource",
                ),
            ],
            require_all_rules=True,
        )
    )

    # Test with HR user accessing internal data
    sec_ctx = create_security_context(user_id="hr_user")
    policy_ctx = PolicyContext(
        user_id="hr_user",
        resource="employee_data",
        action="read",
        attributes={
            "user": {"department": "hr"},
            "resource": {"sensitivity": "internal"},
        },
    )

    allowed = await rbac.has_permission_with_context(
        user_id="hr_user",
        permission="employee_data.read",
        policy_context=policy_ctx,
        security_context=sec_ctx,
    )
    print(f"HR user accessing internal employee data: {allowed}")


async def main():
    """Run all examples."""
    print("=" * 60)
    print("RBAC Component Examples")
    print("=" * 60)

    await example_basic_rbac()
    await example_permission_engine()
    await example_policy_enforcement()
    await example_context_aware_rbac()
    await example_attribute_based_access()

    print("\n" + "=" * 60)
    print("All examples completed!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
