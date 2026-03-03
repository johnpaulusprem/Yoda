"""Document management service with RAG ingestion pipeline integration."""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cxo_ai_companion.models.document import Document, DocumentChunk
from cxo_ai_companion.rag.chunking.base_chunker import BaseChunker
from cxo_ai_companion.rag.embeddings.base_embedder import BaseEmbedder
from cxo_ai_companion.rag.ingestion.base_loader import LoadedDocument
from cxo_ai_companion.rag.pipeline.ingestion_pipeline import (
    IngestionPipeline,
    IngestionResult,
)
from cxo_ai_companion.rag.vectorstore.base_vectorstore import BaseVectorStore

logger = logging.getLogger(__name__)

# Mapping of MIME type prefixes → loader class names
_LOADER_MAP: dict[str, str] = {
    "application/pdf": "PDFLoader",
    "application/vnd.openxmlformats-officedocument.wordprocessingml": "DOCXLoader",
    "application/vnd.openxmlformats-officedocument.presentationml": "PPTXLoader",
    "text/html": "HTMLLoader",
    "text/csv": "CSVLoader",
    "message/rfc822": "EmailLoader",
}


def _select_loader(content_type: str | None) -> Any:
    """Select the appropriate document loader based on MIME type."""
    if not content_type:
        return None
    from cxo_ai_companion.rag.ingestion import (
        CSVLoader,
        DOCXLoader,
        EmailLoader,
        HTMLLoader,
        PDFLoader,
        PPTXLoader,
    )

    loader_map = {
        "PDFLoader": PDFLoader,
        "DOCXLoader": DOCXLoader,
        "PPTXLoader": PPTXLoader,
        "HTMLLoader": HTMLLoader,
        "CSVLoader": CSVLoader,
        "EmailLoader": EmailLoader,
    }
    for prefix, loader_name in _LOADER_MAP.items():
        if content_type.startswith(prefix):
            loader_cls = loader_map.get(loader_name)
            if loader_cls:
                return loader_cls()
    return None


class DocumentService:
    """Manages documents linked to meetings with full RAG ingestion pipeline.

    Handles syncing documents from Graph API (SharePoint/OneDrive), extracting
    text via format-specific loaders, chunking, embedding, and storing vectors
    for retrieval-augmented generation.

    Args:
        graph_connector: GraphClient for fetching user documents from OneDrive.
        db_session_factory: Async session factory for document persistence.
        ingestion_pipeline: Optional RAG ingestion pipeline (chunk, embed, store).
            Document processing is skipped if None.
    """

    def __init__(
        self,
        graph_connector: Any,
        db_session_factory: async_sessionmaker[AsyncSession],
        ingestion_pipeline: IngestionPipeline | None = None,
    ) -> None:
        self._graph = graph_connector
        self._session_factory = db_session_factory
        self._ingestion = ingestion_pipeline

    async def get_meeting_documents(self, meeting_id: UUID) -> list[Document]:
        """Retrieve all documents associated with a meeting.

        Args:
            meeting_id: UUID of the meeting.

        Returns:
            List of Document instances linked to the meeting.
        """
        async with self._session_factory() as db:
            result = await db.execute(
                select(Document).where(Document.meeting_id == meeting_id)
            )
            return list(result.scalars().all())

    async def get_user_documents(
        self, user_id: str, limit: int = 20
    ) -> list[Document]:
        """Retrieve documents uploaded by a user, most recent first.

        Args:
            user_id: Azure AD user ID of the document owner.
            limit: Maximum number of documents to return.

        Returns:
            List of Document instances ordered by creation date descending.
        """
        async with self._session_factory() as db:
            result = await db.execute(
                select(Document)
                .where(Document.uploaded_by == user_id)
                .order_by(Document.created_at.desc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def sync_from_graph(self, user_id: str) -> list[Document]:
        """Pull recent documents from Graph API (SharePoint/OneDrive).

        Fetches the user's recent OneDrive items and persists any new ones
        as Document records with status ``pending``.

        Args:
            user_id: Azure AD user ID whose documents to sync.

        Returns:
            List of newly created Document instances.
        """
        graph_docs = await self._graph.get_user_documents(user_id, limit=10)
        docs = []
        async with self._session_factory() as db:
            for gd in graph_docs:
                existing = await db.execute(
                    select(Document).where(
                        Document.source_url == gd.get("webUrl", "")
                    )
                )
                if existing.scalar_one_or_none():
                    continue
                doc = Document(
                    title=gd.get("name", "Untitled"),
                    source="onedrive",
                    source_url=gd.get("webUrl", ""),
                    content_type=gd.get("file", {}).get("mimeType", ""),
                    file_size_bytes=gd.get("size", 0),
                    uploaded_by=user_id,
                    status="pending",
                )
                db.add(doc)
                docs.append(doc)
            await db.commit()
        return docs

    async def process_document(self, document_id: UUID) -> IngestionResult | None:
        """Extract text and ingest a document into the RAG vector store.

        Selects a format-specific loader based on MIME type, extracts text,
        runs the ingestion pipeline (chunk, embed, store), and updates status.

        Args:
            document_id: UUID of the Document record to process.

        Returns:
            IngestionResult with chunk/vector counts, or None if the
            document is not found or has an unsupported content type.

        Raises:
            Exception: Re-raised after marking the document as ``failed``.
        """
        async with self._session_factory() as db:
            result = await db.execute(
                select(Document).where(Document.id == document_id)
            )
            doc = result.scalar_one_or_none()
            if doc is None:
                logger.warning("Document %s not found", document_id)
                return None

            try:
                # Select loader based on content type
                loader = _select_loader(doc.content_type)
                if loader is None:
                    # Fallback: treat as plain text if we have extracted_text
                    if doc.extracted_text:
                        text = doc.extracted_text
                    else:
                        doc.status = "failed"
                        await db.commit()
                        logger.warning(
                            "No loader for content type %s", doc.content_type
                        )
                        return None
                else:
                    # Load from source URL or existing extracted text
                    source = doc.source_url or ""
                    loaded_docs: list[LoadedDocument] = await loader.load(source)
                    text = "\n\n".join(ld.content for ld in loaded_docs)

                # Store extracted text
                doc.extracted_text = text

                # Run ingestion pipeline if available
                ingestion_result: IngestionResult | None = None
                if self._ingestion is not None:
                    metadata = {
                        "document_id": str(document_id),
                        "title": doc.title,
                        "source": doc.source,
                        "content_type": doc.content_type or "",
                    }
                    ingestion_result = await self._ingestion.ingest_text(
                        document_id=str(document_id),
                        text=text,
                        metadata=metadata,
                    )
                    doc.embedding_id = str(document_id)
                    logger.info(
                        "Document %s ingested: %d chunks, %d vectors",
                        document_id,
                        ingestion_result.chunks_created,
                        ingestion_result.vectors_stored,
                    )

                doc.status = "processed"
                await db.commit()
                logger.info("Document %s processed successfully", document_id)
                return ingestion_result

            except Exception:
                doc.status = "failed"
                await db.commit()
                logger.exception("Failed to process document %s", document_id)
                raise

    async def process_meeting_transcript(
        self,
        meeting_id: UUID,
        transcript_text: str,
        meeting_subject: str = "",
    ) -> IngestionResult | None:
        """Index a meeting transcript into the RAG vector store.

        Args:
            meeting_id: UUID of the meeting whose transcript to index.
            transcript_text: Full transcript text to chunk and embed.
            meeting_subject: Meeting subject for metadata tagging.

        Returns:
            IngestionResult with chunk counts, or None if the pipeline
            is not configured.
        """
        if self._ingestion is None:
            logger.warning("Ingestion pipeline not configured, skipping transcript")
            return None

        metadata = {
            "meeting_id": str(meeting_id),
            "source": "meeting_transcript",
            "subject": meeting_subject,
        }
        result = await self._ingestion.ingest_text(
            document_id=f"meeting-{meeting_id}",
            text=transcript_text,
            metadata=metadata,
        )
        logger.info(
            "Meeting %s transcript indexed: %d chunks",
            meeting_id,
            result.chunks_created,
        )
        return result

    async def search_documents(
        self,
        query: str,
        k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Perform semantic search across indexed documents via the retriever.

        Args:
            query: Natural language search query.
            k: Maximum number of results to return.
            filters: Optional metadata filters for scoping results.

        Returns:
            List of dicts with id, content, score, and metadata fields.
        """
        from cxo_ai_companion.rag.retrieval.base_retriever import RetrievalResult

        # Import lazily to avoid circular imports at module scope
        from cxo_ai_companion.dependencies import get_retriever

        retriever = get_retriever()
        retrieval_result: RetrievalResult = await retriever.retrieve(
            query=query, k=k, filters=filters
        )
        return [
            {
                "id": doc.id,
                "content": doc.content,
                "score": doc.score,
                "metadata": doc.metadata,
            }
            for doc in retrieval_result.documents
        ]
