"""Auth utilities for cxo_ai_companion.

Re-exports the public API so consumers can write::

    from cxo_ai_companion.utilities.auth import TokenProvider
"""

from __future__ import annotations

from cxo_ai_companion.utilities.auth.token_provider import TokenProvider

__all__ = [
    "TokenProvider",
]
