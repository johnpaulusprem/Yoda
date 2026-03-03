"""Embedding providers for the RAG pipeline."""

from __future__ import annotations

from cxo_ai_companion.rag.embeddings.azure_embedder import (
    AzureEmbedder,
    AzureEmbedderConfig,
)
from cxo_ai_companion.rag.embeddings.base_embedder import (
    BaseEmbedder,
    EmbedderConfig,
    EmbeddingResult,
)

__all__ = [
    "BaseEmbedder",
    "EmbedderConfig",
    "EmbeddingResult",
    "AzureEmbedder",
    "AzureEmbedderConfig",
]
