"""
Context-aware RBAC with dynamic permissions.

This module extends RBAC with attribute-based access control (ABAC)
capabilities including time-based, location-based, and data-based rules.

Example:
    ```python
    from yoda_foundation.security.rbac import (
        ContextAwareRBAC,
        DynamicPermission,
        ContextRule,
        TimeRule,
        LocationRule,
    )

    # Create dynamic permission with rules
    perm = DynamicPermission(
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
    )

    # Evaluate with context
    rbac = ContextAwareRBAC(permission_engine=engine)
    can_access = await rbac.evaluate_dynamic_permission(
        user_id="user_123",
        permission=perm,
        context=policy_context,
        security_context=sec_ctx,
    )
    ```
"""

from __future__ import annotations

import ipaddress
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from yoda_foundation.exceptions import ValidationError
from yoda_foundation.security.context import SecurityContext
from yoda_foundation.security.rbac.permission_engine import PermissionEngine
from yoda_foundation.security.rbac.policy_enforcement import (
    PolicyContext,
    PolicyDecision,
    PolicyDecisionType,
)


class RuleEvaluationResult(Enum):
    """Result of a rule evaluation."""

    ALLOW = "allow"
    DENY = "deny"
    NOT_APPLICABLE = "not_applicable"


@dataclass
class RuleContext:
    """
    Context information for rule evaluation.

    Attributes:
        timestamp: Current timestamp
        ip_address: Client IP address
        location: Client location
        user_attributes: User-specific attributes
        resource_attributes: Resource-specific attributes
        environment: Additional environmental context
    """

    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    ip_address: str | None = None
    location: str | None = None
    user_attributes: dict[str, Any] = field(default_factory=dict)
    resource_attributes: dict[str, Any] = field(default_factory=dict)
    environment: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_policy_context(cls, policy_context: PolicyContext) -> RuleContext:
        """
        Create RuleContext from PolicyContext.

        Args:
            policy_context: Policy context

        Returns:
            RuleContext instance

        Example:
            ```python
            rule_ctx = RuleContext.from_policy_context(policy_ctx)
            ```
        """
        env = policy_context.environment
        attrs = policy_context.attributes

        return cls(
            timestamp=env.get("timestamp", datetime.now(UTC)),
            ip_address=env.get("ip_address"),
            location=env.get("location"),
            user_attributes=attrs.get("user", {}),
            resource_attributes=attrs.get("resource", {}),
            environment=env,
        )


class ContextRule(ABC):
    """
    Base class for context-aware authorization rules.

    Rules evaluate contextual information to make dynamic
    authorization decisions.

    Example:
        ```python
        class CustomRule(ContextRule):
            async def evaluate(
                self,
                rule_context: RuleContext,
            ) -> RuleEvaluationResult:
                if rule_context.user_attributes.get("department") == "hr":
                    return RuleEvaluationResult.ALLOW
                return RuleEvaluationResult.NOT_APPLICABLE
        ```
    """

    @abstractmethod
    async def evaluate(self, rule_context: RuleContext) -> RuleEvaluationResult:
        """
        Evaluate the rule against the context.

        Args:
            rule_context: Context information

        Returns:
            RuleEvaluationResult indicating the decision

        Example:
            ```python
            result = await rule.evaluate(rule_context)
            if result == RuleEvaluationResult.ALLOW:
                print("Rule allows access")
            ```
        """
        pass

    @abstractmethod
    def to_dict(self) -> dict[str, Any]:
        """
        Convert rule to dictionary for serialization.

        Returns:
            Dictionary representation
        """
        pass


@dataclass
class TimeRule(ContextRule):
    """
    Time-based access rule.

    Restricts access to specific hours and days of the week.

    Attributes:
        start_hour: Start hour (0-23)
        end_hour: End hour (0-23)
        days_of_week: List of allowed days (0=Monday, 6=Sunday)
        timezone_name: Timezone for evaluation (e.g., "America/New_York")

    Example:
        ```python
        # Business hours only, Monday-Friday
        rule = TimeRule(
            start_hour=9,
            end_hour=17,
            days_of_week=[0, 1, 2, 3, 4],
            timezone_name="America/New_York",
        )

        result = await rule.evaluate(rule_context)
        ```
    """

    start_hour: int = 0
    end_hour: int = 23
    days_of_week: list[int] = field(default_factory=lambda: list(range(7)))
    timezone_name: str = "UTC"

    def __post_init__(self) -> None:
        """Validate time rule parameters."""
        if not (0 <= self.start_hour <= 23):
            raise ValidationError(
                message="start_hour must be between 0 and 23",
                field_name="start_hour",
            )

        if not (0 <= self.end_hour <= 23):
            raise ValidationError(
                message="end_hour must be between 0 and 23",
                field_name="end_hour",
            )

        if not all(0 <= day <= 6 for day in self.days_of_week):
            raise ValidationError(
                message="days_of_week must be between 0 (Monday) and 6 (Sunday)",
                field_name="days_of_week",
            )

    async def evaluate(self, rule_context: RuleContext) -> RuleEvaluationResult:
        """
        Evaluate time-based rule.

        Args:
            rule_context: Rule context with timestamp

        Returns:
            ALLOW if within allowed time, DENY otherwise

        Example:
            ```python
            result = await rule.evaluate(rule_context)
            if result == RuleEvaluationResult.ALLOW:
                print("Access allowed during business hours")
            ```
        """
        current_time = rule_context.timestamp

        # Check day of week (0=Monday)
        if current_time.weekday() not in self.days_of_week:
            return RuleEvaluationResult.DENY

        # Check hour
        current_hour = current_time.hour
        if self.start_hour <= current_hour < self.end_hour:
            return RuleEvaluationResult.ALLOW

        return RuleEvaluationResult.DENY

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "type": "time",
            "start_hour": self.start_hour,
            "end_hour": self.end_hour,
            "days_of_week": self.days_of_week,
            "timezone_name": self.timezone_name,
        }


@dataclass
class LocationRule(ContextRule):
    """
    Location-based access rule.

    Restricts access based on IP address or geographic location.

    Attributes:
        allowed_networks: List of allowed IP networks (CIDR notation)
        allowed_locations: List of allowed location identifiers
        deny_mode: If True, denies listed items instead of allowing

    Example:
        ```python
        # Only allow access from office network
        rule = LocationRule(
            allowed_networks=["10.0.0.0/8", "192.168.1.0/24"],
        )

        # Only allow access from specific locations
        rule = LocationRule(
            allowed_locations=["office", "vpn"],
        )
        ```
    """

    allowed_networks: list[str] = field(default_factory=list)
    allowed_locations: list[str] = field(default_factory=list)
    deny_mode: bool = False

    async def evaluate(self, rule_context: RuleContext) -> RuleEvaluationResult:
        """
        Evaluate location-based rule.

        Args:
            rule_context: Rule context with IP and location

        Returns:
            ALLOW/DENY based on location match

        Example:
            ```python
            result = await rule.evaluate(rule_context)
            if result == RuleEvaluationResult.ALLOW:
                print("Access from allowed location")
            ```
        """
        # Check IP networks
        if self.allowed_networks and rule_context.ip_address:
            ip_allowed = await self._check_ip_address(rule_context.ip_address)

            if self.deny_mode:
                return RuleEvaluationResult.DENY if ip_allowed else RuleEvaluationResult.ALLOW
            else:
                return RuleEvaluationResult.ALLOW if ip_allowed else RuleEvaluationResult.DENY

        # Check location strings
        if self.allowed_locations and rule_context.location:
            location_allowed = rule_context.location in self.allowed_locations

            if self.deny_mode:
                return RuleEvaluationResult.DENY if location_allowed else RuleEvaluationResult.ALLOW
            else:
                return RuleEvaluationResult.ALLOW if location_allowed else RuleEvaluationResult.DENY

        # No location restrictions configured
        return RuleEvaluationResult.NOT_APPLICABLE

    async def _check_ip_address(self, ip_address: str) -> bool:
        """
        Check if IP address is in allowed networks.

        Args:
            ip_address: IP address to check

        Returns:
            True if IP is in allowed networks
        """
        try:
            ip = ipaddress.ip_address(ip_address)

            for network_str in self.allowed_networks:
                network = ipaddress.ip_network(network_str)
                if ip in network:
                    return True

            return False
        except (ValueError, ipaddress.AddressValueError):
            # Invalid IP address
            return False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "type": "location",
            "allowed_networks": self.allowed_networks,
            "allowed_locations": self.allowed_locations,
            "deny_mode": self.deny_mode,
        }


@dataclass
class AttributeRule(ContextRule):
    """
    Attribute-based access rule.

    Evaluates user or resource attributes for access decisions.

    Attributes:
        attribute_path: Dot-notation path to attribute (e.g., "user.department")
        operator: Comparison operator (eq, ne, in, not_in, gt, lt, etc.)
        value: Value to compare against
        attribute_source: Source of attribute ("user" or "resource")

    Example:
        ```python
        # Only allow users in "engineering" department
        rule = AttributeRule(
            attribute_path="department",
            operator="eq",
            value="engineering",
            attribute_source="user",
        )

        # Only allow access to non-sensitive resources
        rule = AttributeRule(
            attribute_path="sensitivity",
            operator="in",
            value=["public", "internal"],
            attribute_source="resource",
        )
        ```
    """

    attribute_path: str
    operator: str
    value: Any
    attribute_source: str = "user"

    VALID_OPERATORS = {"eq", "ne", "in", "not_in", "gt", "lt", "gte", "lte", "contains"}

    def __post_init__(self) -> None:
        """Validate attribute rule parameters."""
        if self.operator not in self.VALID_OPERATORS:
            raise ValidationError(
                message=f"Invalid operator: {self.operator}",
                field_name="operator",
                details={"valid_operators": list(self.VALID_OPERATORS)},
            )

        if self.attribute_source not in ("user", "resource"):
            raise ValidationError(
                message="attribute_source must be 'user' or 'resource'",
                field_name="attribute_source",
            )

    async def evaluate(self, rule_context: RuleContext) -> RuleEvaluationResult:
        """
        Evaluate attribute-based rule.

        Args:
            rule_context: Rule context with attributes

        Returns:
            ALLOW if attribute matches, DENY otherwise

        Example:
            ```python
            result = await rule.evaluate(rule_context)
            if result == RuleEvaluationResult.ALLOW:
                print("Attribute check passed")
            ```
        """
        # Get attributes based on source
        if self.attribute_source == "user":
            attributes = rule_context.user_attributes
        else:
            attributes = rule_context.resource_attributes

        # Get attribute value using dot notation
        attr_value = self._get_nested_attribute(attributes, self.attribute_path)

        if attr_value is None:
            # Attribute not found
            return RuleEvaluationResult.NOT_APPLICABLE

        # Evaluate based on operator
        match = await self._evaluate_operator(attr_value, self.operator, self.value)

        return RuleEvaluationResult.ALLOW if match else RuleEvaluationResult.DENY

    def _get_nested_attribute(
        self,
        attributes: dict[str, Any],
        path: str,
    ) -> Any:
        """
        Get nested attribute value using dot notation.

        Args:
            attributes: Attribute dictionary
            path: Dot-notation path (e.g., "user.department")

        Returns:
            Attribute value or None
        """
        parts = path.split(".")
        value = attributes

        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return None

        return value

    async def _evaluate_operator(
        self,
        attr_value: Any,
        operator: str,
        expected_value: Any,
    ) -> bool:
        """
        Evaluate operator comparison.

        Args:
            attr_value: Actual attribute value
            operator: Comparison operator
            expected_value: Expected value

        Returns:
            True if comparison matches
        """
        if operator == "eq":
            return attr_value == expected_value
        elif operator == "ne":
            return attr_value != expected_value
        elif operator == "in":
            return attr_value in expected_value
        elif operator == "not_in":
            return attr_value not in expected_value
        elif operator == "gt":
            return attr_value > expected_value
        elif operator == "lt":
            return attr_value < expected_value
        elif operator == "gte":
            return attr_value >= expected_value
        elif operator == "lte":
            return attr_value <= expected_value
        elif operator == "contains":
            return expected_value in attr_value
        else:
            return False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "type": "attribute",
            "attribute_path": self.attribute_path,
            "operator": self.operator,
            "value": self.value,
            "attribute_source": self.attribute_source,
        }


@dataclass
class DataOwnershipRule(ContextRule):
    """
    Data ownership rule for "own data only" access.

    Allows access only if user owns the resource.

    Attributes:
        owner_attribute: Attribute path in resource for owner ID
        user_id_attribute: Attribute path in user for user ID

    Example:
        ```python
        # User can only access their own documents
        rule = DataOwnershipRule(
            owner_attribute="owner_id",
            user_id_attribute="id",
        )
        ```
    """

    owner_attribute: str = "owner_id"
    user_id_attribute: str = "id"

    async def evaluate(self, rule_context: RuleContext) -> RuleEvaluationResult:
        """
        Evaluate ownership rule.

        Args:
            rule_context: Rule context

        Returns:
            ALLOW if user owns resource, DENY otherwise

        Example:
            ```python
            result = await rule.evaluate(rule_context)
            if result == RuleEvaluationResult.ALLOW:
                print("User owns this resource")
            ```
        """
        owner_id = rule_context.resource_attributes.get(self.owner_attribute)
        user_id = rule_context.user_attributes.get(self.user_id_attribute)

        if owner_id is None or user_id is None:
            return RuleEvaluationResult.NOT_APPLICABLE

        return RuleEvaluationResult.ALLOW if owner_id == user_id else RuleEvaluationResult.DENY

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "type": "ownership",
            "owner_attribute": self.owner_attribute,
            "user_id_attribute": self.user_id_attribute,
        }


@dataclass
class DynamicPermission:
    """
    Permission with contextual rules for dynamic evaluation.

    Combines a base permission with rules that must be satisfied
    for the permission to be granted.

    Attributes:
        permission: Base permission string
        rules: List of contextual rules
        require_all_rules: If True, all rules must pass (AND logic)
        description: Human-readable description
        metadata: Additional metadata

    Example:
        ```python
        perm = DynamicPermission(
            permission="sensitive_data.read",
            rules=[
                TimeRule(start_hour=9, end_hour=17),
                LocationRule(allowed_networks=["10.0.0.0/8"]),
            ],
            require_all_rules=True,
            description="Read sensitive data during business hours from office",
        )
        ```
    """

    permission: str
    rules: list[ContextRule] = field(default_factory=list)
    require_all_rules: bool = True
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    async def evaluate_rules(
        self,
        rule_context: RuleContext,
    ) -> bool:
        """
        Evaluate all rules against the context.

        Args:
            rule_context: Context for rule evaluation

        Returns:
            True if rules allow access

        Example:
            ```python
            allowed = await perm.evaluate_rules(rule_context)
            if allowed:
                print("All rules satisfied")
            ```
        """
        if not self.rules:
            # No rules means permission is static
            return True

        results = []
        for rule in self.rules:
            result = await rule.evaluate(rule_context)
            results.append(result)

        if self.require_all_rules:
            # All rules must ALLOW (none can DENY)
            return all(r != RuleEvaluationResult.DENY for r in results)
        else:
            # At least one rule must ALLOW
            return any(r == RuleEvaluationResult.ALLOW for r in results)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "permission": self.permission,
            "rules": [rule.to_dict() for rule in self.rules],
            "require_all_rules": self.require_all_rules,
            "description": self.description,
            "metadata": self.metadata,
        }


class ContextAwareRBAC:
    """
    Context-aware RBAC engine with dynamic permissions.

    Extends standard RBAC with attribute-based access control (ABAC)
    by evaluating contextual rules in addition to role permissions.

    Example:
        ```python
        rbac = ContextAwareRBAC(permission_engine=engine)

        # Add dynamic permission
        rbac.add_dynamic_permission(
            DynamicPermission(
                permission="sensitive_data.read",
                rules=[
                    TimeRule(start_hour=9, end_hour=17),
                    LocationRule(allowed_networks=["10.0.0.0/8"]),
                ],
            )
        )

        # Evaluate with context
        allowed = await rbac.has_permission_with_context(
            user_id="user_123",
            permission="sensitive_data.read",
            policy_context=policy_ctx,
            security_context=sec_ctx,
        )
        ```
    """

    def __init__(self, permission_engine: PermissionEngine) -> None:
        """
        Initialize context-aware RBAC.

        Args:
            permission_engine: Base permission engine
        """
        self._permission_engine = permission_engine
        self._dynamic_permissions: dict[str, DynamicPermission] = {}

    def add_dynamic_permission(self, dynamic_perm: DynamicPermission) -> None:
        """
        Register a dynamic permission.

        Args:
            dynamic_perm: Dynamic permission to register

        Example:
            ```python
            rbac.add_dynamic_permission(
                DynamicPermission(
                    permission="admin.access",
                    rules=[TimeRule(start_hour=9, end_hour=17)],
                )
            )
            ```
        """
        self._dynamic_permissions[dynamic_perm.permission] = dynamic_perm

    async def has_permission_with_context(
        self,
        user_id: str,
        permission: str,
        policy_context: PolicyContext,
        security_context: SecurityContext,
    ) -> bool:
        """
        Check permission with contextual rules.

        Args:
            user_id: User identifier
            permission: Permission to check
            policy_context: Policy context with environment
            security_context: Security context

        Returns:
            True if permission granted with context

        Example:
            ```python
            allowed = await rbac.has_permission_with_context(
                user_id="user_123",
                permission="sensitive_data.read",
                policy_context=policy_ctx,
                security_context=sec_ctx,
            )
            ```
        """
        # First check base RBAC permission
        has_base_perm = await self._permission_engine.has_permission(
            user_id=user_id,
            permission=permission,
            security_context=security_context,
        )

        if not has_base_perm:
            return False

        # Check dynamic rules if configured
        dynamic_perm = self._dynamic_permissions.get(permission)
        if dynamic_perm:
            rule_context = RuleContext.from_policy_context(policy_context)
            return await dynamic_perm.evaluate_rules(rule_context)

        return True

    async def evaluate_dynamic_permission(
        self,
        user_id: str,
        permission: DynamicPermission,
        policy_context: PolicyContext,
        security_context: SecurityContext,
    ) -> PolicyDecision:
        """
        Evaluate a dynamic permission and return detailed decision.

        Args:
            user_id: User identifier
            permission: Dynamic permission to evaluate
            policy_context: Policy context
            security_context: Security context

        Returns:
            PolicyDecision with evaluation details

        Example:
            ```python
            decision = await rbac.evaluate_dynamic_permission(
                user_id="user_123",
                permission=dynamic_perm,
                policy_context=policy_ctx,
                security_context=sec_ctx,
            )

            if decision.deny:
                print(f"Denied: {decision.reason}")
            ```
        """
        # Check base permission
        has_base_perm = await self._permission_engine.has_permission(
            user_id=user_id,
            permission=permission.permission,
            security_context=security_context,
        )

        if not has_base_perm:
            return PolicyDecision(
                decision=PolicyDecisionType.DENY,
                reason=f"User lacks base permission: {permission.permission}",
                context=policy_context,
                suggestions=[
                    f"Request the '{permission.permission}' permission",
                ],
            )

        # Evaluate contextual rules
        rule_context = RuleContext.from_policy_context(policy_context)
        rules_pass = await permission.evaluate_rules(rule_context)

        if rules_pass:
            return PolicyDecision(
                decision=PolicyDecisionType.ALLOW,
                reason="Permission granted with contextual rules satisfied",
                context=policy_context,
                details={
                    "permission": permission.permission,
                    "rules_evaluated": len(permission.rules),
                },
            )
        else:
            return PolicyDecision(
                decision=PolicyDecisionType.DENY,
                reason=f"Contextual rules not satisfied for {permission.permission}",
                context=policy_context,
                suggestions=[
                    "Ensure you meet the contextual requirements (time, location, etc.)",
                    permission.description if permission.description else "",
                ],
            )
