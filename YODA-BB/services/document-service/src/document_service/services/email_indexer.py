"""Email indexer -- fetches emails from Graph API and indexes for RAG retrieval."""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yoda_foundation.models.document import Document

logger = logging.getLogger(__name__)


class EmailIndexer:
    """Fetches user emails from Microsoft Graph and indexes them as documents.

    Integrates with the RAG ingestion pipeline so that email content becomes
    searchable via the Chat / Ask AI features.

    Args:
        graph_connector: GraphConnector (or compatible) for fetching emails.
        db_session_factory: Async session factory for document persistence.
        ingestion_pipeline: Optional RAG ingestion pipeline (chunk, embed, store).
    """

    def __init__(
        self,
        graph_connector: Any,
        db_session_factory: async_sessionmaker[AsyncSession],
        ingestion_pipeline: Any = None,
    ) -> None:
        self._graph = graph_connector
        self._session_factory = db_session_factory
        self._ingestion = ingestion_pipeline

    async def index_recent_emails(
        self, user_id: str, days: int = 7, limit: int = 50
    ) -> list[Document]:
        """Fetch recent emails and index them as documents.

        1. Calls Graph API to get recent emails.
        2. Creates Document records with source='email'.
        3. Runs through ingestion pipeline (chunk + embed) if available.

        Args:
            user_id: Azure AD user ID whose mailbox to index.
            days: How many days back to fetch (passed to Graph connector).
            limit: Maximum number of emails to index per call.

        Returns:
            List of newly created Document instances.
        """
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
