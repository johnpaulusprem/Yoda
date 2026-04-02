"""
Content moderation guardrails.

This module provides guardrails for content moderation with support
for external moderation APIs and configurable filtering.

Example:
    ```python
    from yoda_foundation.guardrails.moderation import (
        ModerationGuardrail,
        ModerationResult,
        ContentFilter,
    )

    # Create moderation guardrail
    guardrail = ModerationGuardrail(
        provider="internal",
        thresholds={
            ContentCategory.HATE_SPEECH: 0.7,
            ContentCategory.VIOLENCE: 0.8,
        },
    )

    # Moderate content
    result = await guardrail.moderate(
        content="User message here",
        security_context=ctx,
    )

    if not result.safe:
        handle_flagged_content(result)
    ```
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from yoda_foundation.guardrails.base import InputGuardrail, OutputGuardrail
from yoda_foundation.guardrails.schemas import (
    ContentCategory,
    GuardrailAction,
    GuardrailConfig,
    GuardrailResult,
    ModerationResult,
    RiskLevel,
    Violation,
)
from yoda_foundation.security.context import SecurityContext
from yoda_foundation.observability.logging import get_logger


logger = get_logger(__name__)


# Type for pre/post processing hooks
ProcessingHook = Callable[[str, dict[str, Any]], Awaitable[str]]


@dataclass
class ContentFilterConfig:
    """
    Configuration for content filtering.

    Attributes:
        enabled_categories: Categories to filter
        thresholds: Category-specific thresholds
        action_on_flag: Action when content is flagged
        redact_flagged: Whether to redact flagged content
        log_flagged: Whether to log flagged content

    Example:
        ```python
        config = ContentFilterConfig(
            enabled_categories=[
                ContentCategory.HATE_SPEECH,
                ContentCategory.VIOLENCE,
            ],
            thresholds={
                ContentCategory.HATE_SPEECH: 0.7,
                ContentCategory.VIOLENCE: 0.8,
            },
            action_on_flag=GuardrailAction.BLOCK,
        )
        ```
    """

    enabled_categories: list[ContentCategory] = field(
        default_factory=lambda: [
            ContentCategory.HATE_SPEECH,
            ContentCategory.VIOLENCE,
            ContentCategory.SEXUAL,
            ContentCategory.SELF_HARM,
            ContentCategory.DANGEROUS,
        ]
    )
    thresholds: dict[ContentCategory, float] = field(default_factory=dict)
    action_on_flag: GuardrailAction = GuardrailAction.BLOCK
    redact_flagged: bool = False
    log_flagged: bool = True

    def get_threshold(self, category: ContentCategory) -> float:
        """Get threshold for a category (default 0.5)."""
        return self.thresholds.get(category, 0.5)


class ContentFilter:
    """
    Configurable content filter.

    Filters content based on configurable rules and thresholds.

    Attributes:
        config: Filter configuration

    Example:
        ```python
        filter = ContentFilter(config=filter_config)

        result = await filter.filter_content(
            content="Some potentially harmful content",
            security_context=ctx,
        )

        if not result.safe:
            print(f"Content flagged: {result.highest_risk_category}")
        ```
    """

    # Internal scoring patterns
    CATEGORY_PATTERNS: dict[ContentCategory, list[tuple[str, float]]] = {
        ContentCategory.HATE_SPEECH: [
            (r"\b(hate|despise)\s+(all\s+)?\w+\b", 0.8),
            (r"\b\w+\s+(are\s+)?inferior\b", 0.7),
            (r"\b(discriminat|racist|bigot)\w*\b", 0.6),
        ],
        ContentCategory.VIOLENCE: [
            (r"\b(kill|murder|attack|hurt)\s+\w+\b", 0.8),
            (r"\b(bomb|weapon|gun)\s+(making|instructions)\b", 0.9),
            (r"\b(violent|brutal|savage)\b", 0.5),
        ],
        ContentCategory.SEXUAL: [
            (r"\b(nude|naked|explicit)\b", 0.7),
            (r"\b(sexual|erotic|pornograph)\w*\b", 0.8),
        ],
        ContentCategory.SELF_HARM: [
            (r"\b(suicide|self-harm|cut\s+myself)\b", 0.9),
            (r"\bhow\s+to\s+kill\s+(myself|yourself)\b", 0.95),
            (r"\bwant\s+to\s+die\b", 0.8),
        ],
        ContentCategory.DANGEROUS: [
            (r"\bhow\s+to\s+(make|build)\s+(a\s+)?(bomb|weapon|drug)\b", 0.95),
            (r"\b(illegal|dangerous)\s+activities?\b", 0.6),
        ],
    }

    def __init__(self, config: ContentFilterConfig | None = None) -> None:
        """
        Initialize the content filter.

        Args:
            config: Filter configuration
        """
        self.config = config or ContentFilterConfig()
        self._compiled_patterns: dict[ContentCategory, list[tuple[re.Pattern, float]]] = {}
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Compile patterns for enabled categories."""
        for category in self.config.enabled_categories:
            patterns = self.CATEGORY_PATTERNS.get(category, [])
            compiled = []
            for pattern, score in patterns:
                compiled.append((re.compile(pattern, re.IGNORECASE), score))
            self._compiled_patterns[category] = compiled

    async def filter_content(
        self,
        content: str,
        security_context: SecurityContext,
    ) -> ModerationResult:
        """
        Filter content and return moderation result.

        Args:
            content: Content to filter
            security_context: Security context

        Returns:
            ModerationResult with filtering details
        """
        scores: dict[ContentCategory, float] = {}
        highest_category: ContentCategory | None = None
        highest_score = 0.0

        for category, patterns in self._compiled_patterns.items():
            category_score = 0.0

            for pattern, base_score in patterns:
                matches = pattern.findall(content)
                if matches:
                    # Aggregate score from matches
                    match_score = base_score * min(len(matches), 3) / 3
                    category_score = max(category_score, match_score)

            scores[category] = category_score

            if category_score > highest_score:
                highest_score = category_score
                highest_category = category

        # Determine if content is safe based on thresholds
        safe = True
        action = GuardrailAction.ALLOW

        for category, score in scores.items():
            threshold = self.config.get_threshold(category)
            if score >= threshold:
                safe = False
                action = self.config.action_on_flag
                break

        if self.config.log_flagged and not safe:
            logger.warning(
                "Content flagged by filter",
                category=highest_category.value if highest_category else None,
                score=highest_score,
            )

        return ModerationResult(
            safe=safe,
            categories=scores,
            highest_risk_category=highest_category,
            highest_risk_score=highest_score,
            action=action,
        )


class ModerationGuardrail(InputGuardrail):
    """
    Comprehensive content moderation guardrail.

    Provides full content moderation with support for internal
    pattern matching or external API integration.

    Attributes:
        provider: Moderation provider ("internal" or "openai")
        thresholds: Category-specific thresholds
        content_filter: Internal content filter

    Example:
        ```python
        guardrail = ModerationGuardrail(
            provider="internal",
            thresholds={
                ContentCategory.HATE_SPEECH: 0.7,
            },
        )

        result = await guardrail.moderate(
            content="Content to moderate",
            security_context=ctx,
        )
        ```
    """

    def __init__(
        self,
        provider: str = "internal",
        thresholds: dict[ContentCategory, float] | None = None,
        pre_processors: list[ProcessingHook] | None = None,
        post_processors: list[ProcessingHook] | None = None,
        guardrail_id: str | None = None,
        priority: int = 5,
        enabled: bool = True,
        config: GuardrailConfig | None = None,
    ) -> None:
        """
        Initialize the moderation guardrail.

        Args:
            provider: Moderation provider
            thresholds: Category thresholds
            pre_processors: Pre-processing hooks
            post_processors: Post-processing hooks
            guardrail_id: Unique identifier
            priority: Execution priority
            enabled: Whether guardrail is active
            config: Guardrail configuration
        """
        super().__init__(
            guardrail_id=guardrail_id or "moderation_guardrail",
            priority=priority,
            enabled=enabled,
            config=config,
        )
        self.provider = provider
        self.thresholds = thresholds or {}
        self.pre_processors = pre_processors or []
        self.post_processors = post_processors or []

        # Initialize content filter
        filter_config = ContentFilterConfig(thresholds=self.thresholds)
        self.content_filter = ContentFilter(config=filter_config)

    async def moderate(
        self,
        content: str,
        security_context: SecurityContext,
    ) -> ModerationResult:
        """
        Moderate content and return detailed result.

        Args:
            content: Content to moderate
            security_context: Security context

        Returns:
            ModerationResult with moderation details

        Example:
            ```python
            result = await guardrail.moderate(
                content=user_message,
                security_context=ctx,
            )

            if not result.safe:
                return block_response(result.highest_risk_category)
            ```
        """
        # Apply pre-processors
        processed_content = content
        for processor in self.pre_processors:
            processed_content = await processor(processed_content, {})

        # Perform moderation
        if self.provider == "internal":
            result = await self.content_filter.filter_content(processed_content, security_context)
        else:
            # External API moderation would go here
            result = await self._external_moderation(processed_content, security_context)

        return result

    async def _external_moderation(
        self,
        content: str,
        security_context: SecurityContext,
    ) -> ModerationResult:
        """
        Perform moderation using external API.

        This is a placeholder for external API integration.

        Args:
            content: Content to moderate
            security_context: Security context

        Returns:
            ModerationResult from external API
        """
        # Placeholder for external API integration
        # In production, integrate with OpenAI, Perspective, etc.
        logger.warning("External moderation not configured, using internal")
        return await self.content_filter.filter_content(content, security_context)

    async def _check_impl(
        self,
        content: str,
        context: dict[str, Any],
        security_context: SecurityContext,
    ) -> GuardrailResult:
        """Check content through moderation."""
        moderation_result = await self.moderate(content, security_context)

        if not moderation_result.safe:
            violations: list[Violation] = []

            for category, score in moderation_result.categories.items():
                threshold = self.thresholds.get(category, 0.5)
                if score >= threshold:
                    violations.append(
                        self._create_violation(
                            rule_id=f"moderation_{category.value}",
                            rule_name=f"Moderation: {category.value}",
                            severity=self._score_to_severity(score),
                            description=f"Content flagged for {category.value}",
                            category=category,
                            score=score,
                            threshold=threshold,
                        )
                    )

            return self._create_fail_result(
                violations=violations,
                action=moderation_result.action,
                risk_level=self._score_to_severity(moderation_result.highest_risk_score),
                moderation_result=moderation_result.to_dict(),
            )

        return self._create_pass_result(
            moderation_result=moderation_result.to_dict(),
        )

    def _score_to_severity(self, score: float) -> RiskLevel:
        """Convert moderation score to risk level."""
        if score >= 0.9:
            return RiskLevel.CRITICAL
        elif score >= 0.7:
            return RiskLevel.HIGH
        elif score >= 0.5:
            return RiskLevel.MEDIUM
        elif score >= 0.3:
            return RiskLevel.LOW
        return RiskLevel.NONE


class OutputModerationGuardrail(OutputGuardrail):
    """
    Moderation guardrail specifically for output filtering.

    Moderates LLM output before it's returned to users.

    Example:
        ```python
        guardrail = OutputModerationGuardrail()

        result = await guardrail.check(
            content=llm_response,
            security_context=ctx,
        )

        if result.action == GuardrailAction.MODIFY:
            use_content = result.modified_content
        ```
    """

    def __init__(
        self,
        thresholds: dict[ContentCategory, float] | None = None,
        auto_redact: bool = False,
        guardrail_id: str | None = None,
        priority: int = 10,
        enabled: bool = True,
        config: GuardrailConfig | None = None,
    ) -> None:
        """
        Initialize the output moderation guardrail.

        Args:
            thresholds: Category thresholds
            auto_redact: Automatically redact flagged content
            guardrail_id: Unique identifier
            priority: Execution priority
            enabled: Whether guardrail is active
            config: Guardrail configuration
        """
        super().__init__(
            guardrail_id=guardrail_id or "output_moderation_guardrail",
            priority=priority,
            enabled=enabled,
            config=config,
        )
        self.thresholds = thresholds or {}
        self.auto_redact = auto_redact

        filter_config = ContentFilterConfig(
            thresholds=self.thresholds,
            redact_flagged=auto_redact,
        )
        self.content_filter = ContentFilter(config=filter_config)

    async def _check_impl(
        self,
        content: str,
        context: dict[str, Any],
        security_context: SecurityContext,
    ) -> GuardrailResult:
        """Check output content through moderation."""
        result = await self.content_filter.filter_content(content, security_context)

        if not result.safe:
            violations: list[Violation] = []

            for category, score in result.categories.items():
                threshold = self.thresholds.get(category, 0.5)
                if score >= threshold:
                    violations.append(
                        self._create_violation(
                            rule_id=f"output_moderation_{category.value}",
                            rule_name=f"Output Moderation: {category.value}",
                            severity=RiskLevel.HIGH if score >= 0.7 else RiskLevel.MEDIUM,
                            description=f"Output content flagged for {category.value}",
                            category=category,
                        )
                    )

            action = GuardrailAction.MODIFY if self.auto_redact else GuardrailAction.BLOCK

            modified_content = None
            if self.auto_redact:
                modified_content = self._redact_content(content, result)

            return self._create_fail_result(
                violations=violations,
                action=action,
                modified_content=modified_content,
            )

        return self._create_pass_result()

    def _redact_content(
        self,
        content: str,
        result: ModerationResult,
    ) -> str:
        """
        Redact flagged content.

        Args:
            content: Original content
            result: Moderation result

        Returns:
            Redacted content
        """
        # Simple redaction - in production, use more sophisticated approach
        redacted = content

        for category in result.categories.keys():
            patterns = self.content_filter._compiled_patterns.get(category, [])
            for pattern, _ in patterns:
                redacted = pattern.sub("[REDACTED]", redacted)

        return redacted
