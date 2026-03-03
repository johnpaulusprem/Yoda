"""Vector store backends for the RAG pipeline."""

from __future__ import annotations

from cxo_ai_companion.rag.vectorstore.base_vectorstore import (
    BaseVectorStore,
    DistanceMetric,
    VectorDocument,
    VectorSearchResult,
)
from cxo_ai_companion.rag.vectorstore.pgvector_store import (
    PGVectorConfig,
    PGVectorStore,
)

__all__ = [
    "BaseVectorStore",
    "DistanceMetric",
    "VectorDocument",
    "VectorSearchResult",
    "PGVectorConfig",
    "PGVectorStore",
]
