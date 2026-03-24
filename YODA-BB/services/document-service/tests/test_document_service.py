"""Tests for document service routes and business logic."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient

from tests.conftest import FakeDocument


# ===========================================================================
# Health endpoint
# ===========================================================================

@pytest.mark.asyncio
async def test_health_endpoint(client: AsyncClient) -> None:
    """GET /health returns 200 with service name."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["service"] == "document-service"


# ===========================================================================
# Document list endpoint
# ===========================================================================

@pytest.mark.asyncio
async def test_list_documents(client: AsyncClient, mock_db_session: AsyncMock, fake_documents: list) -> None:
    """GET /api/documents returns a paginated list."""
    # Mock the DB execute result
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = fake_documents
    mock_result.scalars.return_value = mock_scalars
    mock_db_session.execute = AsyncMock(return_value=mock_result)

    # Patch model_validate to handle FakeDocument
    with patch("document_service.routes.documents.DocumentResponse") as MockDocResp:
        MockDocResp.model_validate.side_effect = lambda d: MagicMock(
            id=d.id,
            meeting_id=d.meeting_id,
            title=d.title,
            source=d.source,
            source_url=d.source_url,
            content_type=d.content_type,
            content_hash=d.content_hash,
            status=d.status,
            uploaded_by=d.uploaded_by,
            file_size_bytes=d.file_size_bytes,
            review_status=d.review_status,
            created_at=d.created_at,
            updated_at=d.updated_at,
        )
        with patch("document_service.routes.documents.DocumentListResponse") as MockListResp:
            MockListResp.return_value = MagicMock()
            MockListResp.return_value.model_dump.return_value = {
                "items": [{"title": "Doc A"}, {"title": "Doc B"}],
                "total": 2,
            }

            resp = await client.get("/api/documents")
            assert resp.status_code == 200


# ===========================================================================
# Get single document
# ===========================================================================

@pytest.mark.asyncio
async def test_get_document_found(client: AsyncClient, mock_db_session: AsyncMock, fake_document: FakeDocument) -> None:
    """GET /api/documents/{id} returns 200 when document exists."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = fake_document
    mock_db_session.execute = AsyncMock(return_value=mock_result)

    resp = await client.get(f"/api/documents/{fake_document.id}")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_get_document_not_found(client: AsyncClient, mock_db_session: AsyncMock) -> None:
    """GET /api/documents/{id} returns 404 when document does not exist."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db_session.execute = AsyncMock(return_value=mock_result)

    random_id = uuid.uuid4()
    resp = await client.get(f"/api/documents/{random_id}")
    assert resp.status_code == 404


# ===========================================================================
# Reprocess endpoint
# ===========================================================================

@pytest.mark.asyncio
async def test_reprocess_document_not_found(client: AsyncClient, mock_db_session: AsyncMock) -> None:
    """POST /api/documents/{id}/reprocess returns 404 when doc missing."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db_session.execute = AsyncMock(return_value=mock_result)

    random_id = uuid.uuid4()
    resp = await client.post(f"/api/documents/{random_id}/reprocess")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_reprocess_document_accepted(
    client: AsyncClient, mock_db_session: AsyncMock, fake_document: FakeDocument
) -> None:
    """POST /api/documents/{id}/reprocess returns 202 when doc exists."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = fake_document
    mock_db_session.execute = AsyncMock(return_value=mock_result)

    resp = await client.post(f"/api/documents/{fake_document.id}/reprocess")
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "reprocessing"
    assert data["document_id"] == str(fake_document.id)


# ===========================================================================
# DocumentService unit tests (business logic)
# ===========================================================================

@pytest.mark.asyncio
async def test_document_service_get_meeting_documents() -> None:
    """DocumentService.get_meeting_documents queries by meeting_id."""
    from document_service.services.document_service import DocumentService

    meeting_id = uuid.uuid4()
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [FakeDocument(meeting_id=meeting_id)]
    mock_result.scalars.return_value = mock_scalars
    mock_session.execute = AsyncMock(return_value=mock_result)

    # Create a mock session factory (MagicMock so calling it returns a sync
    # object with __aenter__/__aexit__, matching async_sessionmaker behaviour)
    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    service = DocumentService(
        graph_connector=None,
        db_session_factory=mock_factory,
        ingestion_pipeline=None,
    )

    docs = await service.get_meeting_documents(meeting_id)
    assert len(docs) == 1


@pytest.mark.asyncio
async def test_document_service_process_meeting_transcript_no_pipeline() -> None:
    """process_meeting_transcript returns None when pipeline is not configured."""
    from document_service.services.document_service import DocumentService

    mock_factory = AsyncMock()

    service = DocumentService(
        graph_connector=None,
        db_session_factory=mock_factory,
        ingestion_pipeline=None,
    )

    result = await service.process_meeting_transcript(
        meeting_id=uuid.uuid4(),
        transcript_text="Hello world",
    )
    assert result is None


@pytest.mark.asyncio
async def test_document_service_process_meeting_transcript_with_pipeline() -> None:
    """process_meeting_transcript calls ingest_text on the pipeline."""
    from document_service.services.document_service import DocumentService

    mock_factory = AsyncMock()
    mock_pipeline = AsyncMock()
    mock_ingestion_result = MagicMock()
    mock_ingestion_result.chunks_created = 5
    mock_ingestion_result.vectors_stored = 5
    mock_pipeline.ingest_text = AsyncMock(return_value=mock_ingestion_result)

    service = DocumentService(
        graph_connector=None,
        db_session_factory=mock_factory,
        ingestion_pipeline=mock_pipeline,
    )

    meeting_id = uuid.uuid4()
    result = await service.process_meeting_transcript(
        meeting_id=meeting_id,
        transcript_text="This is a meeting transcript",
        meeting_subject="Q4 Review",
    )

    assert result is not None
    assert result.chunks_created == 5
    mock_pipeline.ingest_text.assert_awaited_once()
    call_kwargs = mock_pipeline.ingest_text.call_args.kwargs
    assert call_kwargs["document_id"] == f"meeting-{meeting_id}"
    assert call_kwargs["metadata"]["source"] == "meeting_transcript"


# ===========================================================================
# NEW: Sync endpoint route test
# ===========================================================================

@pytest.mark.asyncio
async def test_sync_documents(
    client: AsyncClient,
    mock_document_service: AsyncMock,
) -> None:
    """POST /api/documents/sync triggers Graph sync and returns synced count."""
    new_doc = FakeDocument(title="New from Graph.pptx", source="onedrive")
    mock_document_service.sync_from_graph.return_value = [new_doc]

    with patch("document_service.routes.documents.DocumentResponse") as MockDocResp:
        mock_resp_obj = MagicMock()
        MockDocResp.model_validate.return_value = mock_resp_obj
        with patch("document_service.routes.documents.DocumentSyncResponse") as MockSyncResp:
            MockSyncResp.return_value = MagicMock()
            MockSyncResp.return_value.model_dump.return_value = {
                "synced": 1,
                "new_documents": [{"title": "New from Graph.pptx"}],
            }

            resp = await client.post("/api/documents/sync")
            assert resp.status_code == 200
            mock_document_service.sync_from_graph.assert_awaited_once_with("test-user-id")


# ===========================================================================
# NEW: Needs review route test
# ===========================================================================

@pytest.mark.asyncio
async def test_needs_review(
    client: AsyncClient,
    mock_document_service: AsyncMock,
) -> None:
    """GET /api/documents/needs-review returns docs awaiting review."""
    review_docs = [
        FakeDocument(
            title="Board Deck v3.pptx",
            review_status="pending_review",
            priority="high",
            shared_by="Priya Sharma",
        ),
        FakeDocument(
            title="Term Sheet.pdf",
            review_status="action_required",
            priority="medium",
            shared_by="Legal",
        ),
    ]
    mock_document_service.get_needs_review.return_value = review_docs

    with patch("document_service.routes.documents.DocumentResponse") as MockDocResp:
        MockDocResp.model_validate.side_effect = lambda d: MagicMock(
            title=d.title, review_status=d.review_status, priority=d.priority,
        )
        with patch("document_service.routes.documents.DocumentListResponse") as MockListResp:
            MockListResp.return_value = MagicMock()
            MockListResp.return_value.model_dump.return_value = {
                "items": [
                    {"title": "Board Deck v3.pptx", "priority": "high"},
                    {"title": "Term Sheet.pdf", "priority": "medium"},
                ],
                "total": 2,
            }

            resp = await client.get("/api/documents/needs-review")
            assert resp.status_code == 200
            mock_document_service.get_needs_review.assert_awaited_once_with("test-user-id")


# ===========================================================================
# NEW: Recent documents with type filter route test
# ===========================================================================

@pytest.mark.asyncio
async def test_recent_documents_type_filter(
    client: AsyncClient,
    mock_document_service: AsyncMock,
) -> None:
    """GET /api/documents/recent?doc_type=presentations filters by PPTX MIME."""
    pptx_doc = FakeDocument(
        title="Board Deck.pptx",
        content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )
    mock_document_service.get_recently_updated.return_value = [pptx_doc]

    with patch("document_service.routes.documents.DocumentResponse") as MockDocResp:
        MockDocResp.model_validate.return_value = MagicMock(title=pptx_doc.title)
        with patch("document_service.routes.documents.DocumentListResponse") as MockListResp:
            MockListResp.return_value = MagicMock()
            MockListResp.return_value.model_dump.return_value = {
                "items": [{"title": "Board Deck.pptx"}],
                "total": 1,
            }

            resp = await client.get("/api/documents/recent?doc_type=presentations")
            assert resp.status_code == 200
            mock_document_service.get_recently_updated.assert_awaited_once_with(
                user_id="test-user-id",
                doc_type="presentations",
                limit=20,
            )


# ===========================================================================
# NEW: Meeting-related documents route test
# ===========================================================================

@pytest.mark.asyncio
async def test_meeting_related_documents(
    client: AsyncClient,
    mock_document_service: AsyncMock,
) -> None:
    """GET /api/documents/meeting-related returns docs cross-referenced with calendar."""
    mock_document_service.get_meeting_documents_for_today.return_value = [
        {
            "meeting_subject": "Q4 Pipeline Review",
            "meeting_time": "2026-01-27T09:00:00",
            "documents": [
                {"title": "Agenda.docx", "source": "email_attachment"},
            ],
            "total": 1,
        },
    ]

    resp = await client.get("/api/documents/meeting-related")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_meetings"] == 1
    assert data["meetings"][0]["meeting_subject"] == "Q4 Pipeline Review"
    mock_document_service.get_meeting_documents_for_today.assert_awaited_once_with("test-user-id")


# ===========================================================================
# NEW: Shared with me route test
# ===========================================================================

@pytest.mark.asyncio
async def test_shared_with_me(
    client: AsyncClient,
    mock_document_service: AsyncMock,
) -> None:
    """GET /api/documents/shared-with-me returns docs shared via Graph."""
    shared_docs = [
        FakeDocument(
            title="Shared Deck.pptx",
            shared_by="Priya Sharma",
            shared_at=datetime(2026, 1, 25, tzinfo=timezone.utc),
            review_status="pending_review",
        ),
    ]
    mock_document_service.get_shared_with_me.return_value = shared_docs

    with patch("document_service.routes.documents.DocumentResponse") as MockDocResp:
        MockDocResp.model_validate.return_value = MagicMock(
            title="Shared Deck.pptx", shared_by="Priya Sharma",
        )
        with patch("document_service.routes.documents.DocumentListResponse") as MockListResp:
            MockListResp.return_value = MagicMock()
            MockListResp.return_value.model_dump.return_value = {
                "items": [{"title": "Shared Deck.pptx", "shared_by": "Priya Sharma"}],
                "total": 1,
            }

            resp = await client.get("/api/documents/shared-with-me")
            assert resp.status_code == 200
            mock_document_service.get_shared_with_me.assert_awaited_once_with("test-user-id")


# ===========================================================================
# NEW: DocumentService.sync_from_graph unit test
# ===========================================================================

@pytest.mark.asyncio
async def test_document_service_sync_from_graph() -> None:
    """sync_from_graph creates new Document records from Graph API response."""
    from document_service.services.document_service import DocumentService

    mock_graph = AsyncMock()
    mock_graph.get_sharepoint_recent.return_value = [
        {
            "id": "graph-item-1",
            "name": "Pipeline Model.xlsx",
            "webUrl": "https://example.sharepoint.com/Pipeline.xlsx",
            "file": {"mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
            "size": 2048,
            "parentReference": {"path": "/drive/root:/Sales/Pipeline"},
            "lastModifiedBy": {"user": {"displayName": "Ravi Kumar"}},
        },
    ]

    mock_session = AsyncMock()
    # Mock the DB execute for dedup check (no existing doc)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    service = DocumentService(
        graph_connector=mock_graph,
        db_session_factory=mock_factory,
        ingestion_pipeline=None,
    )

    docs = await service.sync_from_graph("user-123")
    assert len(docs) == 1
    new_doc = docs[0]
    assert new_doc.title == "Pipeline Model.xlsx"
    assert new_doc.folder_path == "Sales/Pipeline"
    assert new_doc.last_modified_by == "Ravi Kumar"
    assert new_doc.graph_item_id == "graph-item-1"
    mock_session.add.assert_called_once()


# ===========================================================================
# NEW: DocumentService.get_needs_review unit test
# ===========================================================================

@pytest.mark.asyncio
async def test_document_service_get_needs_review() -> None:
    """get_needs_review queries documents by review_status and priority order."""
    from document_service.services.document_service import DocumentService

    high_doc = FakeDocument(
        title="Board Deck.pptx",
        review_status="pending_review",
        priority="high",
        shared_by="Priya",
    )
    medium_doc = FakeDocument(
        title="Term Sheet.pdf",
        review_status="action_required",
        priority="medium",
        shared_by="Legal",
    )

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [high_doc, medium_doc]
    mock_result.scalars.return_value = mock_scalars
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    service = DocumentService(
        graph_connector=None,
        db_session_factory=mock_factory,
        ingestion_pipeline=None,
    )

    docs = await service.get_needs_review("user-123")
    assert len(docs) == 2
    assert docs[0].priority == "high"
    assert docs[1].priority == "medium"
    mock_session.execute.assert_awaited_once()


# ===========================================================================
# NEW: DocumentService.get_recently_updated unit test
# ===========================================================================

@pytest.mark.asyncio
async def test_document_service_get_recently_updated_with_type_filter() -> None:
    """get_recently_updated filters by MIME type when doc_type is provided."""
    from document_service.services.document_service import DocumentService

    pptx_doc = FakeDocument(
        title="Deck.pptx",
        content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [pptx_doc]
    mock_result.scalars.return_value = mock_scalars
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    service = DocumentService(
        graph_connector=None,
        db_session_factory=mock_factory,
        ingestion_pipeline=None,
    )

    docs = await service.get_recently_updated(
        user_id="user-123",
        doc_type="presentations",
        limit=10,
    )
    assert len(docs) == 1
    assert docs[0].title == "Deck.pptx"


# ===========================================================================
# NEW: DocumentService.get_meeting_documents_for_today unit test
# ===========================================================================

@pytest.mark.asyncio
async def test_document_service_get_meeting_documents_for_today() -> None:
    """get_meeting_documents_for_today cross-refs calendar events with docs."""
    from document_service.services.document_service import DocumentService

    mock_graph = AsyncMock()
    mock_graph.get_calendar_events.return_value = [
        {
            "id": "event-1",
            "subject": "Q4 Pipeline Review",
            "start": {"dateTime": "2026-01-27T09:00:00"},
        },
    ]
    mock_graph.get_meeting_attachments.return_value = [
        {
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": "Agenda.docx",
            "contentType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "size": 4096,
        },
    ]

    # Mock the DB session for the meeting query (no matching local meetings)
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = []  # No local meetings match
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    service = DocumentService(
        graph_connector=mock_graph,
        db_session_factory=mock_factory,
        ingestion_pipeline=None,
    )

    results = await service.get_meeting_documents_for_today("user-123")
    assert len(results) == 1
    assert results[0]["meeting_subject"] == "Q4 Pipeline Review"
    assert results[0]["total"] == 1
    assert results[0]["documents"][0]["title"] == "Agenda.docx"


# ===========================================================================
# NEW: DocumentService.get_shared_with_me unit test
# ===========================================================================

@pytest.mark.asyncio
async def test_document_service_get_shared_with_me() -> None:
    """get_shared_with_me creates records from Graph sharedWithMe response."""
    from document_service.services.document_service import DocumentService

    mock_graph = AsyncMock()
    mock_graph.get_shared_with_me.return_value = [
        {
            "id": "shared-item-1",
            "name": "Shared Deck.pptx",
            "webUrl": "https://example.sharepoint.com/Shared.pptx",
            "file": {"mimeType": "application/vnd.openxmlformats-officedocument.presentationml.presentation"},
            "size": 5120,
            "shared": {
                "sharedBy": {"user": {"displayName": "Priya Sharma"}},
                "sharedDateTime": "2026-01-25T10:00:00Z",
            },
        },
    ]

    mock_session = AsyncMock()
    # Dedup check returns no existing doc
    mock_dedup_result = MagicMock()
    mock_dedup_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_dedup_result)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    service = DocumentService(
        graph_connector=mock_graph,
        db_session_factory=mock_factory,
        ingestion_pipeline=None,
    )

    docs = await service.get_shared_with_me("user-123")
    assert len(docs) == 1
    new_doc = docs[0]
    assert new_doc.title == "Shared Deck.pptx"
    assert new_doc.shared_by == "Priya Sharma"
    assert new_doc.review_status == "pending_review"
    mock_session.add.assert_called_once()


# ===========================================================================
# Classification endpoint tests
# ===========================================================================

@pytest.mark.asyncio
async def test_classify_document_endpoint(
    client: AsyncClient,
    mock_db_session: AsyncMock,
) -> None:
    """POST /api/documents/{id}/classify classifies and persists result."""
    from dataclasses import dataclass, field as dc_field

    @dataclass
    class FakeClassResult:
        category: str = "qbr"
        confidence: float = 0.85
        suggested_priority: str = "medium"
        suggested_tags: list = dc_field(default_factory=lambda: ["Quarterly Business Review", "Q4", "PowerPoint"])

    doc = FakeDocument(
        id=uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
        title="Q4_QBR_2025.pptx",
        extracted_text="Quarterly business review revenue utilization scorecard",
        content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        status="processed",
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = doc
    mock_db_session.execute = AsyncMock(return_value=mock_result)

    with patch("document_service.dependencies.get_document_classifier") as mock_get_clf:
        mock_classifier = AsyncMock()
        mock_classifier.classify_file = AsyncMock(return_value=FakeClassResult())
        mock_get_clf.return_value = mock_classifier

        with patch("yoda_foundation.rag.classification.document_classifier.CATEGORY_LABELS", {"qbr": "Quarterly Business Review"}):
            resp = await client.post(
                f"/api/documents/{doc.id}/classify"
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["category"] == "qbr"
    assert data["category_label"] == "Quarterly Business Review"
    assert data["confidence"] == 0.85
    assert data["suggested_priority"] == "medium"
    assert "Q4" in data["suggested_tags"]
    # Verify persistence on the document object
    assert doc.category == "qbr"
    assert doc.classification_confidence == 0.85
    assert doc.priority == "medium"


@pytest.mark.asyncio
async def test_classify_document_not_found(
    client: AsyncClient,
    mock_db_session: AsyncMock,
) -> None:
    """POST /api/documents/{id}/classify returns 404 for missing document."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db_session.execute = AsyncMock(return_value=mock_result)

    resp = await client.post(
        f"/api/documents/{uuid.uuid4()}/classify"
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_classify_text_endpoint(client: AsyncClient) -> None:
    """POST /api/documents/classify-text classifies arbitrary text."""
    from dataclasses import dataclass, field as dc_field

    @dataclass
    class FakeClassResult:
        category: str = "status_report"
        confidence: float = 0.72
        suggested_priority: str = "medium"
        suggested_tags: list = dc_field(default_factory=lambda: ["Status Report"])

    with patch("document_service.dependencies.get_document_classifier") as mock_get_clf:
        mock_classifier = AsyncMock()
        mock_classifier.classify = AsyncMock(return_value=FakeClassResult())
        mock_get_clf.return_value = mock_classifier

        with patch("yoda_foundation.rag.classification.document_classifier.CATEGORY_LABELS", {"status_report": "Status Report"}):
            resp = await client.post(
                "/api/documents/classify-text",
                params={"text": "Weekly status update sprint 14 deliverables on track"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["category"] == "status_report"
    assert data["confidence"] == 0.72


@pytest.mark.asyncio
async def test_classify_text_with_filename(client: AsyncClient) -> None:
    """POST /api/documents/classify-text uses filename hint when provided."""
    from dataclasses import dataclass, field as dc_field

    @dataclass
    class FakeClassResult:
        category: str = "mbr"
        confidence: float = 0.90
        suggested_priority: str = "medium"
        suggested_tags: list = dc_field(default_factory=lambda: ["Monthly Business Review"])

    with patch("document_service.dependencies.get_document_classifier") as mock_get_clf:
        mock_classifier = AsyncMock()
        mock_classifier.classify_file = AsyncMock(return_value=FakeClassResult())
        mock_get_clf.return_value = mock_classifier

        with patch("yoda_foundation.rag.classification.document_classifier.CATEGORY_LABELS", {"mbr": "Monthly Business Review"}):
            resp = await client.post(
                "/api/documents/classify-text",
                params={
                    "text": "Monthly review of account health",
                    "filename": "MBR_January_2026.pptx",
                },
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["category"] == "mbr"
    # When filename is provided, classify_file should be called
    mock_classifier.classify_file.assert_awaited_once()
