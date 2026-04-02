"""RAG (Retrieval-Augmented Generation) foundation layer.

Provides embeddings, vector storage, document chunking, retrieval,
and context-building capabilities for the CXO AI Companion knowledge pipeline.
"""

from __future__ import annotations

from yoda_foundation.rag.chunking import (
    BaseChunker,
    Chunk,
    ChunkerConfig,
    ChunkMetadata,
    RecursiveChunker,
    RecursiveChunkerConfig,
)
from yoda_foundation.rag.context import (
    Citation,
    CitationTracker,
    ContextBuilder,
    ContextChunk,
    ContextConfig,
    RetrievalContext,
    SourceReference,
)
from yoda_foundation.rag.embeddings import (
    AzureEmbedder,
    AzureEmbedderConfig,
    BaseEmbedder,
    EmbedderConfig,
    EmbeddingResult,
)
from yoda_foundation.rag.evaluation import (
    EvalCase,
    EvalMetrics,
    GOLDEN_QA_CASES,
    RAGEvaluator,
)
from yoda_foundation.rag.retrieval import (
    BaseRetriever,
    HybridRetriever,
    HybridRetrieverConfig,
    LLMReranker,
    QueryExpander,
    QueryExpanderConfig,
    RerankerConfig,
    RetrievalResult,
    RetrievedDocument,
    SimilarityRetriever,
    SimilarityRetrieverConfig,
)
from yoda_foundation.rag.ingestion import (
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
from yoda_foundation.rag.pipeline import (
    IngestionConfig,
    IngestionPipeline,
    IngestionResult,
    RAGConfig,
    RAGPipeline,
    RAGResult,
)
from yoda_foundation.rag.vectorstore import (
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
    "HybridRetriever",
    "HybridRetrieverConfig",
    "LLMReranker",
    "RerankerConfig",
    "QueryExpander",
    "QueryExpanderConfig",
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
    # Evaluation
    "EvalCase",
    "EvalMetrics",
    "RAGEvaluator",
    "GOLDEN_QA_CASES",
]
