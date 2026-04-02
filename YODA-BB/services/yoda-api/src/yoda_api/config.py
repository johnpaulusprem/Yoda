"""Unified YODA API configuration.

Merges settings from all former microservices into a single Settings class.
"""

from __future__ import annotations

from yoda_foundation.config.settings import Settings as _FoundationSettings


class YodaAPISettings(_FoundationSettings):
    """All foundation settings plus service-specific fields."""

    APP_NAME: str = "yoda-api"

    # ─── Meeting Bot Behaviour ──────────────────────────────────────
    BOT_DISPLAY_NAME: str = "Meeting Assistant"

    # ─── Azure AD Auth (API protection) ─────────────────────────────
    AZURE_AD_AUDIENCE: str = ""  # App ID URI or client_id; empty = dev mode
    AZURE_AD_ADMIN_ROLE: str = "Admin"

    # ─── Pre-meeting brief ──────────────────────────────────────────
    AI_FOUNDRY_DEPLOYMENT: str = "gpt-4o-mini"
    BRIEF_CACHE_TTL_SECONDS: int = 7200


# Convenience alias
Settings = YodaAPISettings
