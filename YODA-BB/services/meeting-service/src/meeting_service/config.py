"""Meeting-service configuration.

Extends the shared ``yoda_foundation.config.settings.Settings`` with fields
that are specific to the meeting-service microservice.
"""

from __future__ import annotations

from yoda_foundation.config.settings import Settings as _FoundationSettings


class MeetingServiceSettings(_FoundationSettings):
    """All foundation settings plus meeting-service specifics."""

    APP_NAME: str = "meeting-service"

    # ─── Meeting Bot Behaviour ──────────────────────────────────────
    BOT_DISPLAY_NAME: str = "Meeting Assistant"

    # ─── Azure AD Auth (API protection) ─────────────────────────────
    AZURE_AD_AUDIENCE: str = ""  # App ID URI or client_id — empty = dev mode
    AZURE_AD_ADMIN_ROLE: str = "Admin"


# Module-level convenience alias so existing ``from meeting_service.config import Settings``
# works without changing every call-site.
Settings = MeetingServiceSettings
