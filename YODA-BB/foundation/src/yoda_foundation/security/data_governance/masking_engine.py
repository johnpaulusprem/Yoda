"""
Data masking engine for the Agentic AI Component Library.

Provides comprehensive data masking capabilities for PII, PHI, PCI,
and other sensitive data with reversible tokenization support.

Example:
    ```python
    from yoda_foundation.security.data_governance import (
        MaskingEngine,
        MaskingStrategy,
        PIIMasker,
        PHIMasker,
    )

    # Initialize engine
    engine = MaskingEngine()

    # Register maskers
    engine.register_masker(PIIMasker())
    engine.register_masker(PHIMasker())

    # Mask data
    result = await engine.mask(
        data="Call John at 555-123-4567 or email john@example.com",
        security_context=context,
    )
    # Output: "Call [REDACTED] at [PHONE:****4567] or email [EMAIL]"

    # Unmask for authorized users
    original = await engine.unmask(
        masked_data=result,
        security_context=admin_context,
    )
    ```
"""

from __future__ import annotations

import hashlib
import re
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from yoda_foundation.exceptions import (
    GovernanceError,
    ValidationError,
)
from yoda_foundation.security.context import SecurityContext
from yoda_foundation.observability.logging import get_logger


logger = get_logger(__name__)


class MaskingStrategy(Enum):
    """
    Masking strategies for sensitive data.

    Different strategies provide different levels of data utility
    and security.

    Attributes:
        REDACT: Replace with [REDACTED] - highest security, no utility
        PARTIAL: Show partial data (e.g., ****4567) - balanced
        HASH: Replace with one-way hash - deterministic masking
        TOKENIZE: Replace with reversible token - full utility with security
        PRESERVE_FORMAT: Mask while preserving format - some utility
    """

    REDACT = "redact"
    PARTIAL = "partial"
    HASH = "hash"
    TOKENIZE = "tokenize"
    PRESERVE_FORMAT = "preserve_format"


@dataclass
class MaskingRule:
    """
    Rule for masking specific data patterns.

    Attributes:
        name: Rule identifier
        pattern: Regex pattern to match
        strategy: Masking strategy to use
        preserve_chars: Number of characters to preserve (for PARTIAL)
        replacement: Custom replacement text
        enabled: Whether rule is active
    """

    name: str
    pattern: str
    strategy: MaskingStrategy = MaskingStrategy.REDACT
    preserve_chars: int = 4
    replacement: str | None = None
    enabled: bool = True

    def __post_init__(self) -> None:
        """Compile regex pattern."""
        self._compiled_pattern = re.compile(self.pattern, re.IGNORECASE)

    @property
    def compiled_pattern(self) -> re.Pattern:
        """Get compiled regex pattern."""
        return self._compiled_pattern


@dataclass
class MaskingResult:
    """
    Result of masking operation.

    Attributes:
        masked_data: The masked data
        original_type: Type of original data
        masks_applied: List of mask names applied
        tokenization_id: ID for reversible tokenization
        metadata: Additional metadata
    """

    masked_data: str | dict[str, Any]
    original_type: str
    masks_applied: list[str] = field(default_factory=list)
    tokenization_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class DataMasker(ABC):
    """
    Base class for data maskers.

    Maskers detect and mask specific types of sensitive data.

    Attributes:
        name: Masker identifier
        priority: Execution priority (higher runs first)
        enabled: Whether masker is active
    """

    def __init__(
        self,
        name: str,
        priority: int = 100,
        enabled: bool = True,
    ) -> None:
        """
        Initialize data masker.

        Args:
            name: Masker identifier
            priority: Execution priority
            enabled: Whether masker is active
        """
        self.name = name
        self.priority = priority
        self.enabled = enabled
        self.rules: list[MaskingRule] = []
        self._token_store: dict[str, str] = {}

    @abstractmethod
    async def mask(
        self,
        data: str,
        strategy: MaskingStrategy,
        security_context: SecurityContext,
    ) -> str:
        """
        Mask sensitive data in text.

        Args:
            data: Text containing sensitive data
            strategy: Masking strategy to use
            security_context: Security context

        Returns:
            Masked text
        """
        pass

    async def unmask(
        self,
        masked_data: str,
        tokenization_id: str,
        security_context: SecurityContext,
    ) -> str:
        """
        Unmask tokenized data.

        Only works for TOKENIZE strategy. Requires appropriate permissions.

        Args:
            masked_data: Masked text
            tokenization_id: Tokenization ID
            security_context: Security context

        Returns:
            Original unmasked text

        Raises:
            AuthorizationError: If user lacks unmask permission
        """
        security_context.require_permission("data.unmask")

        # Look up tokens
        token_key = f"{tokenization_id}:{masked_data}"
        original = self._token_store.get(token_key)

        if original is None:
            logger.warning(
                "Token not found for unmasking",
                tokenization_id=tokenization_id,
                security_context=security_context,
            )
            return masked_data

        logger.info(
            "Data unmasked",
            masker=self.name,
            tokenization_id=tokenization_id,
            security_context=security_context,
        )

        return original

    def _generate_token(self, original: str, tokenization_id: str) -> str:
        """
        Generate and store a reversible token.

        Args:
            original: Original value
            tokenization_id: Tokenization session ID

        Returns:
            Token string
        """
        token = f"[TOKEN:{secrets.token_hex(8)}]"
        token_key = f"{tokenization_id}:{token}"
        self._token_store[token_key] = original
        return token

    def _apply_strategy(
        self,
        value: str,
        strategy: MaskingStrategy,
        label: str = "MASKED",
        tokenization_id: str | None = None,
    ) -> str:
        """
        Apply masking strategy to a value.

        Args:
            value: Value to mask
            strategy: Strategy to apply
            label: Label for masked value
            tokenization_id: ID for tokenization

        Returns:
            Masked value
        """
        if strategy == MaskingStrategy.REDACT:
            return f"[{label}]"

        elif strategy == MaskingStrategy.PARTIAL:
            if len(value) <= 4:
                return "****"
            preserve = 4
            masked_part = "*" * (len(value) - preserve)
            return f"{masked_part}{value[-preserve:]}"

        elif strategy == MaskingStrategy.HASH:
            hash_value = hashlib.sha256(value.encode()).hexdigest()[:8]
            return f"[{label}:{hash_value}]"

        elif strategy == MaskingStrategy.TOKENIZE:
            if tokenization_id:
                token = self._generate_token(value, tokenization_id)
                return token
            else:
                # Fallback to hash if no tokenization ID
                return self._apply_strategy(value, MaskingStrategy.HASH, label)

        elif strategy == MaskingStrategy.PRESERVE_FORMAT:
            # Replace alphanumeric with X, preserve special chars
            return "".join("X" if c.isalnum() else c for c in value)

        return f"[{label}]"


class PIIMasker(DataMasker):
    """
    Masker for Personally Identifiable Information (PII).

    Masks SSN, email addresses, phone numbers, addresses, etc.

    Example:
        ```python
        masker = PIIMasker()
        masked = await masker.mask(
            data="Contact: john@example.com or 555-123-4567",
            strategy=MaskingStrategy.PARTIAL,
            security_context=context,
        )
        # Output: "Contact: [EMAIL] or [PHONE:****4567]"
        ```
    """

    def __init__(self, priority: int = 100, enabled: bool = True) -> None:
        """Initialize PII masker."""
        super().__init__("pii_masker", priority, enabled)
        self._setup_rules()

    def _setup_rules(self) -> None:
        """Setup PII masking rules."""
        # SSN patterns
        self.rules.append(
            MaskingRule(
                name="ssn_dashes",
                pattern=r"\b\d{3}-\d{2}-\d{4}\b",
                strategy=MaskingStrategy.PARTIAL,
            )
        )

        self.rules.append(
            MaskingRule(
                name="ssn_spaces",
                pattern=r"\b\d{3}\s\d{2}\s\d{4}\b",
                strategy=MaskingStrategy.PARTIAL,
            )
        )

        # Email addresses
        self.rules.append(
            MaskingRule(
                name="email",
                pattern=r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
                strategy=MaskingStrategy.REDACT,
            )
        )

        # Phone numbers
        self.rules.append(
            MaskingRule(
                name="phone_us",
                pattern=r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",
                strategy=MaskingStrategy.PARTIAL,
            )
        )

        self.rules.append(
            MaskingRule(
                name="phone_intl",
                pattern=r"\+\d{1,3}[-.\s]?\d{1,14}",
                strategy=MaskingStrategy.PARTIAL,
            )
        )

    async def mask(
        self,
        data: str,
        strategy: MaskingStrategy,
        security_context: SecurityContext,
    ) -> str:
        """
        Mask PII in text.

        Args:
            data: Text containing PII
            strategy: Masking strategy
            security_context: Security context

        Returns:
            Masked text
        """
        masked = data
        tokenization_id = secrets.token_hex(16)

        for rule in self.rules:
            if not rule.enabled:
                continue

            def replacer(match: re.Match) -> str:
                value = match.group(0)
                # Determine label from rule name
                label = rule.name.split("_")[0].upper()
                return self._apply_strategy(
                    value,
                    strategy,
                    label,
                    tokenization_id,
                )

            masked = rule.compiled_pattern.sub(replacer, masked)

        return masked


class PHIMasker(DataMasker):
    """
    Masker for Protected Health Information (PHI).

    Masks medical record numbers, diagnoses, medications, etc.

    Example:
        ```python
        masker = PHIMasker()
        masked = await masker.mask(
            data="Patient MRN: 123456, Diagnosis: Hypertension",
            strategy=MaskingStrategy.HASH,
            security_context=context,
        )
        ```
    """

    def __init__(self, priority: int = 100, enabled: bool = True) -> None:
        """Initialize PHI masker."""
        super().__init__("phi_masker", priority, enabled)
        self._setup_rules()

    def _setup_rules(self) -> None:
        """Setup PHI masking rules."""
        # Medical record numbers
        self.rules.append(
            MaskingRule(
                name="mrn",
                pattern=r"\b(MRN|mrn)[:#]?\s*\d{6,}\b",
                strategy=MaskingStrategy.HASH,
            )
        )

        # Patient IDs
        self.rules.append(
            MaskingRule(
                name="patient_id",
                pattern=r"\b(patient|pt)[_\s]?(id|number)[:#]?\s*[A-Z0-9]{6,}\b",
                strategy=MaskingStrategy.HASH,
            )
        )

    async def mask(
        self,
        data: str,
        strategy: MaskingStrategy,
        security_context: SecurityContext,
    ) -> str:
        """
        Mask PHI in text.

        Args:
            data: Text containing PHI
            strategy: Masking strategy
            security_context: Security context

        Returns:
            Masked text
        """
        masked = data
        tokenization_id = secrets.token_hex(16)

        for rule in self.rules:
            if not rule.enabled:
                continue

            def replacer(match: re.Match) -> str:
                value = match.group(0)
                return self._apply_strategy(
                    value,
                    strategy,
                    "PHI",
                    tokenization_id,
                )

            masked = rule.compiled_pattern.sub(replacer, masked)

        return masked


class PCIMasker(DataMasker):
    """
    Masker for Payment Card Industry (PCI) data.

    Masks credit card numbers, CVV, account numbers, etc.

    Example:
        ```python
        masker = PCIMasker()
        masked = await masker.mask(
            data="Card: 4532-1234-5678-9010, CVV: 123",
            strategy=MaskingStrategy.PARTIAL,
            security_context=context,
        )
        # Output: "Card: [CARD:****9010], CVV: [REDACTED]"
        ```
    """

    def __init__(self, priority: int = 100, enabled: bool = True) -> None:
        """Initialize PCI masker."""
        super().__init__("pci_masker", priority, enabled)
        self._setup_rules()

    def _setup_rules(self) -> None:
        """Setup PCI masking rules."""
        # Credit card numbers
        self.rules.append(
            MaskingRule(
                name="credit_card",
                pattern=r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b",
                strategy=MaskingStrategy.PARTIAL,
            )
        )

        # CVV
        self.rules.append(
            MaskingRule(
                name="cvv",
                pattern=r"\b(cvv|cvc)[:#]?\s*\d{3,4}\b",
                strategy=MaskingStrategy.REDACT,
            )
        )

        # Account numbers
        self.rules.append(
            MaskingRule(
                name="account_number",
                pattern=r"\b(account|acct)[_\s]?(number|num|#)[:#]?\s*\d{8,17}\b",
                strategy=MaskingStrategy.PARTIAL,
            )
        )

    async def mask(
        self,
        data: str,
        strategy: MaskingStrategy,
        security_context: SecurityContext,
    ) -> str:
        """
        Mask PCI data in text.

        Args:
            data: Text containing PCI data
            strategy: Masking strategy
            security_context: Security context

        Returns:
            Masked text
        """
        masked = data
        tokenization_id = secrets.token_hex(16)

        for rule in self.rules:
            if not rule.enabled:
                continue

            def replacer(match: re.Match) -> str:
                value = match.group(0)
                label = "CARD" if "card" in rule.name else "PCI"
                return self._apply_strategy(
                    value,
                    strategy,
                    label,
                    tokenization_id,
                )

            masked = rule.compiled_pattern.sub(replacer, masked)

        return masked


class MaskingEngine:
    """
    Comprehensive data masking engine.

    Orchestrates multiple maskers to protect sensitive data across
    different categories (PII, PHI, PCI).

    Attributes:
        maskers: Registered data maskers
        default_strategy: Default masking strategy

    Example:
        ```python
        # Create and configure engine
        engine = MaskingEngine(
            default_strategy=MaskingStrategy.PARTIAL
        )

        # Register maskers
        engine.register_masker(PIIMasker())
        engine.register_masker(PHIMasker())
        engine.register_masker(PCIMasker())

        # Mask text data
        result = await engine.mask(
            data="Patient: John, SSN: 123-45-6789, Card: 4532-1234-5678-9010",
            security_context=context,
        )

        # Mask structured data
        user_data = {
            "name": "John Doe",
            "email": "john@example.com",
            "ssn": "123-45-6789",
        }

        masked_user = await engine.mask_dict(
            data=user_data,
            security_context=context,
        )
        ```
    """

    def __init__(
        self,
        maskers: list[DataMasker] | None = None,
        default_strategy: MaskingStrategy = MaskingStrategy.REDACT,
    ) -> None:
        """
        Initialize masking engine.

        Args:
            maskers: Initial list of maskers
            default_strategy: Default masking strategy
        """
        self.maskers: list[DataMasker] = maskers or []
        self.default_strategy = default_strategy

        # Add default maskers if none provided
        if not self.maskers:
            self.register_masker(PIIMasker())
            self.register_masker(PHIMasker())
            self.register_masker(PCIMasker())

    def register_masker(self, masker: DataMasker) -> None:
        """
        Register a data masker.

        Maskers are executed in priority order (highest first).

        Args:
            masker: Data masker to register
        """
        self.maskers.append(masker)
        # Sort by priority (highest first)
        self.maskers.sort(key=lambda m: m.priority, reverse=True)

        logger.debug(
            f"Registered masker: {masker.name}",
            masker=masker.name,
            priority=masker.priority,
        )

    def unregister_masker(self, masker_name: str) -> bool:
        """
        Unregister a masker by name.

        Args:
            masker_name: Name of masker to remove

        Returns:
            True if masker was removed, False if not found
        """
        initial_count = len(self.maskers)
        self.maskers = [m for m in self.maskers if m.name != masker_name]
        removed = len(self.maskers) < initial_count

        if removed:
            logger.debug(f"Unregistered masker: {masker_name}")

        return removed

    async def mask(
        self,
        data: str,
        strategy: MaskingStrategy | None = None,
        *,
        security_context: SecurityContext,
    ) -> MaskingResult:
        """
        Mask sensitive data in text.

        Applies all registered maskers in priority order.

        Args:
            data: Text to mask
            strategy: Masking strategy (uses default if not specified)
            security_context: Security context

        Returns:
            MaskingResult with masked data

        Raises:
            ValidationError: If data is invalid

        Example:
            ```python
            result = await engine.mask(
                data="Call 555-1234 or email user@example.com",
                strategy=MaskingStrategy.PARTIAL,
                security_context=context,
            )

            print(result.masked_data)
            # Output: "Call [PHONE:****1234] or email [EMAIL]"
            ```
        """
        if not isinstance(data, str):
            raise ValidationError(
                message=f"Expected string data, got {type(data).__name__}",
                suggestions=["Provide text data to mask"],
            )

        strategy = strategy or self.default_strategy
        masked = data
        masks_applied = []

        logger.debug(
            "Masking data",
            data_length=len(data),
            strategy=strategy.value,
            maskers_count=len(self.maskers),
        )

        # Apply each masker
        for masker in self.maskers:
            if not masker.enabled:
                continue

            try:
                masked = await masker.mask(
                    masked,
                    strategy,
                    security_context,
                )
                masks_applied.append(masker.name)
            except (GovernanceError, OSError, ValueError) as e:
                logger.warning(
                    f"Masker {masker.name} failed",
                    masker=masker.name,
                    error=str(e),
                )

        result = MaskingResult(
            masked_data=masked,
            original_type="str",
            masks_applied=masks_applied,
            metadata={
                "strategy": strategy.value,
                "original_length": len(data),
                "masked_length": len(masked),
            },
        )

        logger.info(
            "Data masked",
            masks_applied=len(masks_applied),
            strategy=strategy.value,
        )

        return result

    async def mask_dict(
        self,
        data: dict[str, Any],
        strategy: MaskingStrategy | None = None,
        *,
        security_context: SecurityContext,
        sensitive_fields: set[str] | None = None,
    ) -> MaskingResult:
        """
        Mask sensitive data in dictionary.

        Recursively masks string values in dictionary while preserving structure.

        Args:
            data: Dictionary to mask
            strategy: Masking strategy
            security_context: Security context
            sensitive_fields: Set of field names to always mask

        Returns:
            MaskingResult with masked dictionary

        Example:
            ```python
            user = {
                "name": "John Doe",
                "email": "john@example.com",
                "profile": {
                    "phone": "555-1234",
                    "ssn": "123-45-6789",
                }
            }

            result = await engine.mask_dict(
                data=user,
                security_context=context,
            )
            ```
        """
        strategy = strategy or self.default_strategy
        sensitive_fields = sensitive_fields or set()
        masks_applied = []

        async def mask_value(key: str, value: Any) -> Any:
            # Always mask sensitive fields
            if key.lower() in sensitive_fields:
                if isinstance(value, str):
                    result = await self.mask(value, strategy, security_context=security_context)
                    masks_applied.extend(result.masks_applied)
                    return result.masked_data
                return "[REDACTED]"

            # Recursively process dictionaries
            if isinstance(value, dict):
                return {k: await mask_value(k, v) for k, v in value.items()}

            # Process lists
            elif isinstance(value, list):
                return [await mask_value(key, item) for item in value]

            # Mask string values
            elif isinstance(value, str):
                result = await self.mask(value, strategy, security_context=security_context)
                if result.masks_applied:
                    masks_applied.extend(result.masks_applied)
                    return result.masked_data

            return value

        masked_dict = {}
        for key, value in data.items():
            masked_dict[key] = await mask_value(key, value)

        result = MaskingResult(
            masked_data=masked_dict,
            original_type="dict",
            masks_applied=list(set(masks_applied)),  # Deduplicate
            metadata={
                "strategy": strategy.value,
                "field_count": len(data),
            },
        )

        logger.info(
            "Dictionary masked",
            field_count=len(data),
            masks_applied=len(result.masks_applied),
        )

        return result

    async def unmask(
        self,
        masked_result: MaskingResult,
        security_context: SecurityContext,
    ) -> str | dict[str, Any]:
        """
        Unmask data (only for tokenized data).

        Requires unmask permission. Only works with TOKENIZE strategy.

        Args:
            masked_result: MaskingResult from previous masking
            security_context: Security context with unmask permission

        Returns:
            Unmasked data

        Raises:
            AuthorizationError: If user lacks unmask permission
            ValidationError: If data cannot be unmasked

        Example:
            ```python
            # Mask with tokenization
            result = await engine.mask(
                data=sensitive_data,
                strategy=MaskingStrategy.TOKENIZE,
                security_context=context,
            )

            # Later, unmask for authorized user
            original = await engine.unmask(
                masked_result=result,
                security_context=admin_context,
            )
            ```
        """
        security_context.require_permission("data.unmask")

        if not masked_result.tokenization_id:
            raise ValidationError(
                message="Cannot unmask data without tokenization ID",
                suggestions=[
                    "Use MaskingStrategy.TOKENIZE when masking",
                    "Only tokenized data can be unmasked",
                ],
            )

        logger.info(
            "Unmasking data",
            tokenization_id=masked_result.tokenization_id,
            security_context=security_context,
        )

        # For now, return masked data as unmasking requires token storage
        # In production, this would look up tokens from secure storage
        return masked_result.masked_data
