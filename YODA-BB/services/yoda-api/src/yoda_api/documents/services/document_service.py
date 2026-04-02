"""Document management service with RAG ingestion pipeline integration."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yoda_foundation.models.document import Document, DocumentChunk
from yoda_foundation.rag.chunking.base_chunker import BaseChunker
from yoda_foundation.rag.embeddings.base_embedder import BaseEmbedder
from yoda_foundation.rag.ingestion.base_loader import LoadedDocument
from yoda_foundation.rag.pipeline.ingestion_pipeline import (
    IngestionPipeline,
    IngestionResult,
)
from yoda_foundation.rag.vectorstore.base_vectorstore import BaseVectorStore

logger = logging.getLogger(__name__)

# Mapping of MIME type prefixes -> loader class names
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
    from yoda_foundation.rag.ingestion import (
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

        Fetches the user's recent OneDrive items via ``get_sharepoint_recent``
        and persists any new ones as Document records with status ``pending``.
        Sets folder_path, page_count, and last_modified_by from the Graph response.

        Args:
            user_id: Azure AD user ID whose documents to sync.

        Returns:
            List of newly created Document instances.
        """
        graph_docs = await self._graph.get_sharepoint_recent(user_id, limit=20)
        docs: list[Document] = []
        async with self._session_factory() as db:
            for gd in graph_docs:
                web_url = gd.get("webUrl", "")
                graph_id = gd.get("id", "")

                # Skip if already synced (check by source_url or graph_item_id)
                existing = await db.execute(
                    select(Document).where(
                        or_(
                            Document.source_url == web_url,
                            Document.graph_item_id == graph_id,
                        )
                    )
                )
                if existing.scalar_one_or_none():
                    continue

                # Extract folder path from parentReference.path
                parent_ref = gd.get("parentReference", {})
                folder_path = parent_ref.get("path", "")
                # Strip the drive prefix (e.g. "/drive/root:/Sales/Pipeline" -> "Sales/Pipeline")
                if ":/" in folder_path:
                    folder_path = folder_path.split(":/", 1)[1]

                # Extract last modified by display name
                last_modified_by_obj = gd.get("lastModifiedBy", {})
                last_modified_by = last_modified_by_obj.get("user", {}).get("displayName", "")

                # Extract page count from file properties if available
                file_info = gd.get("file", {})
                page_count = file_info.get("pageCount")

                doc = Document(
                    title=gd.get("name", "Untitled"),
                    source="onedrive",
                    source_url=web_url,
                    content_type=file_info.get("mimeType", ""),
                    file_size_bytes=gd.get("size", 0),
                    uploaded_by=user_id,
                    status="pending",
                    graph_item_id=graph_id or None,
                    folder_path=folder_path or None,
                    page_count=page_count,
                    last_modified_by=last_modified_by or None,
                )
                db.add(doc)
                docs.append(doc)
            await db.commit()
        return docs

    # -- Type filter mapping ---------------------------------------------------
    _TYPE_MAP: dict[str, list[str]] = {
        "presentations": [
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "application/vnd.ms-powerpoint",
        ],
        "spreadsheets": [
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-excel",
        ],
        "documents": [
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/msword",
        ],
        "pdfs": [
            "application/pdf",
        ],
    }

    async def get_shared_with_me(self, user_id: str) -> list[Document]:
        """Fetch documents shared with the user via Graph API.

        Calls ``graph.get_shared_with_me()``, creates or updates Document records
        with shared_by, shared_at, and review_status='pending_review'.

        Args:
            user_id: Azure AD user ID.

        Returns:
            List of Document instances representing shared items.
        """
        shared_items = await self._graph.get_shared_with_me(user_id)
        docs: list[Document] = []
        async with self._session_factory() as db:
            for item in shared_items:
                # Shared items may be wrapped in a remoteItem
                remote = item.get("remoteItem", item)
                web_url = remote.get("webUrl", item.get("webUrl", ""))
                graph_id = remote.get("id", item.get("id", ""))

                # Check for existing document
                existing_result = await db.execute(
                    select(Document).where(
                        or_(
                            Document.source_url == web_url,
                            Document.graph_item_id == graph_id,
                        )
                    )
                )
                existing_doc = existing_result.scalar_one_or_none()
                if existing_doc is not None:
                    docs.append(existing_doc)
                    continue

                # Extract sharer info
                shared_by_obj = remote.get("shared", item.get("shared", {}))
                shared_by_user = shared_by_obj.get("sharedBy", {}).get("user", {})
                shared_by_name = shared_by_user.get("displayName", "")
                shared_datetime_str = shared_by_obj.get("sharedDateTime")
                shared_at = None
                if shared_datetime_str:
                    try:
                        shared_at = datetime.fromisoformat(shared_datetime_str.replace("Z", "+00:00"))
                    except (ValueError, AttributeError):
                        shared_at = None

                file_info = remote.get("file", item.get("file", {}))

                doc = Document(
                    title=remote.get("name", item.get("name", "Untitled")),
                    source="sharepoint",
                    source_url=web_url,
                    content_type=file_info.get("mimeType", ""),
                    file_size_bytes=remote.get("size", item.get("size", 0)),
                    uploaded_by=user_id,
                    status="pending",
                    review_status="pending_review",
                    shared_by=shared_by_name or None,
                    shared_at=shared_at,
                    graph_item_id=graph_id or None,
                )
                db.add(doc)
                docs.append(doc)
            await db.commit()
        return docs

    async def get_needs_review(self, user_id: str) -> list[Document]:
        """Get documents that need the user's review.

        Queries the DB for documents with review_status in
        ('pending_review', 'action_required') that were shared with the user
        (shared_by is set or uploaded_by differs from user_id).
        Results are ordered by priority (high first), then shared_at descending.

        Args:
            user_id: Azure AD user ID.

        Returns:
            Ordered list of Document instances awaiting review.
        """
        # Define priority ordering: high=1, medium=2, low=3, None=4
        from sqlalchemy import case

        priority_order = case(
            (Document.priority == "high", 1),
            (Document.priority == "medium", 2),
            (Document.priority == "low", 3),
            else_=4,
        )

        async with self._session_factory() as db:
            result = await db.execute(
                select(Document)
                .where(
                    Document.review_status.in_(["pending_review", "action_required"]),
                    or_(
                        Document.shared_by.isnot(None),
                        Document.uploaded_by != user_id,
                    ),
                )
                .order_by(priority_order, Document.shared_at.desc().nullslast())
            )
            return list(result.scalars().all())

    async def get_meeting_documents_for_today(self, user_id: str) -> list[dict[str, Any]]:
        """Cross-reference today's calendar events with documents.

        1. Gets today's calendar events from Graph API.
        2. For each event, checks for attached files.
        3. Also queries local DB for documents linked to matching meeting IDs.

        Args:
            user_id: Azure AD user ID.

        Returns:
            List of dicts, each containing ``meeting_subject``, ``meeting_time``,
            and ``documents`` (list of Document-like dicts).
        """
        now = datetime.now(UTC)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)

        events = await self._graph.get_calendar_events(
            user_id,
            start=start_of_day.isoformat(),
            end=end_of_day.isoformat(),
        )

        results: list[dict[str, Any]] = []

        async with self._session_factory() as db:
            for event in events:
                event_id = event.get("id", "")
                subject = event.get("subject", "Untitled Meeting")
                start_time = event.get("start", {}).get("dateTime", "")

                meeting_docs: list[dict[str, Any]] = []

                # Fetch attachments from the calendar event via Graph
                try:
                    attachments = await self._graph.get_meeting_attachments(
                        user_id, event_id
                    )
                    for att in attachments:
                        meeting_docs.append({
                            "title": att.get("name", "Attachment"),
                            "source": "email_attachment",
                            "content_type": att.get("contentType", ""),
                            "file_size_bytes": att.get("size", 0),
                        })
                except Exception:
                    logger.warning(
                        "Failed to fetch attachments for event %s", event_id
                    )

                # Query local DB for documents linked to meetings with matching subject
                from yoda_foundation.models.meeting import Meeting

                meeting_result = await db.execute(
                    select(Meeting.id).where(
                        Meeting.subject == subject,
                        Meeting.scheduled_start >= start_of_day,
                        Meeting.scheduled_start < end_of_day,
                    )
                )
                meeting_ids = [row[0] for row in meeting_result.all()]

                if meeting_ids:
                    doc_result = await db.execute(
                        select(Document).where(
                            Document.meeting_id.in_(meeting_ids)
                        )
                    )
                    for doc in doc_result.scalars().all():
                        meeting_docs.append({
                            "title": doc.title,
                            "source": doc.source,
                            "content_type": doc.content_type,
                            "file_size_bytes": doc.file_size_bytes,
                            "source_url": doc.source_url,
                            "id": str(doc.id),
                        })

                results.append({
                    "meeting_subject": subject,
                    "meeting_time": start_time,
                    "documents": meeting_docs,
                    "total": len(meeting_docs),
                })

        return results

    async def get_recently_updated(
        self,
        user_id: str,
        doc_type: str | None = None,
        limit: int = 20,
    ) -> list[Document]:
        """Get recently updated documents, optionally filtered by type.

        Args:
            user_id: Azure AD user ID (for scoping).
            doc_type: Optional filter key: 'presentations', 'spreadsheets',
                'documents', or 'pdfs'. Maps to MIME type filters.
            limit: Maximum results to return.

        Returns:
            List of Document instances ordered by updated_at descending.
        """
        async with self._session_factory() as db:
            query = select(Document).order_by(Document.updated_at.desc()).limit(limit)

            if doc_type and doc_type in self._TYPE_MAP:
                mime_types = self._TYPE_MAP[doc_type]
                query = query.where(Document.content_type.in_(mime_types))

            result = await db.execute(query)
            return list(result.scalars().all())

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

                # Auto-classify the document
                try:
                    from yoda_api.dependencies import get_document_classifier

                    classifier = get_document_classifier()
                    classification = await classifier.classify_file(
                        text=text[:5000],  # limit text for classification perf
                        filename=doc.title,
                        content_type=doc.content_type,
                    )
                    doc.category = classification.category
                    doc.classification_confidence = classification.confidence
                    doc.priority = classification.suggested_priority
                    doc.suggested_tags = classification.suggested_tags
                    logger.info(
                        "Document %s classified as %s (%.2f)",
                        document_id,
                        classification.category,
                        classification.confidence,
                    )
                except Exception:
                    logger.warning(
                        "Auto-classification failed for document %s", document_id,
                        exc_info=True,
                    )

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

    async def index_emails(
        self, user_id: str, days: int = 7, limit: int = 50
    ) -> list[Document]:
        """Fetch recent emails from Microsoft Graph and index them as documents.

        1. Calls Graph API to get recent emails for the user.
        2. De-duplicates against existing documents by ``source_url``.
        3. Creates Document records with ``source='email'``.
        4. Runs through the ingestion pipeline (chunk + embed) if available.

        Args:
            user_id: Azure AD user ID whose mailbox to index.
            days: How many days back to fetch.
            limit: Maximum number of emails to index per call.

        Returns:
            List of newly created Document instances.

        Raises:
            RuntimeError: If the Graph connector is not configured.
        """
        if self._graph is None:
            raise RuntimeError(
                "Graph connector not configured; cannot fetch emails."
            )

        emails = await self._graph.get_user_emails(user_id, days=days)

        indexed: list[Document] = []
        async with self._session_factory() as db:
            for email in emails[:limit]:
                web_link = email.get("webLink", "")

                # Skip if already indexed (deduplicate by source_url)
                existing = await db.execute(
                    select(Document).where(Document.source_url == web_link)
                )
                if existing.scalar_one_or_none():
                    continue

                # Extract email content
                subject = email.get("subject", "No Subject")
                body_content = email.get("body", {}).get("content", "")
                sender = (
                    email.get("from", {})
                    .get("emailAddress", {})
                    .get("name", "Unknown")
                )
                received = email.get("receivedDateTime", "")

                # Strip HTML tags from body (basic sanitisation)
                clean_body = re.sub(r"<[^>]+>", "", body_content).strip()

                if not clean_body or len(clean_body) < 20:
                    continue

                doc = Document(
                    title=f"Email: {subject}",
                    source="email",
                    source_url=web_link,
                    content_type="message/rfc822",
                    extracted_text=(
                        f"From: {sender}\n"
                        f"Subject: {subject}\n"
                        f"Date: {received}\n\n"
                        f"{clean_body}"
                    ),
                    uploaded_by=user_id,
                    status="pending",
                )
                db.add(doc)
                indexed.append(doc)

            await db.commit()

        # Run ingestion pipeline for each indexed email
        if self._ingestion and indexed:
            for doc in indexed:
                try:
                    await self._ingestion.ingest_text(
                        document_id=str(doc.id),
                        text=doc.extracted_text,
                        metadata={
                            "document_id": str(doc.id),
                            "title": doc.title,
                            "source": "email",
                            "content_type": "message/rfc822",
                        },
                    )
                    doc.status = "processed"
                    logger.info("Indexed email: %s", doc.title)
                except Exception:
                    logger.warning(
                        "Failed to index email: %s", doc.title, exc_info=True
                    )

        logger.info("Indexed %d emails for user %s", len(indexed), user_id)
        return indexed

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
        from yoda_foundation.rag.retrieval.base_retriever import RetrievalResult

        from yoda_api.dependencies import get_retriever

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
