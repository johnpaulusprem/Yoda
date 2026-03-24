"""Pre-meeting brief service configuration.

Extends the shared ``yoda_foundation.config.settings.Settings`` with fields
specific to the pre-meeting-brief-service microservice.
"""

from __future__ import annotations

from yoda_foundation.config.settings import Settings as _FoundationSettings


class PreMeetingBriefSettings(_FoundationSettings):
    """All foundation settings plus pre-meeting-brief-service specifics."""

    APP_NAME: str = "pre-meeting-brief-service"
    PORT: int = 8005

    # ─── AI Foundry for question generation ──────────────────────────
    AI_FOUNDRY_DEPLOYMENT: str = "gpt-4o-mini"

    # ─── Caching ─────────────────────────────────────────────────────
    BRIEF_CACHE_TTL_SECONDS: int = 7200


# Module-level convenience alias
Settings = PreMeetingBriefSettings
