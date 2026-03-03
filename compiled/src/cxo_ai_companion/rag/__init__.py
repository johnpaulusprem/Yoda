"""RAG (Retrieval-Augmented Generation) foundation layer.

Provides embeddings, vector storage, document chunking, retrieval,
and context-building capabilities for the CXO AI Companion knowledge pipeline.
"""

from __future__ import annotations

from cxo_ai_companion.rag.chunking import (
    BaseChunker,
    Chunk,
    ChunkerConfig,
    ChunkMetadata,
    RecursiveChunker,
    RecursiveChunkerConfig,
)
from cxo_ai_companion.rag.context import (
    Citation,
    CitationTracker,
    ContextBuilder,
    ContextChunk,
    ContextConfig,
    RetrievalContext,
    SourceReference,
)
from cxo_ai_companion.rag.embeddings import (
    AzureEmbedder,
    AzureEmbedderConfig,
    BaseEmbedder,
    EmbedderConfig,
    EmbeddingResult,
)
from cxo_ai_companion.rag.retrieval import (
    BaseRetriever,
    RetrievalResult,
    RetrievedDocument,
    SimilarityRetriever,
    SimilarityRetrieverConfig,
)
from cxo_ai_companion.rag.ingestion import (
    CSVLoader,
    DOCXLoader,
    DocumentLoader,
    EmailLoader,
    HTMLLoader,
    LoadedDocument,
    LoaderConfig,
    LoadMode,
    PDFLoader,
    PPTXLoader,
)
from cxo_ai_companion.rag.pipeline import (
    IngestionConfig,
    IngestionPipeline,
    IngestionResult,
    RAGConfig,
    RAGPipeline,
    RAGResult,
)
from cxo_ai_companion.rag.vectorstore import (
    BaseVectorStore,
    DistanceMetric,
    PGVectorConfig,
    PGVectorStore,
    VectorDocument,
    VectorSearchResult,
)

__all__ = [
    # Embeddings
    "BaseEmbedder",
    "EmbedderConfig",
    "EmbeddingResult",
    "AzureEmbedder",
    "AzureEmbedderConfig",
    # Vector store
    "BaseVectorStore",
    "VectorDocument",
    "VectorSearchResult",
    "DistanceMetric",
    "PGVectorStore",
    "PGVectorConfig",
    # Chunking
    "BaseChunker",
    "ChunkerConfig",
    "ChunkMetadata",
    "Chunk",
    "RecursiveChunker",
    "RecursiveChunkerConfig",
    # Retrieval
    "BaseRetriever",
    "RetrievedDocument",
    "RetrievalResult",
    "SimilarityRetriever",
    "SimilarityRetrieverConfig",
    # Context
    "ContextBuilder",
    "ContextConfig",
    "ContextChunk",
    "RetrievalContext",
    "CitationTracker",
    "SourceReference",
    "Citation",
    # Ingestion
    "DocumentLoader",
    "LoaderConfig",
    "LoadMode",
    "LoadedDocument",
    "PDFLoader",
    "DOCXLoader",
    "PPTXLoader",
    "HTMLLoader",
    "CSVLoader",
    "EmailLoader",
    # Pipeline
    "IngestionPipeline",
    "IngestionConfig",
    "IngestionResult",
    "RAGPipeline",
    "RAGConfig",
    "RAGResult",
]
