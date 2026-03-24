"""
Guardrails module for the Agentic AI Component Library.

Provides a comprehensive guardrails system inspired by NeMo Guardrails
for content safety, jailbreak detection, topic adherence, fact-checking,
policy enforcement, and content moderation.

Example:
    ```python
    from yoda_foundation.guardrails import (
        # Core
        GuardrailEngine,
        GuardrailConfig,
        GuardrailResult,
        GuardrailAction,
        RiskLevel,
        # Content Safety
        ToxicityGuardrail,
        PIIGuardrail,
        ProfanityGuardrail,
        HateSpeechGuardrail,
        ViolenceGuardrail,
        ContentSafetyGuardrail,
        # Jailbreak Detection
        JailbreakDetector,
        PromptInjectionGuardrail,
        RolePlayGuardrail,
        EncodingGuardrail,
        # Topic & Facts
        TopicGuardrail,
        FactCheckGuardrail,
        GroundingGuardrail,
        # Policy & Moderation
        PolicyGuardrail,
        Policy,
        PolicyRule,
        ModerationGuardrail,
        # Rail DSL
        Rail,
        RailParser,
        RailValidator,
        # Middleware
        GuardrailMiddleware,
        guarded,
    )

    # Configure engine
    config = GuardrailConfig(
        fail_on_block=True,
        risk_threshold=RiskLevel.MEDIUM,
    )
    engine = GuardrailEngine(config)

    # Register guardrails
    engine.register_guardrail(ToxicityGuardrail(threshold=0.7))
    engine.register_guardrail(PIIGuardrail(redact=True))
    engine.register_guardrail(JailbreakDetector())
    engine.register_guardrail(TopicGuardrail(allowed_topics=["support"]))

    # Check input
    result = await engine.check_input(user_message, security_context)
    if not result.passed:
        handle_violation(result.violations)

    # Use decorator
    @guarded(engine, check_input=True, check_output=True)
    async def process(content: str, security_context: SecurityContext) -> str:
        return await agent.run(content)
    ```
"""

# Schemas
# Base classes
from yoda_foundation.guardrails.base import (
    BaseGuardrail,
    DialogGuardrail,
    ExecutionGuardrail,
    InputGuardrail,
    OutputGuardrail,
    RetrievalGuardrail,
)

# Content Safety
from yoda_foundation.guardrails.content_safety import (
    ContentSafetyConfig,
    ContentSafetyGuardrail,
    HateSpeechGuardrail,
    PIIGuardrail,
    ProfanityGuardrail,
    ToxicityGuardrail,
    ViolenceGuardrail,
)

# Engine
from yoda_foundation.guardrails.engine import (
    GuardrailEngine,
)

# Fact Checking
from yoda_foundation.guardrails.fact_check import (
    Claim,
    FactCheckGuardrail,
    GroundingGuardrail,
    HallucinationGuardrail,
)

# Jailbreak Detection
from yoda_foundation.guardrails.jailbreak import (
    EncodingGuardrail,
    JailbreakDetector,
    JailbreakPattern,
    PromptInjectionGuardrail,
    RolePlayGuardrail,
)

# Middleware
from yoda_foundation.guardrails.middleware import (
    GuardedContext,
    GuardedExecutionResult,
    GuardrailChain,
    GuardrailMiddleware,
    guarded,
)

# Content Moderation
from yoda_foundation.guardrails.moderation import (
    ContentFilter,
    ContentFilterConfig,
    ModerationGuardrail,
    OutputModerationGuardrail,
)

# Policy Enforcement
from yoda_foundation.guardrails.policy import (
    ConditionalPolicy,
    ConditionalPolicyGuardrail,
    Policy,
    PolicyGuardrail,
    PolicyRule,
    SemanticPolicyGuardrail,
)

# Rail DSL
from yoda_foundation.guardrails.rail import (
    Rail,
    RailGuardrailSpec,
    RailParser,
    RailValidator,
    ValidationError,
    ValidationResult,
)
from yoda_foundation.guardrails.schemas import (
    ContentCategory,
    DialogContext,
    FactCheckResult,
    GuardrailAction,
    GuardrailConfig,
    GuardrailResult,
    GuardrailType,
    ModerationResult,
    RetrievalContext,
    RiskLevel,
    RuleConfig,
    Violation,
)

# Topic Adherence
from yoda_foundation.guardrails.topic import (
    OffTopicAction,
    TopicDefinition,
    TopicDriftGuardrail,
    TopicGuardrail,
)


__all__ = [
    # Schemas
    "GuardrailType",
    "GuardrailAction",
    "RiskLevel",
    "ContentCategory",
    "Violation",
    "GuardrailResult",
    "RuleConfig",
    "GuardrailConfig",
    "DialogContext",
    "RetrievalContext",
    "FactCheckResult",
    "ModerationResult",
    # Base
    "BaseGuardrail",
    "InputGuardrail",
    "OutputGuardrail",
    "DialogGuardrail",
    "RetrievalGuardrail",
    "ExecutionGuardrail",
    # Content Safety
    "ToxicityGuardrail",
    "ProfanityGuardrail",
    "HateSpeechGuardrail",
    "ViolenceGuardrail",
    "PIIGuardrail",
    "ContentSafetyGuardrail",
    "ContentSafetyConfig",
    # Jailbreak
    "JailbreakDetector",
    "PromptInjectionGuardrail",
    "RolePlayGuardrail",
    "EncodingGuardrail",
    "JailbreakPattern",
    # Topic
    "TopicGuardrail",
    "TopicDriftGuardrail",
    "TopicDefinition",
    "OffTopicAction",
    # Fact Check
    "FactCheckGuardrail",
    "GroundingGuardrail",
    "HallucinationGuardrail",
    "Claim",
    # Policy
    "PolicyGuardrail",
    "Policy",
    "PolicyRule",
    "SemanticPolicyGuardrail",
    "ConditionalPolicyGuardrail",
    "ConditionalPolicy",
    # Moderation
    "ModerationGuardrail",
    "OutputModerationGuardrail",
    "ContentFilter",
    "ContentFilterConfig",
    # Rail
    "Rail",
    "RailParser",
    "RailValidator",
    "RailGuardrailSpec",
    "ValidationResult",
    "ValidationError",
    # Engine
    "GuardrailEngine",
    # Middleware
    "GuardrailMiddleware",
    "GuardedExecutionResult",
    "GuardedContext",
    "GuardrailChain",
    "guarded",
]
