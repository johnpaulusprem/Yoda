"""Document service configuration.

Extends the shared ``yoda_foundation.config.settings.Settings`` with fields
that are specific to the document-service microservice.
"""

from __future__ import annotations

from yoda_foundation.config.settings import Settings as _FoundationSettings


class DocumentServiceSettings(_FoundationSettings):
    """All foundation settings plus document-service specifics."""

    APP_NAME: str = "document-service"

    # ─── Server ──────────────────────────────────────────────────────
    HOST: str = "0.0.0.0"
    PORT: int = 8002


# Module-level convenience alias so ``from document_service.config import Settings``
# works without changing every call-site.
Settings = DocumentServiceSettings
