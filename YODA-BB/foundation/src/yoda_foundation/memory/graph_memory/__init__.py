"""
Graph memory module for Mem0-style auto-consolidation.

Provides components for extracting entities and relations from conversation
turns, linking memory entries to knowledge graph entities, and automatically
consolidating memories based on configurable thresholds and promotion rules.

Example:
    ```python
    from yoda_foundation.memory.graph_memory import (
        AutoConsolidationConfig,
        AutoConsolidator,
        Contradiction,
        ConversationMemoryExtractor,
        ConversationMemoryUpdate,
        MemoryKGLink,
        MemoryKGLinker,
    )
    ```
"""

from __future__ import annotations

from yoda_foundation.memory.graph_memory.auto_consolidator import (
    AutoConsolidationConfig,
    AutoConsolidator,
)
from yoda_foundation.memory.graph_memory.conversation_extractor import (
    Contradiction,
    ConversationMemoryExtractor,
    ConversationMemoryUpdate,
)
from yoda_foundation.memory.graph_memory.memory_linker import (
    MemoryKGLink,
    MemoryKGLinker,
)


__all__ = [
    "AutoConsolidationConfig",
    "AutoConsolidator",
    "Contradiction",
    "ConversationMemoryExtractor",
    "ConversationMemoryUpdate",
    "MemoryKGLink",
    "MemoryKGLinker",
]
