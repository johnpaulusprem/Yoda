"""Dashboard service configuration."""
from __future__ import annotations

from yoda_foundation.config.settings import Settings as _FoundationSettings


class DashboardServiceSettings(_FoundationSettings):
    """All foundation settings plus dashboard-service specifics."""

    APP_NAME: str = "dashboard-service"
    PORT: int = 8004


# Module-level convenience alias.
Settings = DashboardServiceSettings
