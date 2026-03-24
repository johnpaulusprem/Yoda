"""
Topic adherence guardrails for the Agentic AI Component Library.

This module provides guardrails for ensuring conversations stay on-topic
and within defined boundaries.

Example:
    ```python
    from yoda_foundation.guardrails.topic import (
        TopicGuardrail,
        OffTopicAction,
    )

    # Create topic guardrail
    guardrail = TopicGuardrail(
        allowed_topics=["customer_support", "product_info", "billing"],
        off_topic_action=OffTopicAction.REDIRECT,
    )

    # Check if content is on-topic
    result = await guardrail.check_on_topic(
        content="What's the weather like today?",
        allowed_topics=["customer_support"],
        security_context=ctx,
    )

    if not result.passed:
        # Redirect to on-topic response
        return redirect_response(result.metadata.get("suggested_topic"))
    ```
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from yoda_foundation.guardrails.base import DialogGuardrail, InputGuardrail
from yoda_foundation.guardrails.schemas import (
    ContentCategory,
    DialogContext,
    GuardrailAction,
    GuardrailConfig,
    GuardrailResult,
    RiskLevel,
)
from yoda_foundation.security.context import SecurityContext
from yoda_foundation.observability.logging import get_logger


logger = get_logger(__name__)


class OffTopicAction(Enum):
    """
    Actions to take when content is off-topic.

    Attributes:
        REDIRECT: Redirect to an on-topic response
        BLOCK: Block the off-topic content
        WARN: Allow but issue a warning
        ALLOW: Allow the off-topic content
    """

    REDIRECT = "redirect"
    BLOCK = "block"
    WARN = "warn"
    ALLOW = "allow"


@dataclass
class TopicDefinition:
    r"""
    Definition of an allowed topic.

    Attributes:
        topic_id: Unique topic identifier
        name: Human-readable topic name
        description: Topic description
        keywords: Keywords associated with this topic
        patterns: Regex patterns for topic detection
        subtopics: List of subtopics
        priority: Topic priority (higher = more preferred)

    Example:
        ```python
        topic = TopicDefinition(
            topic_id="customer_support",
            name="Customer Support",
            description="Questions about product support",
            keywords=["help", "support", "issue", "problem", "question"],
            patterns=[r"how\s+do\s+i", r"can\s+you\s+help"],
        )
        ```
    """

    topic_id: str
    name: str
    description: str = ""
    keywords: list[str] = field(default_factory=list)
    patterns: list[str] = field(default_factory=list)
    subtopics: list[str] = field(default_factory=list)
    priority: int = 0


class TopicGuardrail(InputGuardrail):
    """
    Guardrail for ensuring content stays on-topic.

    Detects when conversations drift off-topic and can redirect,
    block, or warn based on configuration.

    Attributes:
        allowed_topics: List of allowed topic IDs
        off_topic_action: Action to take for off-topic content
        topic_definitions: Definitions for allowed topics
        strict_mode: Require exact topic match

    Example:
        ```python
        guardrail = TopicGuardrail(
            allowed_topics=["customer_support", "product_info"],
            off_topic_action=OffTopicAction.REDIRECT,
        )

        # Add custom topic
        guardrail.add_allowed_topic(TopicDefinition(
            topic_id="billing",
            name="Billing",
            keywords=["invoice", "payment", "charge"],
        ))

        result = await guardrail.check(content, security_context=ctx)
        ```
    """

    # Default topic definitions
    DEFAULT_TOPICS: dict[str, TopicDefinition] = {
        "customer_support": TopicDefinition(
            topic_id="customer_support",
            name="Customer Support",
            description="General customer support inquiries",
            keywords=[
                "help",
                "support",
                "issue",
                "problem",
                "question",
                "assist",
                "trouble",
                "error",
                "fix",
                "resolve",
            ],
            patterns=[
                r"how\s+(do|can)\s+i",
                r"can\s+you\s+help",
                r"i\s+(need|have)\s+(a\s+)?(question|problem|issue)",
                r"something\s+(is|isn't)\s+working",
            ],
        ),
        "product_info": TopicDefinition(
            topic_id="product_info",
            name="Product Information",
            description="Questions about products and features",
            keywords=[
                "product",
                "feature",
                "function",
                "capability",
                "specification",
                "details",
                "information",
                "what",
            ],
            patterns=[
                r"what\s+(is|are|does)",
                r"tell\s+me\s+about",
                r"information\s+(about|on)",
                r"features?\s+of",
            ],
        ),
        "billing": TopicDefinition(
            topic_id="billing",
            name="Billing & Payments",
            description="Billing, payments, and account questions",
            keywords=[
                "bill",
                "billing",
                "invoice",
                "payment",
                "charge",
                "subscription",
                "refund",
                "price",
                "cost",
                "fee",
            ],
            patterns=[
                r"how\s+much\s+(does|is)",
                r"(my|the)\s+(bill|invoice|payment)",
                r"cancel\s+(my\s+)?subscription",
                r"refund\s+(for|on)",
            ],
        ),
        "technical": TopicDefinition(
            topic_id="technical",
            name="Technical Support",
            description="Technical issues and troubleshooting",
            keywords=[
                "technical",
                "error",
                "bug",
                "crash",
                "slow",
                "performance",
                "configuration",
                "setup",
                "install",
            ],
            patterns=[
                r"(not|isn't)\s+working",
                r"error\s+(message|code)",
                r"how\s+to\s+(install|configure|setup)",
                r"(crash|freeze|hang)",
            ],
        ),
        "account": TopicDefinition(
            topic_id="account",
            name="Account Management",
            description="Account settings and management",
            keywords=[
                "account",
                "password",
                "login",
                "logout",
                "profile",
                "settings",
                "preferences",
                "update",
                "change",
            ],
            patterns=[
                r"(my|the)\s+account",
                r"(change|update|reset)\s+(my\s+)?(password|email|profile)",
                r"(can't|cannot)\s+login",
            ],
        ),
    }

    def __init__(
        self,
        allowed_topics: list[str] | None = None,
        off_topic_action: OffTopicAction = OffTopicAction.WARN,
        strict_mode: bool = False,
        guardrail_id: str | None = None,
        priority: int = 50,
        enabled: bool = True,
        config: GuardrailConfig | None = None,
    ) -> None:
        """
        Initialize the topic guardrail.

        Args:
            allowed_topics: List of allowed topic IDs
            off_topic_action: Action for off-topic content
            strict_mode: Require exact topic match
            guardrail_id: Unique identifier
            priority: Execution priority
            enabled: Whether guardrail is active
            config: Guardrail configuration
        """
        super().__init__(
            guardrail_id=guardrail_id or "topic_guardrail",
            priority=priority,
            enabled=enabled,
            config=config,
        )
        self.allowed_topics: set[str] = set(allowed_topics or [])
        self.off_topic_action = off_topic_action
        self.strict_mode = strict_mode
        self.topic_definitions: dict[str, TopicDefinition] = self.DEFAULT_TOPICS.copy()

        # Compile patterns for all topics
        self._compiled_patterns: dict[str, list[re.Pattern]] = {}
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Compile regex patterns for all topics."""
        for topic_id, topic_def in self.topic_definitions.items():
            patterns = []
            for pattern in topic_def.patterns:
                patterns.append(re.compile(pattern, re.IGNORECASE))
            self._compiled_patterns[topic_id] = patterns

    def add_allowed_topic(self, topic: TopicDefinition | str) -> None:
        """
        Add an allowed topic.

        Args:
            topic: TopicDefinition or topic ID string

        Example:
            ```python
            # Add by ID (must exist in definitions)
            guardrail.add_allowed_topic("billing")

            # Add with full definition
            guardrail.add_allowed_topic(TopicDefinition(
                topic_id="custom_topic",
                name="Custom Topic",
                keywords=["custom", "keyword"],
            ))
            ```
        """
        if isinstance(topic, str):
            self.allowed_topics.add(topic)
        else:
            self.topic_definitions[topic.topic_id] = topic
            self.allowed_topics.add(topic.topic_id)
            # Compile patterns for new topic
            patterns = []
            for pattern in topic.patterns:
                patterns.append(re.compile(pattern, re.IGNORECASE))
            self._compiled_patterns[topic.topic_id] = patterns

        logger.debug(f"Added allowed topic: {topic if isinstance(topic, str) else topic.topic_id}")

    def remove_allowed_topic(self, topic_id: str) -> bool:
        """
        Remove an allowed topic.

        Args:
            topic_id: Topic ID to remove

        Returns:
            True if topic was removed

        Example:
            ```python
            if guardrail.remove_allowed_topic("billing"):
                print("Billing topic removed")
            ```
        """
        if topic_id in self.allowed_topics:
            self.allowed_topics.remove(topic_id)
            logger.debug(f"Removed allowed topic: {topic_id}")
            return True
        return False

    async def check_on_topic(
        self,
        content: str,
        allowed_topics: list[str] | None = None,
        *,
        security_context: SecurityContext,
    ) -> GuardrailResult:
        """
        Check if content is on-topic.

        Args:
            content: Content to check
            allowed_topics: Override allowed topics
            security_context: Security context

        Returns:
            GuardrailResult with topic analysis

        Example:
            ```python
            result = await guardrail.check_on_topic(
                content="What's the weather?",
                allowed_topics=["customer_support"],
                security_context=ctx,
            )

            if not result.passed:
                print(f"Off-topic: {result.metadata.get('detected_topic')}")
            ```
        """
        topics = set(allowed_topics) if allowed_topics else self.allowed_topics
        context = {"allowed_topics_override": list(topics)}
        return await self.check(content, context, security_context)

    async def extract_topic(
        self,
        content: str,
        security_context: SecurityContext,
    ) -> str | None:
        """
        Extract the topic from content.

        Args:
            content: Content to analyze
            security_context: Security context

        Returns:
            Detected topic ID or None

        Example:
            ```python
            topic = await guardrail.extract_topic(
                content="I need help with my invoice",
                security_context=ctx,
            )
            # Returns: "billing"
            ```
        """
        scores = self._calculate_topic_scores(content)

        if scores:
            best_topic = max(scores.items(), key=lambda x: x[1])
            if best_topic[1] > 0:
                return best_topic[0]

        return None

    def _calculate_topic_scores(self, content: str) -> dict[str, float]:
        """
        Calculate topic scores for content.

        Args:
            content: Content to analyze

        Returns:
            Dictionary of topic_id -> score
        """
        scores: dict[str, float] = {}
        content_lower = content.lower()
        content_words = set(re.findall(r"\w+", content_lower))

        for topic_id, topic_def in self.topic_definitions.items():
            score = 0.0

            # Keyword matching
            keyword_matches = sum(1 for kw in topic_def.keywords if kw.lower() in content_words)
            score += keyword_matches * 0.3

            # Pattern matching
            patterns = self._compiled_patterns.get(topic_id, [])
            pattern_matches = sum(1 for p in patterns if p.search(content))
            score += pattern_matches * 0.5

            # Normalize score
            max_possible = len(topic_def.keywords) * 0.3 + len(patterns) * 0.5
            if max_possible > 0:
                score = score / max_possible

            scores[topic_id] = score

        return scores

    async def _check_impl(
        self,
        content: str,
        context: dict[str, Any],
        security_context: SecurityContext,
    ) -> GuardrailResult:
        """Check if content is on-topic."""
        # Get allowed topics (may be overridden in context)
        allowed_topics = context.get("allowed_topics_override")
        if allowed_topics is None:
            allowed_topics = self.allowed_topics

        if not allowed_topics:
            # No topic restrictions
            return self._create_pass_result(no_restrictions=True)

        # Calculate topic scores
        scores = self._calculate_topic_scores(content)

        # Find best matching topic
        best_topic = None
        best_score = 0.0

        if scores:
            best_topic, best_score = max(scores.items(), key=lambda x: x[1])

        # Check if best topic is allowed
        is_on_topic = best_topic in allowed_topics if best_topic else False

        # In strict mode, require a minimum score threshold
        if self.strict_mode and best_score < 0.3:
            is_on_topic = False

        if not is_on_topic:
            # Off-topic content detected
            action = self._off_topic_action_to_guardrail_action()

            # Find suggested topic from allowed topics
            suggested_topic = None
            suggested_score = 0.0
            for topic_id in allowed_topics:
                if topic_id in scores and scores[topic_id] > suggested_score:
                    suggested_topic = topic_id
                    suggested_score = scores[topic_id]

            violations = [
                self._create_violation(
                    rule_id="off_topic",
                    rule_name="Off-Topic Detection",
                    severity=RiskLevel.LOW if action == GuardrailAction.WARN else RiskLevel.MEDIUM,
                    description="Content appears to be off-topic",
                    category=ContentCategory.OFF_TOPIC,
                    detected_topic=best_topic,
                    detected_score=best_score,
                    allowed_topics=list(allowed_topics),
                )
            ]

            return self._create_fail_result(
                violations=violations,
                action=action,
                risk_level=RiskLevel.LOW,
                detected_topic=best_topic,
                detected_score=best_score,
                suggested_topic=suggested_topic,
                allowed_topics=list(allowed_topics),
                topic_scores={k: v for k, v in scores.items() if v > 0},
            )

        return self._create_pass_result(
            detected_topic=best_topic,
            detected_score=best_score,
            topic_scores={k: v for k, v in scores.items() if v > 0},
        )

    def _off_topic_action_to_guardrail_action(self) -> GuardrailAction:
        """Convert OffTopicAction to GuardrailAction."""
        mapping = {
            OffTopicAction.REDIRECT: GuardrailAction.MODIFY,
            OffTopicAction.BLOCK: GuardrailAction.BLOCK,
            OffTopicAction.WARN: GuardrailAction.WARN,
            OffTopicAction.ALLOW: GuardrailAction.ALLOW,
        }
        return mapping.get(self.off_topic_action, GuardrailAction.WARN)


class TopicDriftGuardrail(DialogGuardrail):
    """
    Guardrail for detecting topic drift in conversations.

    Monitors conversation flow to detect when discussions
    drift away from the original topic.

    Attributes:
        max_drift_turns: Maximum turns before flagging drift
        drift_threshold: Threshold for detecting drift (0.0-1.0)

    Example:
        ```python
        guardrail = TopicDriftGuardrail(
            max_drift_turns=3,
            drift_threshold=0.5,
        )

        result = await guardrail.check_dialog(
            dialog_context=dialog_ctx,
            security_context=ctx,
        )

        if not result.passed:
            # Topic has drifted
            return redirect_to_original_topic()
        ```
    """

    def __init__(
        self,
        max_drift_turns: int = 3,
        drift_threshold: float = 0.5,
        guardrail_id: str | None = None,
        priority: int = 60,
        enabled: bool = True,
        config: GuardrailConfig | None = None,
    ) -> None:
        """
        Initialize the topic drift guardrail.

        Args:
            max_drift_turns: Maximum turns before flagging
            drift_threshold: Drift detection threshold
            guardrail_id: Unique identifier
            priority: Execution priority
            enabled: Whether guardrail is active
            config: Guardrail configuration
        """
        super().__init__(
            guardrail_id=guardrail_id or "topic_drift_guardrail",
            priority=priority,
            enabled=enabled,
            config=config,
        )
        self.max_drift_turns = max_drift_turns
        self.drift_threshold = drift_threshold
        self._topic_guardrail = TopicGuardrail()

    async def _check_dialog_impl(
        self,
        dialog_context: DialogContext,
        context: dict[str, Any],
        security_context: SecurityContext,
    ) -> GuardrailResult:
        """Check for topic drift in conversation."""
        messages = dialog_context.messages
        if len(messages) < 2:
            return self._create_pass_result(insufficient_messages=True)

        # Extract topics from conversation
        topics_over_time: list[str | None] = []

        for msg in messages:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                topic = await self._topic_guardrail.extract_topic(content, security_context)
                topics_over_time.append(topic)

        if len(topics_over_time) < 2:
            return self._create_pass_result(insufficient_user_messages=True)

        # Detect drift
        original_topic = topics_over_time[0]
        recent_topics = topics_over_time[-self.max_drift_turns :]

        if original_topic is None:
            return self._create_pass_result(no_original_topic=True)

        # Count how many recent messages are off the original topic
        drift_count = sum(1 for t in recent_topics if t is not None and t != original_topic)

        drift_ratio = drift_count / len(recent_topics) if recent_topics else 0

        if drift_ratio >= self.drift_threshold:
            current_topic = recent_topics[-1] if recent_topics else None

            return self._create_fail_result(
                violations=[
                    self._create_violation(
                        rule_id="topic_drift",
                        rule_name="Topic Drift Detection",
                        severity=RiskLevel.LOW,
                        description="Conversation has drifted from original topic",
                        category=ContentCategory.OFF_TOPIC,
                        original_topic=original_topic,
                        current_topic=current_topic,
                        drift_ratio=drift_ratio,
                    )
                ],
                action=GuardrailAction.WARN,
                risk_level=RiskLevel.LOW,
                original_topic=original_topic,
                current_topic=current_topic,
                drift_ratio=drift_ratio,
                topics_over_time=topics_over_time,
            )

        return self._create_pass_result(
            original_topic=original_topic,
            drift_ratio=drift_ratio,
            topics_over_time=topics_over_time,
        )
