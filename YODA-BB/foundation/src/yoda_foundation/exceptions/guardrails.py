"""
Guardrail-specific exceptions for the Agentic AI Component Library.

This module defines exceptions raised by the guardrails system
for content blocking, policy violations, and other guardrail failures.

Example:
    ```python
    from yoda_foundation.exceptions.guardrails import (
        GuardrailError,
        ContentBlockedError,
        JailbreakDetectedError,
        PolicyViolationError,
    )

    try:
        result = await guardrail.check(content, security_context)
        if not result.passed:
            raise ContentBlockedError(
                message="Content violates safety policies",
                violations=result.violations,
            )
    except ContentBlockedError as e:
        logger.warning(f"Blocked: {e.error_id}", extra=e.to_log_dict())
        return error_response(e.user_message)
    ```
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from yoda_foundation.exceptions.base import (
    AgenticBaseException,
    ErrorCategory,
    ErrorSeverity,
)


if TYPE_CHECKING:
    from yoda_foundation.guardrails.schemas import (
        GuardrailAction,
        RiskLevel,
        Violation,
    )


class GuardrailError(AgenticBaseException):
    """
    Base exception for guardrail errors.

    All guardrail-specific exceptions inherit from this class.

    Attributes:
        guardrail_id: ID of the guardrail that raised the error
        guardrail_type: Type of guardrail

    Example:
        ```python
        raise GuardrailError(
            message="Guardrail check failed",
            guardrail_id="toxicity_guardrail",
            retryable=False,
        )
        ```
    """

    def __init__(
        self,
        message: str,
        *,
        guardrail_id: str | None = None,
        guardrail_type: str | None = None,
        error_id: str | None = None,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        retryable: bool = False,
        user_message: str | None = None,
        suggestions: list[str] | None = None,
        cause: Exception | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize the guardrail error.

        Args:
            message: Error message
            guardrail_id: ID of the guardrail
            guardrail_type: Type of guardrail
            error_id: Unique error ID
            severity: Error severity
            retryable: Whether operation is retryable
            user_message: User-safe message
            suggestions: Remediation suggestions
            cause: Original exception
            details: Additional details
        """
        super().__init__(
            message=message,
            error_id=error_id,
            category=ErrorCategory.VALIDATION,
            severity=severity,
            retryable=retryable,
            user_message=user_message
            or "Your request could not be processed due to content policy.",
            suggestions=suggestions or ["Review content guidelines", "Modify your request"],
            cause=cause,
            details=details or {},
        )

        self.guardrail_id = guardrail_id
        self.guardrail_type = guardrail_type

        # Add to details
        if guardrail_id:
            self.details["guardrail_id"] = guardrail_id
        if guardrail_type:
            self.details["guardrail_type"] = guardrail_type


class ContentBlockedError(GuardrailError):
    """
    Exception raised when content is blocked by guardrails.

    Attributes:
        violations: List of violations that caused the block
        risk_level: Overall risk level
        action: Action taken by guardrail

    Example:
        ```python
        from yoda_foundation.guardrails.schemas import Violation, RiskLevel

        raise ContentBlockedError(
            message="Content blocked due to safety violations",
            violations=[
                Violation(
                    rule_id="toxicity_001",
                    rule_name="Toxicity Detection",
                    severity=RiskLevel.HIGH,
                    description="Toxic content detected",
                )
            ],
        )
        ```
    """

    def __init__(
        self,
        message: str,
        *,
        violations: list[Violation] | None = None,
        risk_level: RiskLevel | None = None,
        action: GuardrailAction | None = None,
        guardrail_id: str | None = None,
        error_id: str | None = None,
        user_message: str | None = None,
        suggestions: list[str] | None = None,
        cause: Exception | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize the content blocked error.

        Args:
            message: Error message
            violations: List of violations
            risk_level: Risk level
            action: Guardrail action taken
            guardrail_id: Guardrail ID
            error_id: Unique error ID
            user_message: User-safe message
            suggestions: Remediation suggestions
            cause: Original exception
            details: Additional details
        """
        super().__init__(
            message=message,
            guardrail_id=guardrail_id,
            error_id=error_id,
            severity=ErrorSeverity.HIGH,
            retryable=False,
            user_message=user_message
            or "Your content could not be processed as it violates our content policy.",
            suggestions=suggestions
            or [
                "Review our content guidelines",
                "Remove any potentially harmful content",
                "Rephrase your request",
            ],
            cause=cause,
            details=details or {},
        )

        self.violations = violations or []
        self.risk_level = risk_level
        self.action = action

        # Add violation info to details
        if self.violations:
            self.details["violation_count"] = len(self.violations)
            self.details["violation_summaries"] = [
                {
                    "rule_id": v.rule_id,
                    "rule_name": v.rule_name,
                    "severity": v.severity.value
                    if hasattr(v.severity, "value")
                    else str(v.severity),
                }
                for v in self.violations[:5]  # Limit for log size
            ]

        if risk_level:
            self.details["risk_level"] = (
                risk_level.value if hasattr(risk_level, "value") else str(risk_level)
            )
        if action:
            self.details["action"] = action.value if hasattr(action, "value") else str(action)


class JailbreakDetectedError(GuardrailError):
    """
    Exception raised when a jailbreak attempt is detected.

    Attributes:
        jailbreak_type: Type of jailbreak detected
        confidence: Detection confidence score

    Example:
        ```python
        raise JailbreakDetectedError(
            message="Jailbreak attempt detected",
            jailbreak_type="instruction_override",
            confidence=0.95,
        )
        ```
    """

    def __init__(
        self,
        message: str,
        *,
        jailbreak_type: str | None = None,
        confidence: float | None = None,
        violations: list[Violation] | None = None,
        guardrail_id: str | None = None,
        error_id: str | None = None,
        user_message: str | None = None,
        suggestions: list[str] | None = None,
        cause: Exception | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize the jailbreak detected error.

        Args:
            message: Error message
            jailbreak_type: Type of jailbreak
            confidence: Detection confidence
            violations: List of violations
            guardrail_id: Guardrail ID
            error_id: Unique error ID
            user_message: User-safe message
            suggestions: Remediation suggestions
            cause: Original exception
            details: Additional details
        """
        super().__init__(
            message=message,
            guardrail_id=guardrail_id or "jailbreak_detector",
            guardrail_type="jailbreak",
            error_id=error_id,
            severity=ErrorSeverity.CRITICAL,
            retryable=False,
            user_message=user_message or "Your request appears to violate our usage policies.",
            suggestions=suggestions
            or [
                "Please use the system as intended",
                "Review our acceptable use policy",
            ],
            cause=cause,
            details=details or {},
        )

        self.jailbreak_type = jailbreak_type
        self.confidence = confidence
        self.violations = violations or []

        if jailbreak_type:
            self.details["jailbreak_type"] = jailbreak_type
        if confidence is not None:
            self.details["confidence"] = confidence


class PolicyViolationError(GuardrailError):
    """
    Exception raised when content violates a policy.

    Attributes:
        policy_id: ID of violated policy
        policy_name: Name of violated policy
        violated_rules: List of violated rule IDs

    Example:
        ```python
        raise PolicyViolationError(
            message="Content violates competitor mention policy",
            policy_id="competitor_policy",
            policy_name="Competitor Mention Policy",
            violated_rules=["no_competitor_names"],
        )
        ```
    """

    def __init__(
        self,
        message: str,
        *,
        policy_id: str | None = None,
        policy_name: str | None = None,
        violated_rules: list[str] | None = None,
        violations: list[Violation] | None = None,
        guardrail_id: str | None = None,
        error_id: str | None = None,
        user_message: str | None = None,
        suggestions: list[str] | None = None,
        cause: Exception | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize the policy violation error.

        Args:
            message: Error message
            policy_id: ID of violated policy
            policy_name: Name of violated policy
            violated_rules: List of violated rules
            violations: List of violations
            guardrail_id: Guardrail ID
            error_id: Unique error ID
            user_message: User-safe message
            suggestions: Remediation suggestions
            cause: Original exception
            details: Additional details
        """
        super().__init__(
            message=message,
            guardrail_id=guardrail_id or "policy_guardrail",
            guardrail_type="policy",
            error_id=error_id,
            severity=ErrorSeverity.MEDIUM,
            retryable=False,
            user_message=user_message or "Your content violates our content policy.",
            suggestions=suggestions
            or [
                "Review the content policy",
                "Modify content to comply with guidelines",
            ],
            cause=cause,
            details=details or {},
        )

        self.policy_id = policy_id
        self.policy_name = policy_name
        self.violated_rules = violated_rules or []
        self.violations = violations or []

        if policy_id:
            self.details["policy_id"] = policy_id
        if policy_name:
            self.details["policy_name"] = policy_name
        if violated_rules:
            self.details["violated_rules"] = violated_rules


class TopicViolationError(GuardrailError):
    """
    Exception raised when content is off-topic.

    Attributes:
        detected_topic: Topic detected in content
        allowed_topics: List of allowed topics

    Example:
        ```python
        raise TopicViolationError(
            message="Content is off-topic",
            detected_topic="weather",
            allowed_topics=["customer_support", "billing"],
        )
        ```
    """

    def __init__(
        self,
        message: str,
        *,
        detected_topic: str | None = None,
        allowed_topics: list[str] | None = None,
        guardrail_id: str | None = None,
        error_id: str | None = None,
        user_message: str | None = None,
        suggestions: list[str] | None = None,
        cause: Exception | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize the topic violation error.

        Args:
            message: Error message
            detected_topic: Detected topic
            allowed_topics: Allowed topics
            guardrail_id: Guardrail ID
            error_id: Unique error ID
            user_message: User-safe message
            suggestions: Remediation suggestions
            cause: Original exception
            details: Additional details
        """
        super().__init__(
            message=message,
            guardrail_id=guardrail_id or "topic_guardrail",
            guardrail_type="topic",
            error_id=error_id,
            severity=ErrorSeverity.LOW,
            retryable=True,
            user_message=user_message
            or "I can only help with specific topics. Let me redirect you.",
            suggestions=suggestions
            or [
                "Please ask about a supported topic",
                f"Supported topics: {', '.join(allowed_topics or [])}",
            ],
            cause=cause,
            details=details or {},
        )

        self.detected_topic = detected_topic
        self.allowed_topics = allowed_topics or []

        if detected_topic:
            self.details["detected_topic"] = detected_topic
        if allowed_topics:
            self.details["allowed_topics"] = allowed_topics


class FactCheckError(GuardrailError):
    """
    Exception raised when fact-checking fails.

    Attributes:
        unsupported_claims: Claims not supported by sources
        contradicted_claims: Claims contradicted by sources

    Example:
        ```python
        raise FactCheckError(
            message="Response contains unverified claims",
            unsupported_claims=["The company was founded in 2010"],
            contradicted_claims=[],
        )
        ```
    """

    def __init__(
        self,
        message: str,
        *,
        unsupported_claims: list[str] | None = None,
        contradicted_claims: list[str] | None = None,
        guardrail_id: str | None = None,
        error_id: str | None = None,
        user_message: str | None = None,
        suggestions: list[str] | None = None,
        cause: Exception | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize the fact check error.

        Args:
            message: Error message
            unsupported_claims: Unsupported claims
            contradicted_claims: Contradicted claims
            guardrail_id: Guardrail ID
            error_id: Unique error ID
            user_message: User-safe message
            suggestions: Remediation suggestions
            cause: Original exception
            details: Additional details
        """
        super().__init__(
            message=message,
            guardrail_id=guardrail_id or "fact_check_guardrail",
            guardrail_type="fact_check",
            error_id=error_id,
            severity=ErrorSeverity.MEDIUM,
            retryable=True,
            user_message=user_message or "I could not verify some information. Let me try again.",
            suggestions=suggestions
            or [
                "Provide more context or sources",
                "Ask for clarification on specific claims",
            ],
            cause=cause,
            details=details or {},
        )

        self.unsupported_claims = unsupported_claims or []
        self.contradicted_claims = contradicted_claims or []

        if unsupported_claims:
            self.details["unsupported_claims"] = unsupported_claims
        if contradicted_claims:
            self.details["contradicted_claims"] = contradicted_claims


class ModerationError(GuardrailError):
    """
    Exception raised when content fails moderation.

    Attributes:
        flagged_categories: Categories that flagged the content
        highest_score: Highest moderation score

    Example:
        ```python
        raise ModerationError(
            message="Content failed moderation",
            flagged_categories=["violence", "hate_speech"],
            highest_score=0.85,
        )
        ```
    """

    def __init__(
        self,
        message: str,
        *,
        flagged_categories: list[str] | None = None,
        highest_score: float | None = None,
        guardrail_id: str | None = None,
        error_id: str | None = None,
        user_message: str | None = None,
        suggestions: list[str] | None = None,
        cause: Exception | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize the moderation error.

        Args:
            message: Error message
            flagged_categories: Flagged categories
            highest_score: Highest score
            guardrail_id: Guardrail ID
            error_id: Unique error ID
            user_message: User-safe message
            suggestions: Remediation suggestions
            cause: Original exception
            details: Additional details
        """
        super().__init__(
            message=message,
            guardrail_id=guardrail_id or "moderation_guardrail",
            guardrail_type="moderation",
            error_id=error_id,
            severity=ErrorSeverity.HIGH,
            retryable=False,
            user_message=user_message
            or "Your content could not be processed due to content moderation policies.",
            suggestions=suggestions
            or [
                "Remove potentially harmful content",
                "Review content guidelines",
            ],
            cause=cause,
            details=details or {},
        )

        self.flagged_categories = flagged_categories or []
        self.highest_score = highest_score

        if flagged_categories:
            self.details["flagged_categories"] = flagged_categories
        if highest_score is not None:
            self.details["highest_score"] = highest_score


class GuardrailTimeoutError(GuardrailError):
    """
    Exception raised when guardrail check times out.

    Example:
        ```python
        raise GuardrailTimeoutError(
            message="Guardrail check timed out",
            timeout_seconds=30.0,
        )
        ```
    """

    def __init__(
        self,
        message: str,
        *,
        timeout_seconds: float | None = None,
        guardrail_id: str | None = None,
        error_id: str | None = None,
        user_message: str | None = None,
        suggestions: list[str] | None = None,
        cause: Exception | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize the guardrail timeout error.

        Args:
            message: Error message
            timeout_seconds: Timeout duration
            guardrail_id: Guardrail ID
            error_id: Unique error ID
            user_message: User-safe message
            suggestions: Remediation suggestions
            cause: Original exception
            details: Additional details
        """
        super().__init__(
            message=message,
            guardrail_id=guardrail_id,
            error_id=error_id,
            severity=ErrorSeverity.MEDIUM,
            retryable=True,
            user_message=user_message or "Request processing took too long. Please try again.",
            suggestions=suggestions
            or [
                "Try with a shorter input",
                "Wait and try again",
            ],
            cause=cause,
            details=details or {},
        )

        self.timeout_seconds = timeout_seconds

        if timeout_seconds is not None:
            self.details["timeout_seconds"] = timeout_seconds
