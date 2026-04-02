"""
Role definitions and permission sets for the Agentic AI Component Library.

This module provides the foundation for Role-Based Access Control (RBAC)
including role hierarchies, permission sets, and wildcard support.

Example:
    ```python
    from yoda_foundation.security.rbac import (
        Role,
        RoleHierarchy,
        PermissionSet,
        StandardRoles,
    )

    # Create a custom role
    editor = Role(
        id="editor",
        name="Editor",
        description="Can read and edit documents",
        permissions=PermissionSet.from_strings([
            "document.read",
            "document.write",
            "comment.create",
        ]),
    )

    # Create role hierarchy
    hierarchy = RoleHierarchy()
    await hierarchy.add_role(StandardRoles.ADMIN)
    await hierarchy.add_role(editor, parent_role_ids=["user"])

    # Check inheritance
    admin_perms = await hierarchy.get_effective_permissions("admin")
    ```
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from yoda_foundation.exceptions import (
    AuthorizationError,
    ValidationError,
)
from yoda_foundation.security.context import Permission


@dataclass(frozen=True)
class PermissionSet:
    """
    Immutable set of permissions with utility methods.

    A permission set is a collection of permissions that can be
    assigned to roles or checked for authorization.

    Attributes:
        permissions: Frozenset of Permission objects
        metadata: Additional metadata about the permission set

    Example:
        ```python
        # Create from strings
        perms = PermissionSet.from_strings([
            "document.read",
            "document.write",
            "agent.execute",
        ])

        # Check if includes a permission
        if perms.includes("document.read"):
            print("Can read documents")

        # Merge permission sets
        admin_perms = PermissionSet.from_strings(["*.*"])
        combined = perms.merge(admin_perms)
        ```
    """

    permissions: frozenset[Permission]
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate permission set."""
        if not isinstance(self.permissions, frozenset):
            object.__setattr__(
                self,
                "permissions",
                frozenset(self.permissions),
            )

    @classmethod
    def from_strings(
        cls,
        permission_strings: list[str],
        metadata: dict[str, Any] | None = None,
    ) -> PermissionSet:
        """
        Create a permission set from string representations.

        Args:
            permission_strings: List of permission strings (e.g., "resource.action")
            metadata: Optional metadata

        Returns:
            PermissionSet instance

        Raises:
            ValidationError: If any permission string is invalid

        Example:
            ```python
            perms = PermissionSet.from_strings([
                "user.read",
                "user.write:own",
                "admin.*",
            ])
            ```
        """
        permissions = set()
        for perm_str in permission_strings:
            try:
                permissions.add(Permission.from_string(perm_str))
            except (AuthorizationError, ValueError) as e:
                raise ValidationError(
                    message=f"Invalid permission string: {perm_str}",
                    field_name="permission_strings",
                    details={"invalid_permission": perm_str},
                    cause=e,
                )

        return cls(
            permissions=frozenset(permissions),
            metadata=metadata or {},
        )

    @classmethod
    def empty(cls) -> PermissionSet:
        """
        Create an empty permission set.

        Returns:
            Empty PermissionSet

        Example:
            ```python
            no_perms = PermissionSet.empty()
            assert not no_perms.includes("any.action")
            ```
        """
        return cls(permissions=frozenset())

    @classmethod
    def admin(cls) -> PermissionSet:
        """
        Create an admin permission set with wildcard access.

        Returns:
            PermissionSet with full permissions

        Example:
            ```python
            admin_perms = PermissionSet.admin()
            assert admin_perms.includes("any.action")
            ```
        """
        return cls(
            permissions=frozenset([Permission("*", "*")]),
            metadata={"type": "admin"},
        )

    def includes(self, permission: str | Permission) -> bool:
        """
        Check if this set includes the specified permission.

        Supports wildcard matching.

        Args:
            permission: Permission string or Permission object

        Returns:
            True if the permission is included

        Example:
            ```python
            perms = PermissionSet.from_strings(["document.*"])
            assert perms.includes("document.read")
            assert perms.includes("document.write")
            assert not perms.includes("user.read")
            ```
        """
        if isinstance(permission, str):
            permission = Permission.from_string(permission)

        return any(p.matches(permission) for p in self.permissions)

    def merge(self, other: PermissionSet) -> PermissionSet:
        """
        Merge with another permission set.

        Args:
            other: Another PermissionSet to merge with

        Returns:
            New PermissionSet with combined permissions

        Example:
            ```python
            set1 = PermissionSet.from_strings(["doc.read"])
            set2 = PermissionSet.from_strings(["doc.write"])
            combined = set1.merge(set2)
            assert combined.includes("doc.read")
            assert combined.includes("doc.write")
            ```
        """
        merged_perms = self.permissions | other.permissions
        merged_metadata = {**self.metadata, **other.metadata}

        return PermissionSet(
            permissions=merged_perms,
            metadata=merged_metadata,
        )

    def to_strings(self) -> list[str]:
        """
        Convert permissions to string list.

        Returns:
            List of permission strings

        Example:
            ```python
            perms = PermissionSet.from_strings(["doc.read", "doc.write"])
            strings = perms.to_strings()
            assert "doc.read" in strings
            ```
        """
        return sorted([str(p) for p in self.permissions])

    def __len__(self) -> int:
        """Return number of permissions."""
        return len(self.permissions)

    def __bool__(self) -> bool:
        """Check if permission set is non-empty."""
        return len(self.permissions) > 0


@dataclass
class Role:
    """
    Represents a role in the RBAC system.

    A role is a collection of permissions that can be assigned to users
    or agents. Roles can have parent roles for hierarchical inheritance.

    Attributes:
        id: Unique role identifier
        name: Human-readable role name
        description: Role description
        permissions: Set of permissions granted by this role
        parent_role_ids: List of parent role IDs for inheritance
        metadata: Additional role metadata
        created_at: When the role was created
        updated_at: When the role was last updated
        is_system: Whether this is a system-defined role

    Example:
        ```python
        role = Role(
            id="content_editor",
            name="Content Editor",
            description="Can create and edit content",
            permissions=PermissionSet.from_strings([
                "content.read",
                "content.write",
                "content.publish",
            ]),
            parent_role_ids=["viewer"],
        )
        ```
    """

    id: str
    name: str
    description: str
    permissions: PermissionSet
    parent_role_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    is_system: bool = False

    def __post_init__(self) -> None:
        """Validate role definition."""
        if not self.id:
            raise ValidationError(
                message="Role ID is required",
                field_name="id",
            )

        if not re.match(r"^[a-z][a-z0-9_]*$", self.id):
            raise ValidationError(
                message="Role ID must start with lowercase letter and contain only lowercase letters, numbers, and underscores",
                field_name="id",
                details={"role_id": self.id},
            )

        if not self.name:
            raise ValidationError(
                message="Role name is required",
                field_name="name",
            )

        # Detect circular references in parent_role_ids
        if self.id in self.parent_role_ids:
            raise ValidationError(
                message="Role cannot be its own parent",
                field_name="parent_role_ids",
                details={"role_id": self.id},
            )

    def has_permission(self, permission: str | Permission) -> bool:
        """
        Check if this role has a specific permission.

        Note: This only checks the role's direct permissions,
        not inherited permissions from parent roles.

        Args:
            permission: Permission string or Permission object

        Returns:
            True if the permission is granted by this role

        Example:
            ```python
            if role.has_permission("document.write"):
                print("Role can write documents")
            ```
        """
        return self.permissions.includes(permission)

    def to_dict(self) -> dict[str, Any]:
        """
        Convert role to dictionary for serialization.

        Returns:
            Dictionary representation of the role

        Example:
            ```python
            role_dict = role.to_dict()
            await storage.save_role(role_dict)
            ```
        """
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "permissions": self.permissions.to_strings(),
            "parent_role_ids": self.parent_role_ids,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "is_system": self.is_system,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Role:
        """
        Create role from dictionary.

        Args:
            data: Dictionary representation

        Returns:
            Role instance

        Example:
            ```python
            role_data = await storage.get_role(role_id)
            role = Role.from_dict(role_data)
            ```
        """
        permissions = PermissionSet.from_strings(data.get("permissions", []))

        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)

        updated_at = data.get("updated_at")
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at)

        return cls(
            id=data["id"],
            name=data["name"],
            description=data.get("description", ""),
            permissions=permissions,
            parent_role_ids=data.get("parent_role_ids", []),
            metadata=data.get("metadata", {}),
            created_at=created_at or datetime.now(UTC),
            updated_at=updated_at or datetime.now(UTC),
            is_system=data.get("is_system", False),
        )


class RoleHierarchy:
    """
    Manages hierarchical relationships between roles.

    Handles role inheritance, circular dependency detection,
    and effective permission calculation.

    Example:
        ```python
        hierarchy = RoleHierarchy()

        # Add roles
        await hierarchy.add_role(admin_role)
        await hierarchy.add_role(editor_role, parent_role_ids=["viewer"])
        await hierarchy.add_role(viewer_role)

        # Get effective permissions (includes inherited)
        editor_perms = await hierarchy.get_effective_permissions("editor")

        # Check if role exists in hierarchy
        ancestors = await hierarchy.get_ancestor_roles("editor")
        ```
    """

    def __init__(self) -> None:
        """Initialize empty role hierarchy."""
        self._roles: dict[str, Role] = {}
        self._parent_map: dict[str, set[str]] = {}  # role_id -> parent_ids
        self._child_map: dict[str, set[str]] = {}  # role_id -> child_ids

    async def add_role(
        self,
        role: Role,
        parent_role_ids: list[str] | None = None,
    ) -> None:
        """
        Add a role to the hierarchy.

        Args:
            role: Role to add
            parent_role_ids: Optional list of parent role IDs (overrides role.parent_role_ids)

        Raises:
            ValidationError: If role creates circular dependency

        Example:
            ```python
            await hierarchy.add_role(editor_role, parent_role_ids=["viewer"])
            ```
        """
        parent_ids = parent_role_ids or role.parent_role_ids

        # Check for circular dependencies
        if await self._would_create_cycle(role.id, parent_ids):
            raise ValidationError(
                message=f"Adding role '{role.id}' would create circular dependency",
                field_name="parent_role_ids",
                details={
                    "role_id": role.id,
                    "parent_role_ids": parent_ids,
                },
            )

        # Verify parent roles exist
        for parent_id in parent_ids:
            if parent_id not in self._roles:
                raise ValidationError(
                    message=f"Parent role '{parent_id}' does not exist",
                    field_name="parent_role_ids",
                    details={
                        "role_id": role.id,
                        "missing_parent": parent_id,
                    },
                )

        # Add role
        self._roles[role.id] = role
        self._parent_map[role.id] = set(parent_ids)

        # Update child map
        for parent_id in parent_ids:
            if parent_id not in self._child_map:
                self._child_map[parent_id] = set()
            self._child_map[parent_id].add(role.id)

    async def remove_role(self, role_id: str) -> None:
        """
        Remove a role from the hierarchy.

        Args:
            role_id: ID of the role to remove

        Raises:
            ValidationError: If role has children or doesn't exist

        Example:
            ```python
            await hierarchy.remove_role("temporary_role")
            ```
        """
        if role_id not in self._roles:
            raise ValidationError(
                message=f"Role '{role_id}' not found",
                field_name="role_id",
                details={"role_id": role_id},
            )

        # Check if role has children
        if self._child_map.get(role_id):
            raise ValidationError(
                message=f"Cannot remove role '{role_id}' with children",
                field_name="role_id",
                details={
                    "role_id": role_id,
                    "children": list(self._child_map[role_id]),
                },
            )

        # Remove from parent's children
        for parent_id in self._parent_map.get(role_id, set()):
            if parent_id in self._child_map:
                self._child_map[parent_id].discard(role_id)

        # Remove role
        del self._roles[role_id]
        del self._parent_map[role_id]
        self._child_map.pop(role_id, None)

    async def get_role(self, role_id: str) -> Role | None:
        """
        Get a role by ID.

        Args:
            role_id: Role ID

        Returns:
            Role object or None if not found

        Example:
            ```python
            role = await hierarchy.get_role("editor")
            if role:
                print(role.name)
            ```
        """
        return self._roles.get(role_id)

    async def get_ancestor_roles(self, role_id: str) -> list[str]:
        """
        Get all ancestor role IDs in the hierarchy.

        Returns roles from immediate parents to root, in breadth-first order.

        Args:
            role_id: Role ID to start from

        Returns:
            List of ancestor role IDs

        Example:
            ```python
            # If editor -> viewer -> user
            ancestors = await hierarchy.get_ancestor_roles("editor")
            # Returns: ["viewer", "user"]
            ```
        """
        if role_id not in self._roles:
            return []

        visited = set()
        ancestors = []
        queue = list(self._parent_map.get(role_id, set()))

        while queue:
            parent_id = queue.pop(0)
            if parent_id in visited:
                continue

            visited.add(parent_id)
            ancestors.append(parent_id)

            # Add grandparents
            queue.extend(self._parent_map.get(parent_id, set()))

        return ancestors

    async def get_effective_permissions(self, role_id: str) -> PermissionSet:
        """
        Get effective permissions including inherited permissions.

        Args:
            role_id: Role ID

        Returns:
            PermissionSet with all effective permissions

        Raises:
            ValidationError: If role doesn't exist

        Example:
            ```python
            perms = await hierarchy.get_effective_permissions("editor")
            if perms.includes("document.write"):
                print("Editor can write documents")
            ```
        """
        role = self._roles.get(role_id)
        if not role:
            raise ValidationError(
                message=f"Role '{role_id}' not found",
                field_name="role_id",
                details={"role_id": role_id},
            )

        # Start with role's own permissions
        effective = role.permissions

        # Merge parent permissions
        ancestors = await self.get_ancestor_roles(role_id)
        for ancestor_id in ancestors:
            ancestor_role = self._roles[ancestor_id]
            effective = effective.merge(ancestor_role.permissions)

        return effective

    async def has_role(self, role_id: str) -> bool:
        """
        Check if a role exists in the hierarchy.

        Args:
            role_id: Role ID to check

        Returns:
            True if role exists

        Example:
            ```python
            if await hierarchy.has_role("admin"):
                print("Admin role exists")
            ```
        """
        return role_id in self._roles

    async def _would_create_cycle(
        self,
        role_id: str,
        parent_ids: list[str],
    ) -> bool:
        """
        Check if adding parents would create a circular dependency.

        Args:
            role_id: Role being added/updated
            parent_ids: Proposed parent role IDs

        Returns:
            True if this would create a cycle
        """
        for parent_id in parent_ids:
            # Check if parent_id is a descendant of role_id
            visited = set()
            queue = [parent_id]

            while queue:
                current = queue.pop(0)
                if current == role_id:
                    return True

                if current in visited:
                    continue
                visited.add(current)

                # Check current's parents
                queue.extend(self._parent_map.get(current, set()))

        return False


class StandardRoles:
    """
    Pre-defined standard roles for common use cases.

    These roles can be used as-is or customized for specific applications.

    Example:
        ```python
        hierarchy = RoleHierarchy()
        await hierarchy.add_role(StandardRoles.ADMIN)
        await hierarchy.add_role(StandardRoles.USER)
        ```
    """

    ADMIN = Role(
        id="admin",
        name="Administrator",
        description="Full system access with all permissions",
        permissions=PermissionSet.admin(),
        is_system=True,
    )

    MANAGER = Role(
        id="manager",
        name="Manager",
        description="Can manage users and resources within their scope",
        permissions=PermissionSet.from_strings(
            [
                "user.read",
                "user.write:team",
                "resource.read",
                "resource.write:team",
                "report.read",
                "report.generate",
            ]
        ),
        parent_role_ids=["user"],
        is_system=True,
    )

    USER = Role(
        id="user",
        name="User",
        description="Standard authenticated user with basic permissions",
        permissions=PermissionSet.from_strings(
            [
                "profile.read:own",
                "profile.write:own",
                "resource.read:own",
                "resource.write:own",
            ]
        ),
        is_system=True,
    )

    VIEWER = Role(
        id="viewer",
        name="Viewer",
        description="Read-only access to resources",
        permissions=PermissionSet.from_strings(
            [
                "profile.read:own",
                "resource.read",
            ]
        ),
        is_system=True,
    )

    ANONYMOUS = Role(
        id="anonymous",
        name="Anonymous",
        description="Unauthenticated access with minimal permissions",
        permissions=PermissionSet.from_strings(
            [
                "public.read",
            ]
        ),
        is_system=True,
    )

    @classmethod
    def all_roles(cls) -> list[Role]:
        """
        Get all standard roles.

        Returns:
            List of all standard roles

        Example:
            ```python
            for role in StandardRoles.all_roles():
                await hierarchy.add_role(role)
            ```
        """
        return [
            cls.ADMIN,
            cls.MANAGER,
            cls.USER,
            cls.VIEWER,
            cls.ANONYMOUS,
        ]
