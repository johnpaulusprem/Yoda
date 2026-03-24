"""
Multi-tier memory system for the Agentic AI Component Library.

Provides a production-ready memory system with four tiers (Working,
Episodic, Semantic, Procedural), configurable context building, memory
consolidation, and importance decay management.

Architecture:
    The memory system is organized in tiers, each serving a distinct purpose:

    - **Working Memory**: Short-lived, auto-expiring task context
    - **Episodic Memory**: Time-ordered event and experience storage
    - **Semantic Memory**: Knowledge-based storage with vector similarity search
    - **Procedural Memory**: Skill and procedure storage with tag-based retrieval

    The MemoryManager orchestrates all tiers through a unified API.

Example:
    ```python
    from yoda_foundation.memory import (
        ContextConfig,
        ContextStrategy,
        MemoryContent,
        MemoryEntry,
        MemoryManager,
        MemoryScope,
        MemoryTier,
        SearchFilter,
    )
    from yoda_foundation.memory.tiers import (
        WorkingMemoryTier,
        EpisodicMemoryTier,
        SemanticMemoryTier,
        ProceduralMemoryTier,
    )

    # Set up the manager with all tiers
    manager = MemoryManager(
        tiers={
            MemoryTier.WORKING: WorkingMemoryTier(),
            MemoryTier.EPISODIC: EpisodicMemoryTier(),
            MemoryTier.SEMANTIC: SemanticMemoryTier(),
            MemoryTier.PROCEDURAL: ProceduralMemoryTier(),
        },
        context_config=ContextConfig(
            strategy=ContextStrategy.HYBRID,
            max_tokens=4096,
        ),
    )
    await manager.initialize(security_context)

    # Store a memory
    entry = MemoryEntry.create(
        tier=MemoryTier.SEMANTIC,
        scope=MemoryScope.USER,
        content=MemoryContent(content="User prefers Python"),
        importance=0.8,
        tags=["preference", "language"],
    )
    result = await manager.store(entry, security_context)

    # Search memories
    results = await manager.search(
        "programming preferences",
        SearchFilter(limit=10),
        security_context,
    )

    # Build context for agent
    context = await manager.get_context(
        "What languages does the user prefer?",
        security_context,
    )

    # Cleanup
    await manager.close(security_context)
    ```
"""

from __future__ import annotations

from yoda_foundation.memory.base_tier import BaseTier
from yoda_foundation.memory.consolidation import (
    ConsolidationEngine,
    EmbeddingClient,
    LLMClient,
)
from yoda_foundation.memory.context import ContextBuilder, ContextConfig
from yoda_foundation.memory.decay import (
    AccessBasedDecay,
    DecayManager,
    DecayStrategy,
    HybridDecay,
    TierSpecificDecay,
    TimeBasedDecay,
)
from yoda_foundation.memory.manager import MemoryManager
from yoda_foundation.memory.schemas import (
    ConsolidationResult,
    ConsolidationStrategy,
    ContextResult,
    ContextStrategy,
    MemoryContent,
    MemoryEntry,
    MemoryScope,
    MemoryStats,
    MemoryTier,
    SearchFilter,
    SearchResult,
    StoreResult,
)


__all__ = [
    # Core manager
    "MemoryManager",
    # Base tier
    "BaseTier",
    # Schemas and enums
    "MemoryTier",
    "MemoryScope",
    "ContextStrategy",
    "ConsolidationStrategy",
    "MemoryContent",
    "MemoryEntry",
    "SearchFilter",
    "SearchResult",
    "StoreResult",
    "ConsolidationResult",
    "ContextResult",
    "MemoryStats",
    # Context
    "ContextBuilder",
    "ContextConfig",
    # Consolidation
    "ConsolidationEngine",
    "EmbeddingClient",
    "LLMClient",
    # Decay
    "DecayManager",
    "DecayStrategy",
    "TimeBasedDecay",
    "AccessBasedDecay",
    "HybridDecay",
    "TierSpecificDecay",
]
