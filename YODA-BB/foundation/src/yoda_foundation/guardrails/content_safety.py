"""
Content safety guardrails for the Agentic AI Component Library.

This module provides guardrails for detecting and handling harmful content
including toxicity, profanity, hate speech, violence, and PII.

Example:
    ```python
    from yoda_foundation.guardrails.content_safety import (
        ToxicityGuardrail,
        ProfanityGuardrail,
        HateSpeechGuardrail,
        ViolenceGuardrail,
        PIIGuardrail,
        ContentSafetyConfig,
    )

    # Configure content safety
    config = ContentSafetyConfig(
        toxicity_threshold=0.7,
        pii_redaction=True,
        pii_types=["email", "phone", "ssn", "credit_card"],
    )

    # Create guardrails
    toxicity = ToxicityGuardrail(threshold=config.toxicity_threshold)
    pii = PIIGuardrail(redact=config.pii_redaction, pii_types=config.pii_types)

    # Check content
    result = await toxicity.check(user_message, security_context=ctx)
    if not result.passed:
        handle_toxic_content(result)
    ```
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from re import Pattern
from typing import Any

from yoda_foundation.guardrails.base import InputGuardrail, OutputGuardrail
from yoda_foundation.guardrails.schemas import (
    ContentCategory,
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
class ContentSafetyConfig:
    """
    Configuration for content safety guardrails.

    Attributes:
        toxicity_threshold: Threshold for toxicity detection (0.0-1.0)
        profanity_threshold: Threshold for profanity detection (0.0-1.0)
        hate_speech_threshold: Threshold for hate speech detection (0.0-1.0)
        violence_threshold: Threshold for violence detection (0.0-1.0)
        pii_redaction: Whether to redact PII (vs just detect)
        pii_types: List of PII types to detect
        custom_profanity_words: Additional profanity words to detect
        blocklist_words: Words to always block
        allowlist_words: Words to never block
        case_sensitive: Whether detection is case-sensitive

    Example:
        ```python
        config = ContentSafetyConfig(
            toxicity_threshold=0.7,
            pii_redaction=True,
            pii_types=["email", "phone", "ssn"],
            custom_profanity_words=["badword1", "badword2"],
        )
        ```
    """

    toxicity_threshold: float = 0.7
    profanity_threshold: float = 0.5
    hate_speech_threshold: float = 0.6
    violence_threshold: float = 0.6
    pii_redaction: bool = True
    pii_types: list[str] = field(default_factory=lambda: ["email", "phone", "ssn", "credit_card"])
    custom_profanity_words: list[str] = field(default_factory=list)
    blocklist_words: list[str] = field(default_factory=list)
    allowlist_words: list[str] = field(default_factory=list)
    case_sensitive: bool = False


class ToxicityGuardrail(InputGuardrail):
    """
    Guardrail for detecting toxic content.

    Uses pattern matching and keyword detection to identify
    toxic, harmful, or offensive content.

    Attributes:
        threshold: Confidence threshold for detection (0.0-1.0)

    Example:
        ```python
        guardrail = ToxicityGuardrail(threshold=0.7)

        result = await guardrail.check(
            content="You are an idiot!",
            security_context=ctx,
        )

        if not result.passed:
            print(f"Toxic content detected: {result.violations}")
        ```
    """

    # Common toxic patterns and keywords
    TOXIC_PATTERNS = [
        (r"\b(kill|murder|destroy)\s+(you|them|everyone)\b", RiskLevel.CRITICAL),
        (r"\b(stupid|idiot|moron|dumb)\b", RiskLevel.MEDIUM),
        (r"\b(hate|despise|loathe)\s+(you|them)\b", RiskLevel.HIGH),
        (r"\b(shut\s*up|go\s+away)\b", RiskLevel.LOW),
        (r"\byou\s+(suck|stink)\b", RiskLevel.MEDIUM),
    ]

    def __init__(
        self,
        threshold: float = 0.7,
        guardrail_id: str | None = None,
        priority: int = 10,
        enabled: bool = True,
        config: GuardrailConfig | None = None,
    ) -> None:
        """
        Initialize the toxicity guardrail.

        Args:
            threshold: Detection threshold (0.0-1.0)
            guardrail_id: Unique identifier
            priority: Execution priority
            enabled: Whether guardrail is active
            config: Guardrail configuration
        """
        super().__init__(
            guardrail_id=guardrail_id or "toxicity_guardrail",
            priority=priority,
            enabled=enabled,
            config=config,
        )
        self.threshold = threshold
        self._compiled_patterns: list[tuple[Pattern[str], RiskLevel]] = []
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Compile regex patterns for efficient matching."""
        for pattern, severity in self.TOXIC_PATTERNS:
            self._compiled_patterns.append((re.compile(pattern, re.IGNORECASE), severity))

    async def _check_impl(
        self,
        content: str,
        context: dict[str, Any],
        security_context: SecurityContext,
    ) -> GuardrailResult:
        """Check content for toxicity."""
        violations: list[Violation] = []
        max_severity = RiskLevel.NONE

        for pattern, severity in self._compiled_patterns:
            matches = pattern.finditer(content)
            for match in matches:
                violations.append(
                    self._create_violation(
                        rule_id=f"toxicity_{severity.value}",
                        rule_name="Toxicity Detection",
                        severity=severity,
                        description=f"Toxic content detected: {match.group()}",
                        evidence=match.group(),
                        location=(match.start(), match.end()),
                        category=ContentCategory.HATE_SPEECH,
                    )
                )
                max_severity = max(max_severity, severity)

        if violations:
            # Calculate confidence based on number and severity of matches
            confidence = min(
                1.0,
                len(violations) * 0.3
                + 0.1 * (sum(1 for v in violations if v.severity >= RiskLevel.HIGH)),
            )

            if confidence >= self.threshold:
                return self._create_fail_result(
                    violations=violations,
                    risk_level=max_severity,
                    confidence=confidence,
                )

        return self._create_pass_result()


class ProfanityGuardrail(InputGuardrail):
    """
    Guardrail for detecting and filtering profanity.

    Detects common profanity words and can optionally
    filter/replace them.

    Attributes:
        threshold: Detection threshold (0.0-1.0)
        filter_content: Whether to filter profanity
        replacement: Replacement character for filtered words
        custom_words: Additional profanity words to detect

    Example:
        ```python
        guardrail = ProfanityGuardrail(
            threshold=0.5,
            filter_content=True,
            replacement="*",
            custom_words=["customword"],
        )

        result = await guardrail.check(content, security_context=ctx)

        if result.modified_content:
            # Use filtered content
            clean_content = result.modified_content
        ```
    """

    # Base profanity words (using mild examples for demonstration)
    BASE_PROFANITY = {
        "damn",
        "darn",
        "heck",
        "crap",
    }

    def __init__(
        self,
        threshold: float = 0.5,
        filter_content: bool = False,
        replacement: str = "*",
        custom_words: list[str] | None = None,
        guardrail_id: str | None = None,
        priority: int = 20,
        enabled: bool = True,
        config: GuardrailConfig | None = None,
    ) -> None:
        """
        Initialize the profanity guardrail.

        Args:
            threshold: Detection threshold
            filter_content: Whether to filter profanity
            replacement: Replacement character
            custom_words: Additional profanity words
            guardrail_id: Unique identifier
            priority: Execution priority
            enabled: Whether guardrail is active
            config: Guardrail configuration
        """
        super().__init__(
            guardrail_id=guardrail_id or "profanity_guardrail",
            priority=priority,
            enabled=enabled,
            config=config,
        )
        self.threshold = threshold
        self.filter_content = filter_content
        self.replacement = replacement
        self.profanity_words = self.BASE_PROFANITY.copy()
        if custom_words:
            self.profanity_words.update(w.lower() for w in custom_words)

        # Build regex pattern
        escaped_words = [re.escape(word) for word in self.profanity_words]
        pattern = r"\b(" + "|".join(escaped_words) + r")\b"
        self._pattern = re.compile(pattern, re.IGNORECASE)

    async def _check_impl(
        self,
        content: str,
        context: dict[str, Any],
        security_context: SecurityContext,
    ) -> GuardrailResult:
        """Check content for profanity."""
        violations: list[Violation] = []
        matches = list(self._pattern.finditer(content))

        for match in matches:
            violations.append(
                self._create_violation(
                    rule_id="profanity_001",
                    rule_name="Profanity Detection",
                    severity=RiskLevel.MEDIUM,
                    description=f"Profanity detected: {match.group()}",
                    evidence=match.group(),
                    location=(match.start(), match.end()),
                )
            )

        if violations:
            modified_content = None
            if self.filter_content:
                # Replace profanity with replacement character
                modified_content = self._filter_profanity(content)

            confidence = min(1.0, len(violations) * 0.2)
            if confidence >= self.threshold:
                return self._create_fail_result(
                    violations=violations,
                    action=(
                        GuardrailAction.MODIFY if self.filter_content else GuardrailAction.WARN
                    ),
                    modified_content=modified_content,
                    confidence=confidence,
                )

        return self._create_pass_result()

    def _filter_profanity(self, content: str) -> str:
        """Replace profanity words with replacement characters."""

        def replace_word(match: re.Match) -> str:
            word = match.group()
            return self.replacement * len(word)

        return self._pattern.sub(replace_word, content)


class HateSpeechGuardrail(InputGuardrail):
    """
    Guardrail for detecting hate speech.

    Detects content that promotes hatred against protected groups
    based on race, religion, gender, sexuality, etc.

    Attributes:
        threshold: Detection threshold (0.0-1.0)

    Example:
        ```python
        guardrail = HateSpeechGuardrail(threshold=0.6)

        result = await guardrail.check(content, security_context=ctx)

        if not result.passed:
            # Block hate speech
            return block_response(result.violations)
        ```
    """

    # Hate speech patterns (simplified for demonstration)
    HATE_PATTERNS = [
        (r"\b(all|those)\s+\w+\s+(are|should)\s+(die|burn|be\s+killed)\b", RiskLevel.CRITICAL),
        (r"\b(hate|despise)\s+(all\s+)?\w+\s+(people|race|religion)\b", RiskLevel.HIGH),
        (r"\b\w+\s+(go\s+back|don't\s+belong)\b", RiskLevel.HIGH),
        (r"\binferi(or|ority)\s+(race|people|group)\b", RiskLevel.HIGH),
    ]

    def __init__(
        self,
        threshold: float = 0.6,
        guardrail_id: str | None = None,
        priority: int = 5,
        enabled: bool = True,
        config: GuardrailConfig | None = None,
    ) -> None:
        """
        Initialize the hate speech guardrail.

        Args:
            threshold: Detection threshold
            guardrail_id: Unique identifier
            priority: Execution priority
            enabled: Whether guardrail is active
            config: Guardrail configuration
        """
        super().__init__(
            guardrail_id=guardrail_id or "hate_speech_guardrail",
            priority=priority,
            enabled=enabled,
            config=config,
        )
        self.threshold = threshold
        self._compiled_patterns: list[tuple[Pattern[str], RiskLevel]] = []
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Compile regex patterns."""
        for pattern, severity in self.HATE_PATTERNS:
            self._compiled_patterns.append((re.compile(pattern, re.IGNORECASE), severity))

    async def _check_impl(
        self,
        content: str,
        context: dict[str, Any],
        security_context: SecurityContext,
    ) -> GuardrailResult:
        """Check content for hate speech."""
        violations: list[Violation] = []
        max_severity = RiskLevel.NONE

        for pattern, severity in self._compiled_patterns:
            matches = pattern.finditer(content)
            for match in matches:
                violations.append(
                    self._create_violation(
                        rule_id=f"hate_speech_{severity.value}",
                        rule_name="Hate Speech Detection",
                        severity=severity,
                        description="Hate speech detected",
                        evidence=match.group()[:50],  # Truncate for safety
                        location=(match.start(), match.end()),
                        category=ContentCategory.HATE_SPEECH,
                    )
                )
                max_severity = max(max_severity, severity)

        if violations:
            return self._create_fail_result(
                violations=violations,
                risk_level=max_severity,
                action=GuardrailAction.BLOCK,
            )

        return self._create_pass_result()


class ViolenceGuardrail(InputGuardrail):
    """
    Guardrail for detecting violent content.

    Detects content describing or promoting violence,
    harm, or dangerous activities.

    Attributes:
        threshold: Detection threshold (0.0-1.0)

    Example:
        ```python
        guardrail = ViolenceGuardrail(threshold=0.6)

        result = await guardrail.check(content, security_context=ctx)

        if not result.passed:
            handle_violent_content(result)
        ```
    """

    # Violence patterns
    VIOLENCE_PATTERNS = [
        (r"\b(how\s+to\s+)?(kill|murder|harm|hurt|attack)\s+\w+\b", RiskLevel.HIGH),
        (r"\b(bomb|weapon|gun|knife)\s+(making|instructions)\b", RiskLevel.CRITICAL),
        (r"\bviolent\s+(act|attack|crime)\b", RiskLevel.HIGH),
        (r"\b(torture|mutilate|dismember)\b", RiskLevel.CRITICAL),
        (r"\b(beat|punch|kick|stab|shoot)\s+(them|him|her|you)\b", RiskLevel.HIGH),
    ]

    def __init__(
        self,
        threshold: float = 0.6,
        guardrail_id: str | None = None,
        priority: int = 5,
        enabled: bool = True,
        config: GuardrailConfig | None = None,
    ) -> None:
        """
        Initialize the violence guardrail.

        Args:
            threshold: Detection threshold
            guardrail_id: Unique identifier
            priority: Execution priority
            enabled: Whether guardrail is active
            config: Guardrail configuration
        """
        super().__init__(
            guardrail_id=guardrail_id or "violence_guardrail",
            priority=priority,
            enabled=enabled,
            config=config,
        )
        self.threshold = threshold
        self._compiled_patterns: list[tuple[Pattern[str], RiskLevel]] = []
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Compile regex patterns."""
        for pattern, severity in self.VIOLENCE_PATTERNS:
            self._compiled_patterns.append((re.compile(pattern, re.IGNORECASE), severity))

    async def _check_impl(
        self,
        content: str,
        context: dict[str, Any],
        security_context: SecurityContext,
    ) -> GuardrailResult:
        """Check content for violence."""
        violations: list[Violation] = []
        max_severity = RiskLevel.NONE

        for pattern, severity in self._compiled_patterns:
            matches = pattern.finditer(content)
            for match in matches:
                violations.append(
                    self._create_violation(
                        rule_id=f"violence_{severity.value}",
                        rule_name="Violence Detection",
                        severity=severity,
                        description="Violent content detected",
                        evidence=match.group()[:50],
                        location=(match.start(), match.end()),
                        category=ContentCategory.VIOLENCE,
                    )
                )
                max_severity = max(max_severity, severity)

        if violations:
            return self._create_fail_result(
                violations=violations,
                risk_level=max_severity,
                action=GuardrailAction.BLOCK,
            )

        return self._create_pass_result()


class PIIGuardrail(OutputGuardrail):
    """
    Guardrail for detecting and redacting PII.

    Detects personally identifiable information including emails,
    phone numbers, SSNs, credit card numbers, and more.

    Attributes:
        redact: Whether to redact detected PII
        pii_types: List of PII types to detect

    Example:
        ```python
        guardrail = PIIGuardrail(
            redact=True,
            pii_types=["email", "phone", "ssn", "credit_card"],
        )

        result = await guardrail.check(
            content="Contact: john@example.com, 555-123-4567",
            security_context=ctx,
        )

        if result.modified_content:
            # Use redacted content
            safe_content = result.modified_content
            # "Contact: [EMAIL], [PHONE]"
        ```
    """

    # PII detection patterns
    PII_PATTERNS = {
        "email": (
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
            "[EMAIL]",
            RiskLevel.MEDIUM,
        ),
        "phone": (
            r"\b(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b",
            "[PHONE]",
            RiskLevel.MEDIUM,
        ),
        "ssn": (
            r"\b\d{3}-\d{2}-\d{4}\b",
            "[SSN]",
            RiskLevel.HIGH,
        ),
        "credit_card": (
            r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b",
            "[CREDIT_CARD]",
            RiskLevel.HIGH,
        ),
        "ip_address": (
            r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
            "[IP_ADDRESS]",
            RiskLevel.LOW,
        ),
        "date_of_birth": (
            r"\b(?:0?[1-9]|1[0-2])[/-](?:0?[1-9]|[12]\d|3[01])[/-](?:19|20)\d{2}\b",
            "[DOB]",
            RiskLevel.HIGH,
        ),
        "address": (
            r"\b\d+\s+[\w\s]+(?:street|st|avenue|ave|road|rd|boulevard|blvd|drive|dr|lane|ln|way|court|ct)\b",
            "[ADDRESS]",
            RiskLevel.MEDIUM,
        ),
        "passport": (
            r"\b[A-Z]{1,2}\d{6,9}\b",
            "[PASSPORT]",
            RiskLevel.HIGH,
        ),
        "bank_account": (
            r"\b(?:account|acct)[#:\s]*\d{8,17}\b",
            "[BANK_ACCOUNT]",
            RiskLevel.HIGH,
        ),
    }

    def __init__(
        self,
        redact: bool = True,
        pii_types: list[str] | None = None,
        guardrail_id: str | None = None,
        priority: int = 15,
        enabled: bool = True,
        config: GuardrailConfig | None = None,
    ) -> None:
        """
        Initialize the PII guardrail.

        Args:
            redact: Whether to redact PII
            pii_types: PII types to detect (default: all)
            guardrail_id: Unique identifier
            priority: Execution priority
            enabled: Whether guardrail is active
            config: Guardrail configuration
        """
        super().__init__(
            guardrail_id=guardrail_id or "pii_guardrail",
            priority=priority,
            enabled=enabled,
            config=config,
        )
        self.redact = redact
        self.pii_types = pii_types or list(self.PII_PATTERNS.keys())
        self._compiled_patterns: dict[str, tuple[Pattern[str], str, RiskLevel]] = {}
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Compile regex patterns for selected PII types."""
        for pii_type in self.pii_types:
            if pii_type in self.PII_PATTERNS:
                pattern, replacement, severity = self.PII_PATTERNS[pii_type]
                self._compiled_patterns[pii_type] = (
                    re.compile(pattern, re.IGNORECASE),
                    replacement,
                    severity,
                )

    async def _check_impl(
        self,
        content: str,
        context: dict[str, Any],
        security_context: SecurityContext,
    ) -> GuardrailResult:
        """Check content for PII."""
        violations: list[Violation] = []
        max_severity = RiskLevel.NONE
        modified_content = content

        for pii_type, (pattern, replacement, severity) in self._compiled_patterns.items():
            matches = list(pattern.finditer(content))

            for match in matches:
                violations.append(
                    self._create_violation(
                        rule_id=f"pii_{pii_type}",
                        rule_name=f"PII Detection: {pii_type}",
                        severity=severity,
                        description=f"{pii_type.upper()} detected in content",
                        evidence=self._mask_evidence(match.group()),
                        location=(match.start(), match.end()),
                        category=ContentCategory.PII,
                        pii_type=pii_type,
                    )
                )
                max_severity = max(max_severity, severity)

            # Redact if configured
            if self.redact and matches:
                modified_content = pattern.sub(replacement, modified_content)

        if violations:
            return self._create_fail_result(
                violations=violations,
                action=GuardrailAction.MODIFY if self.redact else GuardrailAction.WARN,
                risk_level=max_severity,
                modified_content=modified_content if self.redact else None,
            )

        return self._create_pass_result()

    def _mask_evidence(self, text: str) -> str:
        """Mask evidence for safe logging."""
        if len(text) <= 4:
            return "*" * len(text)
        return text[:2] + "*" * (len(text) - 4) + text[-2:]


class ContentSafetyGuardrail(InputGuardrail):
    """
    Composite guardrail combining multiple content safety checks.

    Combines toxicity, profanity, hate speech, violence, and PII
    detection into a single guardrail for convenience.

    Attributes:
        config: Content safety configuration
        toxicity: ToxicityGuardrail instance
        profanity: ProfanityGuardrail instance
        hate_speech: HateSpeechGuardrail instance
        violence: ViolenceGuardrail instance
        pii: PIIGuardrail instance

    Example:
        ```python
        config = ContentSafetyConfig(
            toxicity_threshold=0.7,
            pii_redaction=True,
        )

        guardrail = ContentSafetyGuardrail(config=config)

        result = await guardrail.check(content, security_context=ctx)

        if not result.passed:
            # Handle any safety violations
            for violation in result.violations:
                log_violation(violation)
        ```
    """

    def __init__(
        self,
        safety_config: ContentSafetyConfig | None = None,
        guardrail_id: str | None = None,
        priority: int = 1,
        enabled: bool = True,
        config: GuardrailConfig | None = None,
    ) -> None:
        """
        Initialize the composite content safety guardrail.

        Args:
            safety_config: Content safety configuration
            guardrail_id: Unique identifier
            priority: Execution priority
            enabled: Whether guardrail is active
            config: Guardrail configuration
        """
        super().__init__(
            guardrail_id=guardrail_id or "content_safety_guardrail",
            priority=priority,
            enabled=enabled,
            config=config,
        )
        self.safety_config = safety_config or ContentSafetyConfig()

        # Initialize sub-guardrails
        self.toxicity = ToxicityGuardrail(
            threshold=self.safety_config.toxicity_threshold,
            config=config,
        )
        self.profanity = ProfanityGuardrail(
            threshold=self.safety_config.profanity_threshold,
            custom_words=self.safety_config.custom_profanity_words,
            config=config,
        )
        self.hate_speech = HateSpeechGuardrail(
            threshold=self.safety_config.hate_speech_threshold,
            config=config,
        )
        self.violence = ViolenceGuardrail(
            threshold=self.safety_config.violence_threshold,
            config=config,
        )
        self.pii = PIIGuardrail(
            redact=self.safety_config.pii_redaction,
            pii_types=self.safety_config.pii_types,
            config=config,
        )

    async def _check_impl(
        self,
        content: str,
        context: dict[str, Any],
        security_context: SecurityContext,
    ) -> GuardrailResult:
        """Run all content safety checks."""
        results: list[GuardrailResult] = []

        # Run all sub-guardrails
        results.append(await self.toxicity.check(content, context, security_context))
        results.append(await self.profanity.check(content, context, security_context))
        results.append(await self.hate_speech.check(content, context, security_context))
        results.append(await self.violence.check(content, context, security_context))
        results.append(await self.pii.check(content, context, security_context))

        # Merge results
        return GuardrailResult.merge(results)
