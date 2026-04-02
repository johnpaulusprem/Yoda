"""
Data Governance module for the Agentic AI Component Library.

Provides comprehensive data governance capabilities including:
- Data classification with sensitivity levels
- PII/PHI/PCI masking and tokenization
- Retention policies and automated purging
- Tamper-evident audit logging

Example:
    ```python
    from yoda_foundation.security.data_governance import (
        # Data Classification
        DataClassifier,
        SensitivityLevel,
        DataClassification,
        ClassificationRule,
        PatternRule,
        KeywordRule,
        FieldNameRule,
        # Masking
        MaskingEngine,
        MaskingStrategy,
        PIIMasker,
        PHIMasker,
        PCIMasker,
        # Retention
        RetentionPolicy,
        RetentionScheduler,
        DataPurger,
        RetentionAction,
        LegalHold,
        # Audit
        AuditLogger,
        AuditEntry,
        AuditAction,
        AuditStatus,
        AuditTrail,
    )

    # Classify data
    classifier = DataClassifier()
    result = await classifier.classify(data, security_context=ctx)

    # Mask sensitive data
    engine = MaskingEngine()
    masked = await engine.mask(text, security_context=ctx)

    # Apply retention policy
    policy = RetentionPolicy(
        name="user_data",
        retention_days=365,
        action=RetentionAction.ARCHIVE,
    )

    # Audit access
    audit = AuditLogger()
    await audit.log_access(
        resource_type="document",
        resource_id="doc_123",
        action=AuditAction.READ,
        security_context=ctx,
    )
    ```
"""

from yoda_foundation.security.data_governance.audit_logger import (
    # Enums
    AuditAction,
    # Core Classes
    AuditEntry,
    # Logger
    AuditLogger,
    AuditStatus,
    # Interfaces
    AuditStorage,
    AuditTrail,
    InMemoryAuditStorage,
)
from yoda_foundation.security.data_governance.data_classification import (
    # Constants
    STANDARD_CATEGORIES,
    # Rules
    ClassificationRule,
    DataCategory,
    DataClassification,
    # Classifier
    DataClassifier,
    FieldNameRule,
    KeywordRule,
    PatternRule,
    # Enums and Classes
    SensitivityLevel,
)
from yoda_foundation.security.data_governance.masking_engine import (
    DataMasker,
    # Engine
    MaskingEngine,
    MaskingResult,
    # Core Classes
    MaskingRule,
    # Enums
    MaskingStrategy,
    PCIMasker,
    PHIMasker,
    # Maskers
    PIIMasker,
)
from yoda_foundation.security.data_governance.retention_policy import (
    # Components
    DataPurger,
    # Interfaces
    DataStore,
    LegalHold,
    PurgeResult,
    # Enums
    RetentionAction,
    # Core Classes
    RetentionPolicy,
    RetentionScheduler,
    RetentionStatus,
)


__all__ = [
    # Data Classification
    "SensitivityLevel",
    "DataCategory",
    "DataClassification",
    "ClassificationRule",
    "PatternRule",
    "KeywordRule",
    "FieldNameRule",
    "DataClassifier",
    "STANDARD_CATEGORIES",
    # Masking
    "MaskingStrategy",
    "MaskingRule",
    "MaskingResult",
    "DataMasker",
    "PIIMasker",
    "PHIMasker",
    "PCIMasker",
    "MaskingEngine",
    # Retention
    "RetentionAction",
    "RetentionStatus",
    "RetentionPolicy",
    "LegalHold",
    "PurgeResult",
    "DataStore",
    "DataPurger",
    "RetentionScheduler",
    # Audit
    "AuditAction",
    "AuditStatus",
    "AuditEntry",
    "AuditTrail",
    "AuditStorage",
    "InMemoryAuditStorage",
    "AuditLogger",
]
