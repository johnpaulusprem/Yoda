"""Tests for the Chat Service -- service layer and API routes."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yoda_foundation.models.chat import ChatMessage, ChatSession


# ═══════════════════════════════════════════════════════════════════════════
# ChatService unit tests
# ═══════════════════════════════════════════════════════════════════════════


class TestChatServiceCreateSession:
    """Tests for ChatService.create_session."""

    @pytest.mark.asyncio
    async def test_create_session_persists(self, session_factory, mock_ai_connector):
        """create_session should persist a new ChatSession."""
        from chat_service.services.chat_service import ChatService

        service = ChatService(
            ai_connector=mock_ai_connector,
            db_session_factory=session_factory,
        )

        session = await service.create_session(user_id="user-001", title="Test Chat")

        assert session.id is not None
        assert session.user_id == "user-001"
        assert session.title == "Test Chat"

    @pytest.mark.asyncio
    async def test_create_session_default_title(self, session_factory, mock_ai_connector):
        """create_session should use 'New Chat' as default title."""
        from chat_service.services.chat_service import ChatService

        service = ChatService(
            ai_connector=mock_ai_connector,
            db_session_factory=session_factory,
        )

        session = await service.create_session(user_id="user-002")

        assert session.title == "New Chat"


class TestChatServiceSendMessage:
    """Tests for ChatService.send_message."""

    @pytest.mark.asyncio
    async def test_send_message_with_rag(
        self, session_factory, mock_ai_connector, mock_rag_pipeline
    ):
        """send_message should use RAG pipeline when available."""
        from chat_service.services.chat_service import ChatService

        service = ChatService(
            ai_connector=mock_ai_connector,
            db_session_factory=session_factory,
            rag_pipeline=mock_rag_pipeline,
        )

        # Create a session first
        session = await service.create_session(user_id="user-001", title="RAG Test")

        # Send a message
        response = await service.send_message(
            session_id=session.id,
            user_message="What was discussed in the last meeting?",
            user_id="user-001",
        )

        assert response.role == "assistant"
        assert response.content is not None
        assert len(response.content) > 0
        mock_rag_pipeline.query.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_message_fallback_when_no_rag(
        self, session_factory, mock_ai_connector
    ):
        """send_message should use fallback when RAG pipeline is None."""
        from chat_service.services.chat_service import ChatService

        service = ChatService(
            ai_connector=mock_ai_connector,
            db_session_factory=session_factory,
            rag_pipeline=None,
        )

        session = await service.create_session(user_id="user-001", title="Fallback Test")

        response = await service.send_message(
            session_id=session.id,
            user_message="Summarize recent meetings",
            user_id="user-001",
        )

        assert response.role == "assistant"
        assert response.content is not None
        mock_ai_connector.complete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_message_persists_user_and_assistant(
        self, session_factory, mock_ai_connector
    ):
        """send_message should persist both user and assistant messages."""
        from chat_service.services.chat_service import ChatService

        service = ChatService(
            ai_connector=mock_ai_connector,
            db_session_factory=session_factory,
            rag_pipeline=None,
        )

        session = await service.create_session(user_id="user-001")
        await service.send_message(
            session_id=session.id,
            user_message="Hello",
            user_id="user-001",
        )

        messages = await service.get_session_messages(session.id)
        assert len(messages) == 2
        assert messages[0].role == "user"
        assert messages[0].content == "Hello"
        assert messages[1].role == "assistant"

    @pytest.mark.asyncio
    async def test_send_message_rag_failure_falls_back(
        self, session_factory, mock_ai_connector
    ):
        """If RAG pipeline raises, should fall back to summary-based answer."""
        from chat_service.services.chat_service import ChatService

        failing_rag = AsyncMock()
        failing_rag.query = AsyncMock(side_effect=RuntimeError("RAG unavailable"))

        service = ChatService(
            ai_connector=mock_ai_connector,
            db_session_factory=session_factory,
            rag_pipeline=failing_rag,
        )

        session = await service.create_session(user_id="user-001")
        response = await service.send_message(
            session_id=session.id,
            user_message="What happened?",
            user_id="user-001",
        )

        # Should still produce an assistant response via fallback
        assert response.role == "assistant"
        mock_ai_connector.complete.assert_awaited_once()


class TestChatServiceGetMessages:
    """Tests for ChatService.get_session_messages."""

    @pytest.mark.asyncio
    async def test_get_session_messages_empty(self, session_factory, mock_ai_connector):
        """get_session_messages should return empty list for new session."""
        from chat_service.services.chat_service import ChatService

        service = ChatService(
            ai_connector=mock_ai_connector,
            db_session_factory=session_factory,
        )

        session = await service.create_session(user_id="user-001")
        messages = await service.get_session_messages(session.id)

        assert messages == []

    @pytest.mark.asyncio
    async def test_get_session_messages_ordered(self, session_factory, mock_ai_connector):
        """get_session_messages should return messages in chronological order."""
        from chat_service.services.chat_service import ChatService

        service = ChatService(
            ai_connector=mock_ai_connector,
            db_session_factory=session_factory,
            rag_pipeline=None,
        )

        session = await service.create_session(user_id="user-001")
        await service.send_message(session.id, "First message", "user-001")
        await service.send_message(session.id, "Second message", "user-001")

        messages = await service.get_session_messages(session.id)

        # 2 user + 2 assistant = 4 messages
        assert len(messages) == 4
        assert messages[0].content == "First message"
        assert messages[1].role == "assistant"
        assert messages[2].content == "Second message"
        assert messages[3].role == "assistant"


# ═══════════════════════════════════════════════════════════════════════════
# API route tests
# ═══════════════════════════════════════════════════════════════════════════


class TestHealthEndpoint:
    """Tests for the /health endpoint."""

    @pytest.mark.asyncio
    async def test_health_returns_ok(self, test_client):
        """GET /health should return 200 with service name."""
        response = await test_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "chat-service"


class TestChatSessionRoutes:
    """Tests for chat session CRUD routes."""

    @pytest.mark.asyncio
    async def test_create_session_route(self, test_client):
        """POST /api/chat/sessions should create a new session."""
        response = await test_client.post("/api/chat/sessions?title=My+Chat")
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "My Chat"
        assert "id" in data
        assert "user_id" in data

    @pytest.mark.asyncio
    async def test_list_sessions_route(self, test_client):
        """GET /api/chat/sessions should list user sessions."""
        # Create a session first
        await test_client.post("/api/chat/sessions?title=Session+1")

        response = await test_client.get("/api/chat/sessions")
        assert response.status_code == 200
        data = response.json()
        assert "sessions" in data

    @pytest.mark.asyncio
    async def test_get_messages_nonexistent_session(self, test_client):
        """GET /api/chat/sessions/{id}/messages with nonexistent session should return empty."""
        fake_id = str(uuid.uuid4())
        response = await test_client.get(f"/api/chat/sessions/{fake_id}/messages")
        assert response.status_code == 200
        data = response.json()
        assert data["messages"] == []

    @pytest.mark.asyncio
    async def test_send_message_nonexistent_session(self, test_client):
        """POST /api/chat/sessions/{id}/messages with nonexistent session should 404."""
        fake_id = str(uuid.uuid4())
        response = await test_client.post(
            f"/api/chat/sessions/{fake_id}/messages",
            json={"content": "Hello"},
        )
        assert response.status_code == 404
