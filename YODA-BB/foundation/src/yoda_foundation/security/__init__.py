"""
Security module for the Agentic AI Component Library.

Provides comprehensive security components including RBAC, audit logging,
data masking, identity management, data governance, security guardrails,
secrets management, and security context propagation.

Example:
    ```python
    from yoda_foundation.security import (
        SecurityContext,
        Permission,
        create_security_context,
        UserIdentity,
        AgentIdentity,
        OAuthProvider,
        # RBAC
        Role,
        RoleHierarchy,
        PermissionEngine,
        PolicyEnforcementPoint,
        PolicyContext,
        ContextAwareRBAC,
        # Data Governance
        DataClassifier,
        SensitivityLevel,
        MaskingEngine,
        MaskingStrategy,
        RetentionPolicy,
        AuditLogger,
        # Guardrails
        InputValidator,
        OutputFilter,
        ActionLimiter,
        ContentPolicy,
        IndustryType,
        # Secrets Management
        VaultClient,
        VaultConfig,
    )

    # Create a security context
    context = create_security_context(
        user_id="user_123",
        tenant_id="tenant_456",
        permissions=["document.read", "document.write"],
    )

    # Setup RBAC
    hierarchy = RoleHierarchy()
    engine = PermissionEngine(role_store=store, role_hierarchy=hierarchy)
    pep = PolicyEnforcementPoint(permission_engine=engine)

    # Enforce policy
    decision = await pep.enforce(
        context=PolicyContext(
            user_id="user_123",
            resource="document",
            action="write",
        ),
        security_context=context,
    )

    # Data governance
    classifier = DataClassifier()
    classification = await classifier.classify(data, security_context=context)

    masker = MaskingEngine()
    masked = await masker.mask(text, security_context=context)

    audit = AuditLogger()
    await audit.log_access(
        resource_type="document",
        resource_id="doc_123",
        action=AuditAction.READ,
        security_context=context,
    )

    # Guardrails
    validator = InputValidator()
    validation = await validator.validate(
        input_text=user_input,
        security_context=context,
    )

    output_filter = OutputFilter(auto_redact_pii=True)
    filtered = await output_filter.filter(
        output=llm_output,
        security_context=context,
    )

    limiter = ActionLimiter()
    action_check = await limiter.check_action(
        action_type=ActionType.FILE_WRITE,
        security_context=context,
    )

    policy = ContentPolicy(industry=IndustryType.HEALTHCARE)
    policy_result = await policy.evaluate(
        content=content,
        security_context=context,
    )
    ```
"""

from yoda_foundation.security.agent_identity import (
    AgentCredentials,
    AgentIdentity,
    AgentType,
    ServiceAccount,
    ServiceAccountType,
)
from yoda_foundation.security.context import (
    ContextType,
    Permission,
    SecurityContext,
    create_anonymous_context,
    create_security_context,
    create_system_context,
)
try:
    from yoda_foundation.security.data_governance import (
        STANDARD_CATEGORIES,
        # Audit
        AuditAction,
        AuditEntry,
        AuditLogger,
        AuditStatus,
        AuditStorage,
        AuditTrail,
        ClassificationRule,
        DataCategory,
        DataClassification,
        DataClassifier,
        DataMasker,
        DataPurger,
        DataStore,
        FieldNameRule,
        InMemoryAuditStorage,
        KeywordRule,
        LegalHold,
        MaskingEngine,
        MaskingResult,
        MaskingRule,
        # Masking
        MaskingStrategy,
        PatternRule,
        PCIMasker,
        PHIMasker,
        PIIMasker,
        PurgeResult,
        # Retention
        RetentionAction,
        RetentionPolicy,
        RetentionScheduler,
        RetentionStatus,
        # Data Classification
        SensitivityLevel,
    )
except (ImportError, ModuleNotFoundError):
    pass  # data_governance optional -- may not have all transitive deps

try:
    from yoda_foundation.security.guardrails import (
        ActionCheckResult,
        ActionLimit,
        # Action Limits
        ActionLimiter,
        ActionPolicy,
        ActionRecord,
        ActionType,
        ContentCategory,
        ContentDetection,
        ContentFilter,
        # Content Policy
        ContentPolicy,
        ContentRule,
        CustomRule,
        ExecutionBoundary,
        FilterAction,
        FilterResult,
        IndustryType,
        InjectionDetectionResult,
        InjectionDetector,
        InjectionType,
        InputSanitizer,
        # Input Validation
        InputValidator,
        LengthRule,
        LimitType,
        # Output Filtering
        OutputFilter,
        PolicyEvaluationResult,
        PolicyViolation,
        RuleType,
        SafetyChecker,
        ValidationResult,
        ValidationViolation,
        ViolationSeverity,
        ViolationType,
    )
    from yoda_foundation.security.guardrails import (
        KeywordRule as PolicyKeywordRule,  # Rename to avoid conflict with data governance
    )
    from yoda_foundation.security.guardrails import (
        PatternRule as PolicyPatternRule,  # Rename to avoid conflict with data governance
    )
except (ImportError, ModuleNotFoundError):
    pass  # guardrails optional -- module may not exist yet
try:
    from yoda_foundation.security.identity_provider import (
        APIKeyProvider,
        IdentityProvider,
        OAuthProvider,
        ProviderType,
        SAMLProvider,
        TokenInfo,
    )
except (ImportError, ModuleNotFoundError):
    pass

try:
    from yoda_foundation.security.rbac import (
        AttributeRule,
        # Context-Aware RBAC
        ContextAwareRBAC,
        ContextRule,
        DataOwnershipRule,
        DynamicPermission,
        LocationRule,
        PermissionCache,
        # Permission Engine
        PermissionEngine,
        PermissionEvaluationResult,
        PermissionEvaluator,
        PermissionSet,
        PolicyContext,
        PolicyDecision,
        PolicyDecisionType,
        # Policy Enforcement
        PolicyEnforcementPoint,
        # Role Definitions
        Role,
        RoleHierarchy,
        RoleStore,
        StandardRoles,
        TimeRule,
    )
except (ImportError, ModuleNotFoundError):
    pass

try:
    from yoda_foundation.security.secrets import (
        AuthMethod,
        SecretAccessDeniedError,
        SecretMetadata,
        SecretNotFoundError,
        SecretResult,
        # Secrets Exceptions
        SecretsError,
        # Vault Client
        VaultClient,
        VaultConfig,
        VaultConnectionError,
        VaultHTTPClient,
    )
except (ImportError, ModuleNotFoundError):
    pass

try:
    from yoda_foundation.security.user_identity import (
        APIKeyCredentials,
        CredentialType,
        OAuthTokenCredentials,
        PasswordCredentials,
        SessionStatus,
        UserCredentials,
        UserIdentity,
        UserSession,
    )
except (ImportError, ModuleNotFoundError):
    pass


__all__ = [
    # Context
    "SecurityContext",
    "Permission",
    "ContextType",
    "create_security_context",
    "create_system_context",
    "create_anonymous_context",
    # User Identity
    "UserIdentity",
    "UserSession",
    "UserCredentials",
    "PasswordCredentials",
    "APIKeyCredentials",
    "OAuthTokenCredentials",
    "CredentialType",
    "SessionStatus",
    # Agent Identity
    "AgentIdentity",
    "AgentCredentials",
    "ServiceAccount",
    "AgentType",
    "ServiceAccountType",
    # Identity Providers
    "IdentityProvider",
    "OAuthProvider",
    "SAMLProvider",
    "APIKeyProvider",
    "ProviderType",
    "TokenInfo",
    # RBAC - Role Definitions
    "Role",
    "RoleHierarchy",
    "PermissionSet",
    "StandardRoles",
    # RBAC - Permission Engine
    "PermissionEngine",
    "PermissionEvaluator",
    "PermissionCache",
    "PermissionEvaluationResult",
    "RoleStore",
    # RBAC - Policy Enforcement
    "PolicyEnforcementPoint",
    "PolicyContext",
    "PolicyDecision",
    "PolicyDecisionType",
    # RBAC - Context-Aware
    "ContextAwareRBAC",
    "DynamicPermission",
    "ContextRule",
    "TimeRule",
    "LocationRule",
    "AttributeRule",
    "DataOwnershipRule",
    # Data Governance - Classification
    "SensitivityLevel",
    "DataCategory",
    "DataClassification",
    "ClassificationRule",
    "PatternRule",
    "KeywordRule",
    "FieldNameRule",
    "DataClassifier",
    "STANDARD_CATEGORIES",
    # Data Governance - Masking
    "MaskingStrategy",
    "MaskingRule",
    "MaskingResult",
    "DataMasker",
    "PIIMasker",
    "PHIMasker",
    "PCIMasker",
    "MaskingEngine",
    # Data Governance - Retention
    "RetentionAction",
    "RetentionStatus",
    "RetentionPolicy",
    "LegalHold",
    "PurgeResult",
    "DataStore",
    "DataPurger",
    "RetentionScheduler",
    # Data Governance - Audit
    "AuditAction",
    "AuditStatus",
    "AuditEntry",
    "AuditTrail",
    "AuditStorage",
    "InMemoryAuditStorage",
    "AuditLogger",
    # Guardrails - Input Validation
    "InputValidator",
    "InputSanitizer",
    "InjectionDetector",
    "InjectionType",
    "InjectionDetectionResult",
    "ValidationResult",
    "ValidationViolation",
    "ViolationType",
    # Guardrails - Output Filtering
    "OutputFilter",
    "ContentFilter",
    "SafetyChecker",
    "FilterResult",
    "ContentDetection",
    "ContentCategory",
    "FilterAction",
    # Guardrails - Action Limits
    "ActionLimiter",
    "ExecutionBoundary",
    "ActionPolicy",
    "ActionType",
    "ActionLimit",
    "ActionRecord",
    "ActionCheckResult",
    "LimitType",
    # Guardrails - Content Policy
    "ContentPolicy",
    "PolicyViolation",
    "PolicyEvaluationResult",
    "ContentRule",
    "PolicyKeywordRule",
    "PolicyPatternRule",
    "LengthRule",
    "CustomRule",
    "RuleType",
    "ViolationSeverity",
    "IndustryType",
    # Secrets Management
    "VaultClient",
    "VaultConfig",
    "AuthMethod",
    "SecretMetadata",
    "SecretResult",
    "VaultHTTPClient",
    "SecretsError",
    "VaultConnectionError",
    "SecretNotFoundError",
    "SecretAccessDeniedError",
]
