"""Document chunking strategies for the RAG pipeline."""

from __future__ import annotations

from cxo_ai_companion.rag.chunking.base_chunker import (
    BaseChunker,
    Chunk,
    ChunkerConfig,
    ChunkMetadata,
)
from cxo_ai_companion.rag.chunking.recursive_chunker import (
    RecursiveChunker,
    RecursiveChunkerConfig,
)

__all__ = [
    "BaseChunker",
    "ChunkerConfig",
    "ChunkMetadata",
    "Chunk",
    "RecursiveChunker",
    "RecursiveChunkerConfig",
]
