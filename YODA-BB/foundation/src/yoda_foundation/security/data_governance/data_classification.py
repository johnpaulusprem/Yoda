"""
Data classification module for the Agentic AI Component Library.

Provides automated data classification based on sensitivity levels,
categories (PII, PHI, PCI), and configurable rules using pattern
matching, keywords, and ML-based detection.

Example:
    ```python
    from yoda_foundation.security.data_governance import (
        DataClassifier,
        SensitivityLevel,
        ClassificationRule,
        PatternRule,
    )

    # Initialize classifier
    classifier = DataClassifier()

    # Add custom rules
    classifier.add_rule(PatternRule(
        name="credit_card",
        pattern=r"\b\\d{4}[- ]?\\d{4}[- ]?\\d{4}[- ]?\\d{4}\b",
        level=SensitivityLevel.RESTRICTED,
        category="PCI",
    ))

    # Classify data
    result = await classifier.classify(
        data={"user_email": "john@example.com", "ssn": "123-45-6789"},
        security_context=context,
    )

    # Check classification
    if result.level >= SensitivityLevel.CONFIDENTIAL:
        await apply_strict_controls(data)
    ```
"""

from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import IntEnum
from typing import Any

from yoda_foundation.exceptions import (
    GovernanceError,
    ValidationError,
)
from yoda_foundation.security.context import SecurityContext
from yoda_foundation.observability.logging import get_logger


logger = get_logger(__name__)


class SensitivityLevel(IntEnum):
    """
    Data sensitivity classification levels.

    Levels are ordered from lowest to highest sensitivity,
    allowing comparison operations (e.g., level >= CONFIDENTIAL).

    Attributes:
        PUBLIC: Publicly shareable information
        INTERNAL: Internal company information
        CONFIDENTIAL: Confidential business information
        RESTRICTED: Highly sensitive, restricted access
        TOP_SECRET: Maximum security, very limited access
    """

    PUBLIC = 0
    INTERNAL = 1
    CONFIDENTIAL = 2
    RESTRICTED = 3
    TOP_SECRET = 4

    def __str__(self) -> str:
        """Return string representation."""
        return self.name

    @property
    def description(self) -> str:
        """Get human-readable description of the level."""
        descriptions = {
            SensitivityLevel.PUBLIC: "Publicly shareable information",
            SensitivityLevel.INTERNAL: "Internal company use only",
            SensitivityLevel.CONFIDENTIAL: "Confidential business information",
            SensitivityLevel.RESTRICTED: "Highly sensitive, restricted access",
            SensitivityLevel.TOP_SECRET: "Maximum security classification",
        }
        return descriptions.get(self, "Unknown sensitivity level")


@dataclass(frozen=True)
class DataCategory:
    """
    Predefined data categories for classification.

    Represents specific types of sensitive data that require
    special handling (e.g., PII, PHI, PCI).
    """

    name: str
    description: str
    min_level: SensitivityLevel


# Standard data categories
STANDARD_CATEGORIES = {
    "PII": DataCategory(
        name="PII",
        description="Personally Identifiable Information",
        min_level=SensitivityLevel.CONFIDENTIAL,
    ),
    "PHI": DataCategory(
        name="PHI",
        description="Protected Health Information",
        min_level=SensitivityLevel.RESTRICTED,
    ),
    "PCI": DataCategory(
        name="PCI",
        description="Payment Card Industry Data",
        min_level=SensitivityLevel.RESTRICTED,
    ),
    "FINANCIAL": DataCategory(
        name="FINANCIAL",
        description="Financial Information",
        min_level=SensitivityLevel.CONFIDENTIAL,
    ),
    "IP": DataCategory(
        name="IP",
        description="Intellectual Property",
        min_level=SensitivityLevel.CONFIDENTIAL,
    ),
    "CREDENTIALS": DataCategory(
        name="CREDENTIALS",
        description="Authentication Credentials",
        min_level=SensitivityLevel.RESTRICTED,
    ),
}


@dataclass
class DataClassification:
    """
    Classification result for data.

    Contains the determined sensitivity level, categories,
    confidence score, and metadata about the classification.

    Attributes:
        level: Determined sensitivity level
        categories: Set of applicable data categories (PII, PHI, etc.)
        confidence: Confidence score (0.0 to 1.0)
        rules_matched: Names of rules that matched
        classified_by: User or system that performed classification
        classified_at: Timestamp of classification
        details: Additional classification details
        data_fingerprint: Hash of classified data for tracking

    Example:
        ```python
        classification = DataClassification(
            level=SensitivityLevel.RESTRICTED,
            categories={"PII", "PCI"},
            confidence=0.95,
            rules_matched=["ssn_pattern", "credit_card_pattern"],
            classified_by="system:classifier",
            classified_at=datetime.now(timezone.utc),
        )
        ```
    """

    level: SensitivityLevel
    categories: set[str] = field(default_factory=set)
    confidence: float = 1.0
    rules_matched: list[str] = field(default_factory=list)
    classified_by: str = "system"
    classified_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    details: dict[str, Any] = field(default_factory=dict)
    data_fingerprint: str | None = None

    def __post_init__(self) -> None:
        """Validate classification data."""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValidationError(
                message=f"Confidence must be between 0.0 and 1.0, got {self.confidence}",
                suggestions=["Provide a valid confidence score between 0 and 1"],
            )

        # Ensure categories is a set
        if isinstance(self.categories, list):
            object.__setattr__(self, "categories", set(self.categories))

    def to_dict(self) -> dict[str, Any]:
        """
        Convert classification to dictionary.

        Returns:
            Dictionary representation of the classification
        """
        return {
            "level": self.level.name,
            "level_value": self.level.value,
            "categories": list(self.categories),
            "confidence": self.confidence,
            "rules_matched": self.rules_matched,
            "classified_by": self.classified_by,
            "classified_at": self.classified_at.isoformat(),
            "details": self.details,
            "data_fingerprint": self.data_fingerprint,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DataClassification:
        """
        Create classification from dictionary.

        Args:
            data: Dictionary representation

        Returns:
            DataClassification instance
        """
        classified_at = data.get("classified_at")
        if isinstance(classified_at, str):
            classified_at = datetime.fromisoformat(classified_at)

        return cls(
            level=SensitivityLevel[data["level"]],
            categories=set(data.get("categories", [])),
            confidence=data.get("confidence", 1.0),
            rules_matched=data.get("rules_matched", []),
            classified_by=data.get("classified_by", "system"),
            classified_at=classified_at or datetime.now(UTC),
            details=data.get("details", {}),
            data_fingerprint=data.get("data_fingerprint"),
        )


class ClassificationRule(ABC):
    """
    Base class for classification rules.

    Classification rules determine sensitivity levels and categories
    based on data content.

    Attributes:
        name: Unique rule identifier
        level: Sensitivity level assigned by this rule
        category: Data category assigned by this rule
        confidence: Base confidence score for matches
        enabled: Whether the rule is active
    """

    def __init__(
        self,
        name: str,
        level: SensitivityLevel,
        category: str | None = None,
        confidence: float = 1.0,
        enabled: bool = True,
    ) -> None:
        """
        Initialize classification rule.

        Args:
            name: Unique rule identifier
            level: Sensitivity level to assign
            category: Data category to assign
            confidence: Confidence score for matches
            enabled: Whether rule is active
        """
        self.name = name
        self.level = level
        self.category = category
        self.confidence = confidence
        self.enabled = enabled

    @abstractmethod
    async def matches(
        self,
        data: str | dict[str, Any],
        security_context: SecurityContext,
    ) -> bool:
        """
        Check if rule matches the data.

        Args:
            data: Data to check (text or structured)
            security_context: Security context for authorization

        Returns:
            True if rule matches the data
        """
        pass

    async def apply(
        self,
        data: str | dict[str, Any],
        security_context: SecurityContext,
    ) -> DataClassification | None:
        """
        Apply rule to data and return classification if matched.

        Args:
            data: Data to classify
            security_context: Security context for authorization

        Returns:
            DataClassification if matched, None otherwise
        """
        if not self.enabled:
            return None

        if await self.matches(data, security_context):
            categories = {self.category} if self.category else set()
            return DataClassification(
                level=self.level,
                categories=categories,
                confidence=self.confidence,
                rules_matched=[self.name],
                classified_by=security_context.user_id,
            )

        return None


class PatternRule(ClassificationRule):
    """
    Classification rule based on regex pattern matching.

    Matches data against regular expressions to identify
    sensitive patterns (SSN, credit cards, emails, etc.).

    Example:
        ```python
        # SSN pattern rule
        ssn_rule = PatternRule(
            name="ssn_detector",
            pattern=r"\b\\d{3}-\\d{2}-\\d{4}\b",
            level=SensitivityLevel.RESTRICTED,
            category="PII",
        )

        # Credit card pattern rule
        cc_rule = PatternRule(
            name="credit_card",
            pattern=r"\b\\d{4}[- ]?\\d{4}[- ]?\\d{4}[- ]?\\d{4}\b",
            level=SensitivityLevel.RESTRICTED,
            category="PCI",
        )
        ```
    """

    def __init__(
        self,
        name: str,
        pattern: str,
        level: SensitivityLevel,
        category: str | None = None,
        confidence: float = 1.0,
        case_sensitive: bool = False,
        enabled: bool = True,
    ) -> None:
        """
        Initialize pattern rule.

        Args:
            name: Rule identifier
            pattern: Regular expression pattern
            level: Sensitivity level to assign
            category: Data category
            confidence: Confidence score
            case_sensitive: Whether pattern is case-sensitive
            enabled: Whether rule is active
        """
        super().__init__(name, level, category, confidence, enabled)
        flags = 0 if case_sensitive else re.IGNORECASE
        self.pattern = re.compile(pattern, flags)
        self.pattern_str = pattern

    async def matches(
        self,
        data: str | dict[str, Any],
        security_context: SecurityContext,
    ) -> bool:
        """
        Check if pattern matches the data.

        Args:
            data: Data to check
            security_context: Security context

        Returns:
            True if pattern found in data
        """
        # Convert structured data to string
        if isinstance(data, dict):
            text = " ".join(str(v) for v in data.values() if v is not None)
        else:
            text = str(data)

        return bool(self.pattern.search(text))


class KeywordRule(ClassificationRule):
    """
    Classification rule based on keyword matching.

    Matches data against a list of keywords to identify
    sensitive content.

    Example:
        ```python
        # Medical keywords rule
        medical_rule = KeywordRule(
            name="medical_terms",
            keywords=["diagnosis", "medication", "treatment", "patient"],
            level=SensitivityLevel.RESTRICTED,
            category="PHI",
        )
        ```
    """

    def __init__(
        self,
        name: str,
        keywords: list[str],
        level: SensitivityLevel,
        category: str | None = None,
        confidence: float = 0.8,
        case_sensitive: bool = False,
        min_matches: int = 1,
        enabled: bool = True,
    ) -> None:
        """
        Initialize keyword rule.

        Args:
            name: Rule identifier
            keywords: List of keywords to match
            level: Sensitivity level to assign
            category: Data category
            confidence: Confidence score
            case_sensitive: Whether matching is case-sensitive
            min_matches: Minimum number of keyword matches required
            enabled: Whether rule is active
        """
        super().__init__(name, level, category, confidence, enabled)
        self.keywords = keywords if case_sensitive else [k.lower() for k in keywords]
        self.case_sensitive = case_sensitive
        self.min_matches = min_matches

    async def matches(
        self,
        data: str | dict[str, Any],
        security_context: SecurityContext,
    ) -> bool:
        """
        Check if keywords match the data.

        Args:
            data: Data to check
            security_context: Security context

        Returns:
            True if sufficient keywords found
        """
        # Convert structured data to string
        if isinstance(data, dict):
            text = " ".join(str(v) for v in data.values() if v is not None)
        else:
            text = str(data)

        if not self.case_sensitive:
            text = text.lower()

        # Count keyword matches
        matches = sum(1 for keyword in self.keywords if keyword in text)
        return matches >= self.min_matches


class FieldNameRule(ClassificationRule):
    """
    Classification rule based on field names in structured data.

    Identifies sensitive data based on dictionary keys/field names.

    Example:
        ```python
        # PII field rule
        pii_rule = FieldNameRule(
            name="pii_fields",
            field_patterns=["ssn", "social_security", "email", "phone"],
            level=SensitivityLevel.CONFIDENTIAL,
            category="PII",
        )
        ```
    """

    def __init__(
        self,
        name: str,
        field_patterns: list[str],
        level: SensitivityLevel,
        category: str | None = None,
        confidence: float = 0.9,
        case_sensitive: bool = False,
        enabled: bool = True,
    ) -> None:
        """
        Initialize field name rule.

        Args:
            name: Rule identifier
            field_patterns: List of field name patterns to match
            level: Sensitivity level to assign
            category: Data category
            confidence: Confidence score
            case_sensitive: Whether matching is case-sensitive
            enabled: Whether rule is active
        """
        super().__init__(name, level, category, confidence, enabled)
        flags = 0 if case_sensitive else re.IGNORECASE
        self.patterns = [re.compile(pattern, flags) for pattern in field_patterns]

    async def matches(
        self,
        data: str | dict[str, Any],
        security_context: SecurityContext,
    ) -> bool:
        """
        Check if field names match the patterns.

        Args:
            data: Data to check (must be dictionary)
            security_context: Security context

        Returns:
            True if any field name matches
        """
        if not isinstance(data, dict):
            return False

        # Check all field names
        for field_name in data.keys():
            for pattern in self.patterns:
                if pattern.search(str(field_name)):
                    return True

        return False


class DataClassifier:
    """
    Automated data classification engine.

    Applies multiple classification rules to determine the
    sensitivity level and categories of data.

    Attributes:
        rules: List of classification rules
        default_level: Default sensitivity level if no rules match

    Example:
        ```python
        # Create classifier with default rules
        classifier = DataClassifier()

        # Add custom rule
        classifier.add_rule(PatternRule(
            name="api_key",
            pattern=r"api[_-]?key[_-]?[:=]\\s*['\"]?[a-zA-Z0-9]{32,}",
            level=SensitivityLevel.RESTRICTED,
            category="CREDENTIALS",
        ))

        # Classify data
        result = await classifier.classify(
            data={"user": "john@example.com", "api_key": "sk_1234..."},
            security_context=context,
        )

        print(f"Level: {result.level}")
        print(f"Categories: {result.categories}")
        print(f"Confidence: {result.confidence}")
        ```
    """

    def __init__(
        self,
        rules: list[ClassificationRule] | None = None,
        default_level: SensitivityLevel = SensitivityLevel.INTERNAL,
    ) -> None:
        """
        Initialize data classifier.

        Args:
            rules: Initial list of classification rules
            default_level: Default level if no rules match
        """
        self.rules: list[ClassificationRule] = rules or []
        self.default_level = default_level
        self._add_default_rules()

    def _add_default_rules(self) -> None:
        """Add default classification rules for common patterns."""
        # SSN patterns
        self.add_rule(
            PatternRule(
                name="ssn_dashes",
                pattern=r"\b\d{3}-\d{2}-\d{4}\b",
                level=SensitivityLevel.RESTRICTED,
                category="PII",
            )
        )

        self.add_rule(
            PatternRule(
                name="ssn_spaces",
                pattern=r"\b\d{3}\s\d{2}\s\d{4}\b",
                level=SensitivityLevel.RESTRICTED,
                category="PII",
            )
        )

        # Email addresses
        self.add_rule(
            PatternRule(
                name="email",
                pattern=r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
                level=SensitivityLevel.CONFIDENTIAL,
                category="PII",
                confidence=0.9,
            )
        )

        # Phone numbers
        self.add_rule(
            PatternRule(
                name="phone_us",
                pattern=r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",
                level=SensitivityLevel.CONFIDENTIAL,
                category="PII",
                confidence=0.8,
            )
        )

        # Credit card numbers
        self.add_rule(
            PatternRule(
                name="credit_card",
                pattern=r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b",
                level=SensitivityLevel.RESTRICTED,
                category="PCI",
            )
        )

        # API keys and tokens
        self.add_rule(
            PatternRule(
                name="api_key",
                pattern=r"(?i)(api[_-]?key|token|secret)[_-]?[:=]\s*['\"]?[a-zA-Z0-9]{20,}",
                level=SensitivityLevel.RESTRICTED,
                category="CREDENTIALS",
            )
        )

        # Medical record numbers
        self.add_rule(
            PatternRule(
                name="medical_record",
                pattern=r"\b(MRN|mrn)[:#]?\s*\d{6,}\b",
                level=SensitivityLevel.RESTRICTED,
                category="PHI",
            )
        )

        # PII field names
        self.add_rule(
            FieldNameRule(
                name="pii_fields",
                field_patterns=[
                    r"ssn|social.?security",
                    r"tax.?id|tin",
                    r"passport",
                    r"driver.?license",
                ],
                level=SensitivityLevel.RESTRICTED,
                category="PII",
            )
        )

        # PHI field names
        self.add_rule(
            FieldNameRule(
                name="phi_fields",
                field_patterns=[
                    r"medical.?record",
                    r"diagnosis",
                    r"medication",
                    r"treatment",
                    r"patient.?id",
                ],
                level=SensitivityLevel.RESTRICTED,
                category="PHI",
            )
        )

        # Financial field names
        self.add_rule(
            FieldNameRule(
                name="financial_fields",
                field_patterns=[
                    r"credit.?card",
                    r"bank.?account",
                    r"routing.?number",
                    r"account.?number",
                ],
                level=SensitivityLevel.RESTRICTED,
                category="PCI",
            )
        )

    def add_rule(self, rule: ClassificationRule) -> None:
        """
        Add a classification rule.

        Args:
            rule: Classification rule to add

        Example:
            ```python
            classifier.add_rule(KeywordRule(
                name="confidential_keywords",
                keywords=["confidential", "proprietary", "trade secret"],
                level=SensitivityLevel.CONFIDENTIAL,
                category="IP",
            ))
            ```
        """
        self.rules.append(rule)
        logger.debug(
            f"Added classification rule: {rule.name}",
            rule_name=rule.name,
            level=rule.level.name,
            category=rule.category,
        )

    def remove_rule(self, rule_name: str) -> bool:
        """
        Remove a classification rule by name.

        Args:
            rule_name: Name of rule to remove

        Returns:
            True if rule was removed, False if not found
        """
        initial_count = len(self.rules)
        self.rules = [r for r in self.rules if r.name != rule_name]
        removed = len(self.rules) < initial_count

        if removed:
            logger.debug(f"Removed classification rule: {rule_name}")

        return removed

    def get_rule(self, rule_name: str) -> ClassificationRule | None:
        """
        Get a classification rule by name.

        Args:
            rule_name: Name of rule to retrieve

        Returns:
            ClassificationRule if found, None otherwise
        """
        for rule in self.rules:
            if rule.name == rule_name:
                return rule
        return None

    async def classify(
        self,
        data: str | dict[str, Any],
        security_context: SecurityContext,
    ) -> DataClassification:
        """
        Classify data based on configured rules.

        Applies all enabled rules and combines results to determine
        the highest sensitivity level and all applicable categories.

        Args:
            data: Data to classify (text or structured)
            security_context: Security context for authorization

        Returns:
            DataClassification with determined level and categories

        Raises:
            AuthorizationError: If user lacks classification permission
            ValidationError: If data format is invalid

        Example:
            ```python
            result = await classifier.classify(
                data={
                    "name": "John Doe",
                    "email": "john@example.com",
                    "ssn": "123-45-6789",
                },
                security_context=context,
            )

            if result.level >= SensitivityLevel.RESTRICTED:
                logger.warning(
                    "Restricted data detected",
                    categories=list(result.categories),
                    confidence=result.confidence,
                )
            ```
        """
        # Check permission
        security_context.require_permission("data.classify")

        logger.info(
            "Classifying data",
            data_type=type(data).__name__,
            rules_count=len(self.rules),
            security_context=security_context,
        )

        # Generate data fingerprint for tracking
        data_str = str(data)
        fingerprint = hashlib.sha256(data_str.encode()).hexdigest()[:16]

        # Collect all matching classifications
        classifications: list[DataClassification] = []

        for rule in self.rules:
            try:
                result = await rule.apply(data, security_context)
                if result:
                    classifications.append(result)
            except (GovernanceError, OSError, ValueError) as e:
                logger.warning(
                    f"Rule {rule.name} failed",
                    rule_name=rule.name,
                    error=str(e),
                )

        # If no rules matched, use default
        if not classifications:
            logger.debug(
                "No classification rules matched, using default",
                default_level=self.default_level.name,
            )
            return DataClassification(
                level=self.default_level,
                categories=set(),
                confidence=1.0,
                rules_matched=[],
                classified_by=security_context.user_id,
                data_fingerprint=fingerprint,
            )

        # Combine classifications
        # - Use highest sensitivity level
        # - Combine all categories
        # - Average confidence scores
        # - Collect all matched rules
        highest_level = max(c.level for c in classifications)
        all_categories = set()
        all_rules = []
        confidences = []

        for c in classifications:
            all_categories.update(c.categories)
            all_rules.extend(c.rules_matched)
            confidences.append(c.confidence)

        avg_confidence = sum(confidences) / len(confidences)

        result = DataClassification(
            level=highest_level,
            categories=all_categories,
            confidence=avg_confidence,
            rules_matched=all_rules,
            classified_by=security_context.user_id,
            data_fingerprint=fingerprint,
            details={
                "total_rules_checked": len(self.rules),
                "rules_matched_count": len(classifications),
            },
        )

        logger.info(
            "Data classified",
            level=result.level.name,
            categories=list(result.categories),
            confidence=result.confidence,
            rules_matched=len(result.rules_matched),
            data_fingerprint=fingerprint,
        )

        return result

    async def classify_batch(
        self,
        data_items: list[str | dict[str, Any]],
        security_context: SecurityContext,
    ) -> list[DataClassification]:
        """
        Classify multiple data items in batch.

        Args:
            data_items: List of data items to classify
            security_context: Security context for authorization

        Returns:
            List of DataClassification results (same order as input)

        Example:
            ```python
            items = [
                {"email": "user1@example.com"},
                {"ssn": "123-45-6789"},
                {"public": "general information"},
            ]

            results = await classifier.classify_batch(items, context)

            for item, classification in zip(items, results):
                print(f"{item} -> {classification.level}")
            ```
        """
        results = []
        for item in data_items:
            result = await self.classify(item, security_context)
            results.append(result)

        logger.info(
            "Batch classification completed",
            total_items=len(data_items),
            security_context=security_context,
        )

        return results
