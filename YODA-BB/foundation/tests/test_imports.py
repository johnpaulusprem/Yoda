"""Smoke test: verify all top-level foundation modules can be imported."""

import importlib
import pytest


MODULES_TO_CHECK = [
    # Core
    "yoda_foundation",
    "yoda_foundation.exceptions",
    "yoda_foundation.exceptions.base",
    "yoda_foundation.exceptions.dspy",
    "yoda_foundation.exceptions.memory",
    "yoda_foundation.exceptions.guardrails",
    "yoda_foundation.exceptions.resilience",
    "yoda_foundation.exceptions.events",
    "yoda_foundation.exceptions.data_access",
    "yoda_foundation.exceptions.observability",
    "yoda_foundation.exceptions.auth",
    # Models
    "yoda_foundation.models",
    "yoda_foundation.models.base",
    "yoda_foundation.models.meeting",
    "yoda_foundation.models.document",
    "yoda_foundation.models.chat",
    "yoda_foundation.models.action_item",
    "yoda_foundation.models.summary",
    "yoda_foundation.models.transcript",
    "yoda_foundation.models.subscription",
    "yoda_foundation.models.insight",
    "yoda_foundation.models.notification",
    "yoda_foundation.models.project",
    # Schemas
    "yoda_foundation.schemas",
    "yoda_foundation.schemas.meeting",
    "yoda_foundation.schemas.chat",
    "yoda_foundation.schemas.dashboard",
    "yoda_foundation.schemas.document",
    "yoda_foundation.schemas.action_item",
    "yoda_foundation.schemas.pre_meeting_brief",
    # Config
    "yoda_foundation.config",
    "yoda_foundation.config.settings",
    # RAG
    "yoda_foundation.rag",
    "yoda_foundation.rag.chunking",
    "yoda_foundation.rag.chunking.base_chunker",
    "yoda_foundation.rag.chunking.recursive_chunker",
    "yoda_foundation.rag.embeddings",
    "yoda_foundation.rag.embeddings.base_embedder",
    "yoda_foundation.rag.retrieval",
    "yoda_foundation.rag.retrieval.base_retriever",
    "yoda_foundation.rag.context",
    "yoda_foundation.rag.context.context_builder",
    "yoda_foundation.rag.context.citation_tracker",
    "yoda_foundation.rag.retrieval.hybrid_retriever",
    "yoda_foundation.rag.retrieval.reranker",
    "yoda_foundation.rag.retrieval.query_expander",
    "yoda_foundation.rag.evaluation",
    "yoda_foundation.rag.evaluation.evaluator",
    "yoda_foundation.rag.evaluation.golden_qa",
    "yoda_foundation.rag.pipeline",
    # DSPy
    "yoda_foundation.dspy",
    "yoda_foundation.dspy.schemas",
    "yoda_foundation.dspy.adapters",
    "yoda_foundation.dspy.modules",
    "yoda_foundation.dspy.signatures",
    "yoda_foundation.dspy.integration",
    # Security (dhurunthur)
    "yoda_foundation.security",
    "yoda_foundation.security.context",
    # Resilience (dhurunthur)
    "yoda_foundation.resilience",
    "yoda_foundation.resilience.retry",
    "yoda_foundation.resilience.circuit_breaker",
    "yoda_foundation.resilience.bulkhead",
    "yoda_foundation.resilience.fallback",
    "yoda_foundation.resilience.health",
    "yoda_foundation.resilience.timeout",
    "yoda_foundation.resilience.recovery",
    "yoda_foundation.resilience.dead_letter",
    # Observability (dhurunthur)
    "yoda_foundation.observability",
    "yoda_foundation.observability.config",
    "yoda_foundation.observability.logging",
    "yoda_foundation.observability.metrics",
    "yoda_foundation.observability.spans",
    # Guardrails (dhurunthur)
    "yoda_foundation.guardrails",
    "yoda_foundation.guardrails.schemas",
    "yoda_foundation.guardrails.base",
    "yoda_foundation.guardrails.engine",
    # Events (dhurunthur)
    "yoda_foundation.events",
    "yoda_foundation.events.bus",
    "yoda_foundation.events.bus.event_bus",
    "yoda_foundation.events.bus.in_memory_bus",
    "yoda_foundation.events.handlers",
    "yoda_foundation.events.schemas",
    "yoda_foundation.events.streaming",
    "yoda_foundation.events.triggers",
    "yoda_foundation.events.monitoring",
    "yoda_foundation.events.sourcing",
    # Memory (dhurunthur)
    "yoda_foundation.memory",
    "yoda_foundation.memory.schemas",
    "yoda_foundation.memory.base_tier",
    "yoda_foundation.memory.manager",
    "yoda_foundation.memory.consolidation",
    "yoda_foundation.memory.decay",
    "yoda_foundation.memory.context",
    "yoda_foundation.memory.tiers",
    "yoda_foundation.memory.graph_memory",
    # Utils
    "yoda_foundation.utils",
    "yoda_foundation.utils.auth",
    "yoda_foundation.utils.caching",
    "yoda_foundation.utils.retry",
    # Middleware
    "yoda_foundation.middleware",
    "yoda_foundation.middleware.correlation_id",
    "yoda_foundation.middleware.error_handler",
    "yoda_foundation.middleware.rate_limiter",
    "yoda_foundation.middleware.security_headers",
    # Data access
    "yoda_foundation.data_access",
    "yoda_foundation.data_access.base",
    "yoda_foundation.data_access.connectors",
    "yoda_foundation.data_access.repositories",
    "yoda_foundation.data_access.registry",
]


@pytest.mark.parametrize("module_name", MODULES_TO_CHECK)
def test_import(module_name: str) -> None:
    """Each foundation module should import without errors."""
    mod = importlib.import_module(module_name)
    assert mod is not None


def test_version() -> None:
    import yoda_foundation
    assert yoda_foundation.__version__ == "1.0.0"


def test_yoda_base_exception() -> None:
    from yoda_foundation.exceptions.base import YodaBaseException
    assert issubclass(YodaBaseException, Exception)


def test_models_have_base() -> None:
    from yoda_foundation.models.base import Base
    assert hasattr(Base, "metadata")
