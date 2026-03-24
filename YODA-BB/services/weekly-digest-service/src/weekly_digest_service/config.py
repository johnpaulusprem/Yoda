"""Weekly digest service configuration.

Extends the shared ``yoda_foundation.config.settings.Settings`` with fields
specific to the weekly-digest-service microservice.
"""

from __future__ import annotations

from yoda_foundation.config.settings import Settings as _FoundationSettings


class WeeklyDigestSettings(_FoundationSettings):
    """All foundation settings plus weekly-digest-service specifics."""

    APP_NAME: str = "weekly-digest-service"
    PORT: int = 8006

    # ─── Digest Schedule ─────────────────────────────────────────────
    DIGEST_SCHEDULE_DAY: str = "fri"   # Day of week: mon, tue, wed, thu, fri, sat, sun
    DIGEST_SCHEDULE_HOUR: int = 16     # Hour in UTC (16 = 4 PM)
    DIGEST_SCHEDULE_MINUTE: int = 0

    # ─── Users to generate digests for (comma-separated Azure AD user IDs)
    DIGEST_USER_IDS: str = ""


# Module-level convenience alias
Settings = WeeklyDigestSettings
