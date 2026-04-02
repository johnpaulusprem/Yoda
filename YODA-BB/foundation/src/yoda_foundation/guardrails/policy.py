"""
Custom policy enforcement guardrails.

This module provides guardrails for enforcing custom business policies
using rules defined via regex patterns, keywords, or custom functions.

Example:
    ```python
    from yoda_foundation.guardrails.policy import (
        PolicyGuardrail,
        Policy,
        PolicyRule,
    )

    # Create custom policy
    policy = Policy(
        policy_id="competitor_policy",
        name="Competitor Mention Policy",
        rules=[
            PolicyRule(
                rule_id="no_competitor_names",
                condition=r"\\b(competitor_a|competitor_b)\\b",
                action=GuardrailAction.BLOCK,
                message="Cannot mention competitor names",
            ),
        ],
    )

    # Create guardrail
    guardrail = PolicyGuardrail()
    guardrail.add_policy(policy)

    # Evaluate content
    result = await guardrail.evaluate(
        content="Have you tried competitor_a?",
        policy=policy,
        security_context=ctx,
    )
    ```
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from yoda_foundation.guardrails.base import InputGuardrail
from yoda_foundation.guardrails.schemas import (
    GuardrailAction,
    GuardrailConfig,
    GuardrailResult,
    RiskLevel,
    Violation,
)
from yoda_foundation.security.context import SecurityContext
from yoda_foundation.observability.logging import get_logger


logger = get_logger(__name__)


@dataclass
class PolicyRule:
    """
    A rule within a policy.

    Attributes:
        rule_id: Unique rule identifier
        condition: Regex pattern or callable for matching
        action: Action to take when matched
        message: Human-readable message
        severity: Risk level when triggered
        enabled: Whether rule is active
        metadata: Additional rule metadata

    Example:
        ```python
        # Regex-based rule
        rule = PolicyRule(
            rule_id="no_prices",
            condition=r"\\$\\d+",
            action=GuardrailAction.BLOCK,
            message="Cannot mention specific prices",
            severity=RiskLevel.MEDIUM,
        )

        # Callable rule
        def check_length(content: str) -> bool:
            return len(content) > 1000

        rule = PolicyRule(
            rule_id="max_length",
            condition=check_length,
            action=GuardrailAction.WARN,
            message="Content exceeds maximum length",
        )
        ```
    """

    rule_id: str
    condition: str | Callable[[str], bool]
    action: GuardrailAction
    message: str
    severity: RiskLevel = RiskLevel.MEDIUM
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Compile regex pattern if condition is a string."""
        if isinstance(self.condition, str):
            self._compiled_pattern = re.compile(self.condition, re.IGNORECASE)
        else:
            self._compiled_pattern = None

    async def evaluate(self, content: str) -> Violation | None:
        """
        Evaluate rule against content.

        Args:
            content: Content to evaluate

        Returns:
            Violation if rule matches, None otherwise
        """
        if not self.enabled:
            return None

        matched = False
        evidence = None
        location = None

        if self._compiled_pattern:
            # Regex-based evaluation
            match = self._compiled_pattern.search(content)
            if match:
                matched = True
                evidence = match.group()
                location = (match.start(), match.end())
        elif callable(self.condition):
            # Callable evaluation
            result = self.condition(content)
            if isinstance(result, bool):
                matched = result
            elif hasattr(result, "__await__"):
                matched = await result

        if matched:
            return Violation(
                rule_id=self.rule_id,
                rule_name=self.rule_id,
                severity=self.severity,
                description=self.message,
                evidence=evidence,
                location=location,
                metadata=self.metadata,
            )

        return None


@dataclass
class Policy:
    """
    A policy containing multiple rules.

    Attributes:
        policy_id: Unique policy identifier
        name: Human-readable name
        description: Policy description
        rules: List of policy rules
        action: Default action when policy violated
        enabled: Whether policy is active
        priority: Evaluation priority
        metadata: Additional policy metadata

    Example:
        ```python
        policy = Policy(
            policy_id="content_policy",
            name="Content Policy",
            description="Company content guidelines",
            rules=[
                PolicyRule(
                    rule_id="no_competitor_names",
                    condition=r"\\b(acme|contoso)\\b",
                    action=GuardrailAction.BLOCK,
                    message="Cannot mention competitor names",
                ),
                PolicyRule(
                    rule_id="no_promises",
                    condition=r"\\b(guarantee|promise|definitely)\\b",
                    action=GuardrailAction.WARN,
                    message="Avoid making absolute promises",
                ),
            ],
        )
        ```
    """

    policy_id: str
    name: str
    description: str = ""
    rules: list[PolicyRule] = field(default_factory=list)
    action: GuardrailAction = GuardrailAction.BLOCK
    enabled: bool = True
    priority: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_rule(self, rule: PolicyRule) -> None:
        """
        Add a rule to the policy.

        Args:
            rule: PolicyRule to add
        """
        self.rules.append(rule)

    def remove_rule(self, rule_id: str) -> bool:
        """
        Remove a rule from the policy.

        Args:
            rule_id: Rule ID to remove

        Returns:
            True if rule was removed
        """
        initial_count = len(self.rules)
        self.rules = [r for r in self.rules if r.rule_id != rule_id]
        return len(self.rules) < initial_count


class PolicyGuardrail(InputGuardrail):
    """
    Guardrail for enforcing custom policies.

    Evaluates content against configured policies and their rules,
    returning violations for any matches.

    Attributes:
        policies: Dictionary of registered policies

    Example:
        ```python
        guardrail = PolicyGuardrail()

        # Add policies
        guardrail.add_policy(competitor_policy)
        guardrail.add_policy(legal_policy)

        # Evaluate content
        result = await guardrail.check(
            content="Check out competitor_a for alternatives",
            security_context=ctx,
        )

        if not result.passed:
            for violation in result.violations:
                print(f"Policy violation: {violation.description}")
        ```
    """

    def __init__(
        self,
        policies: list[Policy] | None = None,
        guardrail_id: str | None = None,
        priority: int = 40,
        enabled: bool = True,
        config: GuardrailConfig | None = None,
    ) -> None:
        """
        Initialize the policy guardrail.

        Args:
            policies: Initial policies to register
            guardrail_id: Unique identifier
            priority: Execution priority
            enabled: Whether guardrail is active
            config: Guardrail configuration
        """
        super().__init__(
            guardrail_id=guardrail_id or "policy_guardrail",
            priority=priority,
            enabled=enabled,
            config=config,
        )
        self.policies: dict[str, Policy] = {}

        if policies:
            for policy in policies:
                self.add_policy(policy)

    def add_policy(self, policy: Policy) -> None:
        """
        Register a policy.

        Args:
            policy: Policy to register

        Example:
            ```python
            guardrail.add_policy(Policy(
                policy_id="legal",
                name="Legal Policy",
                rules=[...],
            ))
            ```
        """
        self.policies[policy.policy_id] = policy
        logger.debug(f"Added policy: {policy.policy_id}")

    def remove_policy(self, policy_id: str) -> bool:
        """
        Remove a policy.

        Args:
            policy_id: Policy ID to remove

        Returns:
            True if policy was removed

        Example:
            ```python
            if guardrail.remove_policy("legal"):
                print("Legal policy removed")
            ```
        """
        if policy_id in self.policies:
            del self.policies[policy_id]
            logger.debug(f"Removed policy: {policy_id}")
            return True
        return False

    async def evaluate(
        self,
        content: str,
        policy: Policy,
        security_context: SecurityContext,
    ) -> GuardrailResult:
        """
        Evaluate content against a specific policy.

        Args:
            content: Content to evaluate
            policy: Policy to evaluate against
            security_context: Security context

        Returns:
            GuardrailResult with policy evaluation

        Example:
            ```python
            result = await guardrail.evaluate(
                content=user_message,
                policy=legal_policy,
                security_context=ctx,
            )
            ```
        """
        ctx = {"policy_override": policy}
        return await self.check(content, ctx, security_context)

    async def _check_impl(
        self,
        content: str,
        context: dict[str, Any],
        security_context: SecurityContext,
    ) -> GuardrailResult:
        """Evaluate content against all policies."""
        violations: list[Violation] = []
        max_severity = RiskLevel.NONE
        action = GuardrailAction.ALLOW

        # Get policies to evaluate
        policy_override = context.get("policy_override")
        policies_to_check = (
            [policy_override]
            if policy_override
            else sorted(self.policies.values(), key=lambda p: -p.priority)
        )

        for policy in policies_to_check:
            if not policy.enabled:
                continue

            for rule in policy.rules:
                violation = await rule.evaluate(content)
                if violation:
                    violations.append(violation)

                    max_severity = max(max_severity, violation.severity)

                    # Escalate action if needed
                    action_priority = {
                        GuardrailAction.ALLOW: 0,
                        GuardrailAction.WARN: 1,
                        GuardrailAction.MODIFY: 2,
                        GuardrailAction.ESCALATE: 3,
                        GuardrailAction.BLOCK: 4,
                    }
                    if action_priority.get(rule.action, 0) > action_priority.get(action, 0):
                        action = rule.action

        if violations:
            return self._create_fail_result(
                violations=violations,
                action=action,
                risk_level=max_severity,
                policies_evaluated=len(policies_to_check),
            )

        return self._create_pass_result(
            policies_evaluated=len(policies_to_check),
        )


class SemanticPolicyGuardrail(PolicyGuardrail):
    """
    Policy guardrail with semantic understanding.

    Extends PolicyGuardrail with semantic similarity matching
    for more flexible rule evaluation.

    Attributes:
        semantic_threshold: Similarity threshold for matching

    Example:
        ```python
        guardrail = SemanticPolicyGuardrail(
            semantic_threshold=0.8,
        )

        # Add semantic rules
        policy = Policy(
            policy_id="sentiment_policy",
            name="Sentiment Policy",
            rules=[
                SemanticRule(
                    rule_id="no_negative_sentiment",
                    reference_text="I hate this product, it's terrible",
                    action=GuardrailAction.WARN,
                    message="Avoid negative sentiment",
                ),
            ],
        )
        ```
    """

    def __init__(
        self,
        semantic_threshold: float = 0.8,
        policies: list[Policy] | None = None,
        guardrail_id: str | None = None,
        priority: int = 45,
        enabled: bool = True,
        config: GuardrailConfig | None = None,
    ) -> None:
        """
        Initialize the semantic policy guardrail.

        Args:
            semantic_threshold: Similarity threshold
            policies: Initial policies
            guardrail_id: Unique identifier
            priority: Execution priority
            enabled: Whether guardrail is active
            config: Guardrail configuration
        """
        super().__init__(
            policies=policies,
            guardrail_id=guardrail_id or "semantic_policy_guardrail",
            priority=priority,
            enabled=enabled,
            config=config,
        )
        self.semantic_threshold = semantic_threshold

    async def _check_semantic_similarity(
        self,
        content: str,
        reference: str,
    ) -> float:
        """
        Calculate semantic similarity between content and reference.

        This is a simplified implementation using word overlap.
        In production, use embeddings and cosine similarity.

        Args:
            content: Content to check
            reference: Reference text

        Returns:
            Similarity score (0.0-1.0)
        """
        # Simplified word overlap similarity
        content_words = set(re.findall(r"\w+", content.lower()))
        reference_words = set(re.findall(r"\w+", reference.lower()))

        if not content_words or not reference_words:
            return 0.0

        intersection = content_words & reference_words
        union = content_words | reference_words

        return len(intersection) / len(union) if union else 0.0


@dataclass
class ConditionalPolicy:
    """
    Policy that is conditionally applied based on context.

    Attributes:
        policy: The policy to apply
        condition: Condition for application
        context_key: Key to check in context

    Example:
        ```python
        conditional = ConditionalPolicy(
            policy=strict_policy,
            condition=lambda ctx: ctx.get("channel") == "public",
            context_key="channel",
        )
        ```
    """

    policy: Policy
    condition: Callable[[dict[str, Any]], bool]
    context_key: str | None = None


class ConditionalPolicyGuardrail(PolicyGuardrail):
    """
    Policy guardrail with conditional policy application.

    Applies different policies based on context conditions.

    Example:
        ```python
        guardrail = ConditionalPolicyGuardrail()

        # Add conditional policy
        guardrail.add_conditional_policy(
            policy=strict_policy,
            condition=lambda ctx: ctx.get("user_type") == "external",
        )

        # Evaluate with context
        result = await guardrail.check(
            content=message,
            context={"user_type": "external"},
            security_context=ctx,
        )
        ```
    """

    def __init__(
        self,
        guardrail_id: str | None = None,
        priority: int = 42,
        enabled: bool = True,
        config: GuardrailConfig | None = None,
    ) -> None:
        """
        Initialize the conditional policy guardrail.

        Args:
            guardrail_id: Unique identifier
            priority: Execution priority
            enabled: Whether guardrail is active
            config: Guardrail configuration
        """
        super().__init__(
            guardrail_id=guardrail_id or "conditional_policy_guardrail",
            priority=priority,
            enabled=enabled,
            config=config,
        )
        self.conditional_policies: list[ConditionalPolicy] = []

    def add_conditional_policy(
        self,
        policy: Policy,
        condition: Callable[[dict[str, Any]], bool],
    ) -> None:
        """
        Add a conditional policy.

        Args:
            policy: Policy to add
            condition: Condition for application

        Example:
            ```python
            guardrail.add_conditional_policy(
                policy=premium_policy,
                condition=lambda ctx: ctx.get("tier") == "premium",
            )
            ```
        """
        self.conditional_policies.append(ConditionalPolicy(policy=policy, condition=condition))

    async def _check_impl(
        self,
        content: str,
        context: dict[str, Any],
        security_context: SecurityContext,
    ) -> GuardrailResult:
        """Evaluate content against applicable conditional policies."""
        # Find applicable policies based on conditions
        applicable_policies: list[Policy] = []

        for conditional in self.conditional_policies:
            try:
                if conditional.condition(context):
                    applicable_policies.append(conditional.policy)
            except (TypeError, ValueError, RuntimeError, KeyError, AttributeError) as e:
                logger.warning(f"Condition evaluation failed: {e}")

        # Also include regular policies
        applicable_policies.extend(self.policies.values())

        if not applicable_policies:
            return self._create_pass_result(no_applicable_policies=True)

        # Evaluate against all applicable policies
        violations: list[Violation] = []
        max_severity = RiskLevel.NONE
        action = GuardrailAction.ALLOW

        for policy in applicable_policies:
            if not policy.enabled:
                continue

            for rule in policy.rules:
                violation = await rule.evaluate(content)
                if violation:
                    violations.append(violation)

                    max_severity = max(max_severity, violation.severity)

                    action_priority = {
                        GuardrailAction.ALLOW: 0,
                        GuardrailAction.WARN: 1,
                        GuardrailAction.MODIFY: 2,
                        GuardrailAction.ESCALATE: 3,
                        GuardrailAction.BLOCK: 4,
                    }
                    if action_priority.get(rule.action, 0) > action_priority.get(action, 0):
                        action = rule.action

        if violations:
            return self._create_fail_result(
                violations=violations,
                action=action,
                risk_level=max_severity,
                applicable_policies=[p.policy_id for p in applicable_policies],
            )

        return self._create_pass_result(
            applicable_policies=[p.policy_id for p in applicable_policies],
        )
