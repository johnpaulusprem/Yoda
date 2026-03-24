"""Ingestion pipeline — chunks, embeds, and stores documents in the vector store."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from yoda_foundation.rag.chunking.base_chunker import BaseChunker
from yoda_foundation.rag.embeddings.base_embedder import BaseEmbedder
from yoda_foundation.rag.ingestion.base_loader import LoadedDocument
from yoda_foundation.rag.vectorstore.base_vectorstore import BaseVectorStore, VectorDocument

logger = logging.getLogger(__name__)


@dataclass
class IngestionConfig:
    """Configuration for the ingestion pipeline.

    Attributes:
        batch_size: Number of chunks to embed per API call.
        store_raw_text: Whether to store the raw chunk text in vector metadata.
    """

    batch_size: int = 50
    store_raw_text: bool = True


@dataclass
class IngestionResult:
    """Aggregated statistics from an ingestion run.

    Attributes:
        documents_processed: Number of documents that were processed.
        chunks_created: Total chunks produced by the chunker.
        vectors_stored: Number of vectors successfully upserted.
        errors: Human-readable error messages from any failed stages.
        execution_time_ms: Total wall-clock time in milliseconds.
    """

    documents_processed: int
    chunks_created: int
    vectors_stored: int
    errors: list[str] = field(default_factory=list)
    execution_time_ms: float = 0.0


class IngestionPipeline:
    """Orchestrates document ingestion: chunking, embedding, and vector storage.

    The pipeline accepts raw text (or pre-loaded documents) and pushes them
    through three stages:

    1. **Chunking** — split text into smaller, overlapping chunks via a
       :class:`BaseChunker`.
    2. **Embedding** — convert chunk text into dense vectors via a
       :class:`BaseEmbedder`.
    3. **Storage** — upsert the resulting :class:`VectorDocument` objects into
       a :class:`BaseVectorStore`.
    """

    def __init__(
        self,
        chunker: BaseChunker,
        embedder: BaseEmbedder,
        vector_store: BaseVectorStore,
        config: IngestionConfig | None = None,
    ) -> None:
        """Initialize the ingestion pipeline.

        Args:
            chunker: Strategy for splitting document text into chunks.
            embedder: Provider for converting text chunks into vectors.
            vector_store: Backend store for upserting embedded chunks.
            config: Pipeline configuration. Defaults to ``IngestionConfig()``.
        """
        self._chunker = chunker
        self._embedder = embedder
        self._vector_store = vector_store
        self._config = config or IngestionConfig()

    async def ingest_text(
        self,
        document_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> IngestionResult:
        """Chunk, embed, and store a single document's text.

        Args:
            document_id: Unique identifier for the source document.
            text: The full document text to ingest.
            metadata: Optional extra metadata to attach to every chunk.

        Returns:
            An :class:`IngestionResult` with processing statistics.
        """
        start = time.perf_counter()
        errors: list[str] = []
        extra_metadata = metadata or {}

        # 1. Chunk the text
        try:
            chunks = self._chunker.chunk_document(document_id, text)
        except Exception as exc:
            logger.exception("Chunking failed for document %s", document_id)
            elapsed = (time.perf_counter() - start) * 1000
            return IngestionResult(
                documents_processed=0,
                chunks_created=0,
                vectors_stored=0,
                errors=[f"Chunking failed: {exc}"],
                execution_time_ms=elapsed,
            )

        if not chunks:
            elapsed = (time.perf_counter() - start) * 1000
            logger.warning("No chunks produced for document %s", document_id)
            return IngestionResult(
                documents_processed=1,
                chunks_created=0,
                vectors_stored=0,
                errors=[],
                execution_time_ms=elapsed,
            )

        # 2. Extract content strings and embed in batches
        content_strings = [chunk.content for chunk in chunks]
        all_vectors: list[list[float]] = []

        batch_size = self._config.batch_size
        for batch_start in range(0, len(content_strings), batch_size):
            batch = content_strings[batch_start : batch_start + batch_size]
            try:
                result = await self._embedder.embed_batch(batch)
                all_vectors.extend(result.vectors)
            except Exception as exc:
                logger.exception(
                    "Embedding batch %d-%d failed for document %s",
                    batch_start,
                    batch_start + len(batch),
                    document_id,
                )
                errors.append(
                    f"Embedding batch {batch_start}-{batch_start + len(batch)} "
                    f"failed: {exc}"
                )
                # Pad with empty vectors so indices stay aligned
                all_vectors.extend([[] for _ in batch])

        # 3. Build VectorDocument list
        vector_documents: list[VectorDocument] = []
        for chunk, vector in zip(chunks, all_vectors):
            if not vector:
                # Skip chunks whose embedding failed
                continue

            doc_metadata: dict[str, Any] = {
                "document_id": chunk.metadata.document_id,
                "chunk_index": chunk.metadata.chunk_index,
                "start_char": chunk.metadata.start_char,
                "end_char": chunk.metadata.end_char,
                "token_count": chunk.metadata.token_count,
                **extra_metadata,
            }
            if self._config.store_raw_text:
                doc_metadata["raw_text"] = chunk.content

            vector_documents.append(
                VectorDocument(
                    id=chunk.metadata.chunk_id,
                    vector=vector,
                    content=chunk.content,
                    metadata=doc_metadata,
                )
            )

        # 4. Upsert to vector store
        vectors_stored = 0
        if vector_documents:
            try:
                vectors_stored = await self._vector_store.upsert(vector_documents)
            except Exception as exc:
                logger.exception(
                    "Vector store upsert failed for document %s", document_id
                )
                errors.append(f"Vector store upsert failed: {exc}")

        elapsed = (time.perf_counter() - start) * 1000

        logger.info(
            "Ingested document %s: chunks=%d, stored=%d, errors=%d, time=%.1fms",
            document_id,
            len(chunks),
            vectors_stored,
            len(errors),
            elapsed,
        )

        return IngestionResult(
            documents_processed=1,
            chunks_created=len(chunks),
            vectors_stored=vectors_stored,
            errors=errors,
            execution_time_ms=elapsed,
        )

    async def ingest_loaded_documents(
        self,
        documents: list[LoadedDocument],
    ) -> IngestionResult:
        """Ingest a batch of pre-loaded documents.

        Iterates over each :class:`LoadedDocument`, calls :meth:`ingest_text`,
        and aggregates the results into a single :class:`IngestionResult`.

        Args:
            documents: The loaded documents to ingest.

        Returns:
            An aggregated :class:`IngestionResult` across all documents.
        """
        start = time.perf_counter()

        total_docs = 0
        total_chunks = 0
        total_stored = 0
        all_errors: list[str] = []

        for doc in documents:
            doc_metadata: dict[str, Any] = {
                "source": doc.source,
                "mime_type": doc.mime_type,
            }
            if doc.page_number is not None:
                doc_metadata["page_number"] = doc.page_number
            if doc.metadata.title:
                doc_metadata["title"] = doc.metadata.title

            result = await self.ingest_text(
                document_id=doc.document_id,
                text=doc.content,
                metadata=doc_metadata,
            )

            total_docs += result.documents_processed
            total_chunks += result.chunks_created
            total_stored += result.vectors_stored
            all_errors.extend(result.errors)

        elapsed = (time.perf_counter() - start) * 1000

        logger.info(
            "Batch ingestion complete: documents=%d, chunks=%d, stored=%d, "
            "errors=%d, time=%.1fms",
            total_docs,
            total_chunks,
            total_stored,
            len(all_errors),
            elapsed,
        )

        return IngestionResult(
            documents_processed=total_docs,
            chunks_created=total_chunks,
            vectors_stored=total_stored,
            errors=all_errors,
            execution_time_ms=elapsed,
        )


__all__ = [
    "IngestionConfig",
    "IngestionPipeline",
    "IngestionResult",
]
