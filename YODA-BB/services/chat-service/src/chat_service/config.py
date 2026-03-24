"""Chat service configuration.

Extends the shared ``yoda_foundation.config.settings.Settings`` with fields
that are specific to the chat-service microservice.
"""

from __future__ import annotations

from yoda_foundation.config.settings import Settings as _FoundationSettings


class ChatServiceSettings(_FoundationSettings):
    """All foundation settings plus chat-service specifics."""

    APP_NAME: str = "chat-service"
    PORT: int = 8003


# Module-level convenience alias so existing ``from chat_service.config import Settings``
# works without changing every call-site.
Settings = ChatServiceSettings
