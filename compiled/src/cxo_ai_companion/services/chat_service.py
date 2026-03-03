"""RAG-powered conversational AI for meeting context queries.

Integrates with the DSPy RAG pipeline for retrieval-augmented generation
with structured citations and confidence scores.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cxo_ai_companion.exceptions import AIProcessingError
from cxo_ai_companion.models.chat import ChatMessage, ChatSession
from cxo_ai_companion.models.summary import MeetingSummary
from cxo_ai_companion.models.transcript import TranscriptSegment

logger = logging.getLogger(__name__)


class ChatService:
    """RAG-powered conversational AI for meeting context queries.

    When a RAG pipeline is provided, queries are answered using
    vector-retrieved context with DSPy ChainOfThought reasoning
    and structured citations.  Falls back to summary-based context
    when the pipeline is unavailable.
    """

    def __init__(
        self,
        ai_connector: Any,
        db_session_factory: async_sessionmaker[AsyncSession],
        rag_pipeline: Any | None = None,
    ) -> None:
        """Initialize the chat service.

        Args:
            ai_connector: Azure AI Foundry client for LLM completions.
            db_session_factory: Async session factory for chat persistence.
            rag_pipeline: Optional RAG pipeline for vector-based retrieval.
                Falls back to summary-based context when None.
        """
        self._ai = ai_connector
        self._session_factory = db_session_factory
        self._rag = rag_pipeline

    async def create_session(
        self, user_id: str, title: str = "New Chat"
    ) -> ChatSession:
        """Create a new chat session for a user.

        Args:
            user_id: Azure AD user ID of the session owner.
            title: Display title for the chat session.

        Returns:
            The persisted ChatSession instance.
        """
        async with self._session_factory() as db:
            session = ChatSession(user_id=user_id, title=title)
            db.add(session)
            await db.commit()
            await db.refresh(session)
            return session

    async def send_message(
        self, session_id: UUID, user_message: str, user_id: str
    ) -> ChatMessage:
        """Send a user message and generate an assistant response.

        Routes to the RAG pipeline if available, otherwise falls back to
        summary-based context. Persists both user and assistant messages.

        Args:
            session_id: UUID of the chat session.
            user_message: The user's question or message text.
            user_id: Azure AD user ID for context scoping.

        Returns:
            The assistant's ChatMessage response.

        Raises:
            AIProcessingError: If the AI backend is unavailable.
        """
        async with self._session_factory() as db:
            # Save user message
            user_msg = ChatMessage(
                session_id=session_id, role="user", content=user_message
            )
            db.add(user_msg)
            await db.flush()

            # Route to RAG pipeline or fallback
            if self._rag is not None:
                assistant_msg = await self._rag_answer(
                    db, session_id, user_message, user_id
                )
            else:
                assistant_msg = await self._fallback_answer(
                    db, session_id, user_message, user_id
                )

            db.add(assistant_msg)
            await db.commit()
            await db.refresh(assistant_msg)

            # Update session timestamp
            result = await db.execute(
                select(ChatSession).where(ChatSession.id == session_id)
            )
            session = result.scalar_one_or_none()
            if session:
                session.last_message_at = datetime.now(UTC)
                await db.commit()

            return assistant_msg

    async def _rag_answer(
        self,
        db: AsyncSession,
        session_id: UUID,
        user_message: str,
        user_id: str,
    ) -> ChatMessage:
        """Answer using the DSPy RAG pipeline with vector retrieval."""
        try:
            from cxo_ai_companion.rag.pipeline.rag_pipeline import RAGResult

            rag_result: RAGResult = await self._rag.query(
                question=user_message,
                user_id=user_id,
            )

            # Build source citations from RAG result
            sources: list[dict[str, Any]] = []
            for citation in rag_result.citations:
                sources.append({
                    "title": citation.source.title,
                    "url": citation.source.url,
                    "snippet": citation.text_snippet,
                    "document_id": citation.source.document_id,
                    "relevance_score": citation.relevance_score,
                })

            return ChatMessage(
                session_id=session_id,
                role="assistant",
                content=rag_result.answer,
                model_used=rag_result.sources[0].metadata.get("model", "gpt-4o")
                if rag_result.sources
                else "gpt-4o",
                tokens_used=0,
                sources=sources if sources else None,
            )

        except Exception as exc:
            logger.warning(
                "RAG pipeline failed, falling back: %s", exc, exc_info=True
            )
            return await self._fallback_answer(
                db, session_id, user_message, user_id
            )

    async def _fallback_answer(
        self,
        db: AsyncSession,
        session_id: UUID,
        user_message: str,
        user_id: str,
    ) -> ChatMessage:
        """Fallback: answer using recent meeting summaries (original behaviour)."""
        context = await self._build_context(db, user_message, user_id)

        from azure.ai.inference.models import SystemMessage, UserMessage

        system_prompt = (
            "You are a CXO AI Companion. Answer questions using the meeting "
            "context provided. Cite sources with [Meeting: <subject>] or "
            "[Transcript: <timestamp>] format. Be concise and "
            "executive-focused.\n\n"
            f"Context:\n{context}"
        )
        try:
            response_text = await self._ai.complete(
                model="gpt-4o-mini",
                messages=[
                    SystemMessage(content=system_prompt),
                    UserMessage(content=user_message),
                ],
                temperature=0.3,
            )
        except Exception as exc:
            raise AIProcessingError(
                message=f"Chat AI failed: {exc}",
                model="gpt-4o-mini",
                cause=exc,
            ) from exc

        return ChatMessage(
            session_id=session_id,
            role="assistant",
            content=response_text,
            model_used="gpt-4o-mini",
            tokens_used=0,
            sources=[{"type": "meeting_context", "query": user_message}],
        )

    async def _build_context(
        self, db: AsyncSession, query: str, user_id: str
    ) -> str:
        """Build RAG context from recent meeting summaries and transcripts."""
        result = await db.execute(
            select(MeetingSummary)
            .order_by(MeetingSummary.created_at.desc())
            .limit(5)
        )
        summaries = result.scalars().all()

        context_parts = []
        for s in summaries:
            context_parts.append(
                f"Meeting Summary (ID: {s.meeting_id}):\n{s.summary_text[:500]}"
            )

        return (
            "\n\n---\n\n".join(context_parts)
            if context_parts
            else "No meeting data available."
        )

    async def get_session_messages(self, session_id: UUID) -> list[ChatMessage]:
        """Retrieve all messages in a chat session, ordered chronologically.

        Args:
            session_id: UUID of the chat session.

        Returns:
            List of ChatMessage instances ordered by created_at.
        """
        async with self._session_factory() as db:
            result = await db.execute(
                select(ChatMessage)
                .where(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.created_at)
            )
            return list(result.scalars().all())
