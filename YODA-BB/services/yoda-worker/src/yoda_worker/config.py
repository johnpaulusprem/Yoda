"""YODA Worker configuration.

Extends the shared ``yoda_foundation.config.settings.Settings`` with fields
specific to the yoda-worker (background jobs).
"""

from __future__ import annotations

from yoda_foundation.config.settings import Settings as _FoundationSettings


class WorkerSettings(_FoundationSettings):
    """All foundation settings plus worker-specific fields."""

    APP_NAME: str = "yoda-worker"
    PORT: int = 8002

    # ─── Digest Schedule ─────────────────────────────────────────────
    DIGEST_SCHEDULE_DAY: str = "fri"   # Day of week: mon, tue, wed, thu, fri, sat, sun
    DIGEST_SCHEDULE_HOUR: int = 16     # Hour in UTC (16 = 4 PM)
    DIGEST_SCHEDULE_MINUTE: int = 0

    # ─── Users to generate digests for (comma-separated Azure AD user IDs)
    DIGEST_USER_IDS: str = ""


# Module-level convenience alias
Settings = WorkerSettings
