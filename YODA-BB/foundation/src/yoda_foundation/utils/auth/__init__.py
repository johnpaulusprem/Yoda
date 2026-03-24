"""Auth utilities for yoda_foundation.

Re-exports the public API so consumers can write::

    from yoda_foundation.utils.auth import TokenProvider
"""

from __future__ import annotations

from yoda_foundation.utils.auth.token_provider import TokenProvider

__all__ = [
    "TokenProvider",
]
