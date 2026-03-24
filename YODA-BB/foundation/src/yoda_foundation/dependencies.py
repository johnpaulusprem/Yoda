"""Shared dependency injection helpers for yoda_foundation.

Provides a cached ``get_settings`` function used by FastAPI dependency
injection (e.g., in ``auth_dependency.py``).
"""

from __future__ import annotations

import functools

from yoda_foundation.config import Settings


@functools.lru_cache
def get_settings() -> Settings:
    """Return the cached application ``Settings`` singleton."""
    return Settings()
