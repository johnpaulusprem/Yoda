"""Retrieval strategies for the RAG pipeline."""

from __future__ import annotations

from cxo_ai_companion.rag.retrieval.base_retriever import (
    BaseRetriever,
    RetrievalResult,
    RetrievedDocument,
)
from cxo_ai_companion.rag.retrieval.similarity_retriever import (
    SimilarityRetriever,
    SimilarityRetrieverConfig,
)

__all__ = [
    "BaseRetriever",
    "RetrievedDocument",
    "RetrievalResult",
    "SimilarityRetriever",
    "SimilarityRetrieverConfig",
]
