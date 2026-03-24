"""Ask AI / RAG chat routes with DSPy RAG pipeline integration."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from yoda_foundation.security.auth_dependency import get_current_user
from yoda_foundation.security.context import SecurityContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from chat_service.dependencies import get_db
from yoda_foundation.schemas.chat import (
    ChatMessageRequest,
    ChatMessageResponse,
    ChatSessionResponse,
)

router = APIRouter()


@router.post("/sessions")
async def create_session(
    title: str = "New Chat",
    db: AsyncSession = Depends(get_db),
    ctx: SecurityContext = Depends(get_current_user),
) -> ChatSessionResponse:
    """Create a new chat session for a user."""
    from yoda_foundation.models.chat import ChatSession

    session = ChatSession(user_id=ctx.user_id, title=title)
    db.add(session)
    await db.flush()
    await db.refresh(session)
    return ChatSessionResponse(
        id=session.id,
        user_id=session.user_id,
        title=session.title,
        last_message_at=session.last_message_at,
        created_at=session.created_at,
        messages=[],
    )


@router.get("/sessions")
async def list_sessions(
    db: AsyncSession = Depends(get_db),
    ctx: SecurityContext = Depends(get_current_user),
) -> dict:
    """List all chat sessions for a user, ordered by most recent activity."""
    from yoda_foundation.models.chat import ChatSession

    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.user_id == ctx.user_id)
        .order_by(ChatSession.last_message_at.desc())
    )
    sessions = result.scalars().all()
    return {
        "sessions": [
            ChatSessionResponse(
                id=s.id,
                user_id=s.user_id,
                title=s.title,
                last_message_at=s.last_message_at,
                created_at=s.created_at,
                messages=[],
            )
            for s in sessions
        ]
    }


@router.post("/sessions/{session_id}/messages", response_model=ChatMessageResponse)
async def send_message(
    session_id: UUID,
    body: ChatMessageRequest,
    db: AsyncSession = Depends(get_db),
    ctx: SecurityContext = Depends(get_current_user),
) -> ChatMessageResponse:
    """Send a user message and receive an AI-generated response via the RAG pipeline.

    Validates the session exists, then delegates to ChatService which
    optionally uses the DSPy RAG pipeline for context-augmented answers.
    """
    from yoda_foundation.models.chat import ChatSession

    # Validate session exists
    result = await db.execute(
        select(ChatSession).where(ChatSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")

    # Use the ChatService with RAG pipeline
    from chat_service.dependencies import (
        get_rag_pipeline,
        get_session_factory,
    )

    try:
        rag_pipeline = get_rag_pipeline()
    except Exception:
        rag_pipeline = None

    from chat_service.services.chat_service import ChatService

    # Get AI connector from app state if available, otherwise None
    ai_connector = None
    try:
        from chat_service.dependencies import get_llm_adapter

        ai_connector = get_llm_adapter()
    except Exception:
        pass

    service = ChatService(
        ai_connector=ai_connector,
        db_session_factory=get_session_factory(),
        rag_pipeline=rag_pipeline,
    )
    assistant_msg = await service.send_message(
        session_id=session_id,
        user_message=body.content,
        user_id=session.user_id,
    )
    return ChatMessageResponse.model_validate(assistant_msg)


@router.get("/sessions/{session_id}/messages")
async def get_messages(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    ctx: SecurityContext = Depends(get_current_user),
) -> dict:
    """Retrieve all messages in a chat session, ordered chronologically."""
    from yoda_foundation.models.chat import ChatMessage

    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
    )
    messages = result.scalars().all()
    return {"messages": [ChatMessageResponse.model_validate(m) for m in messages]}
