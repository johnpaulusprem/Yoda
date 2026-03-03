"""MSAL-based token provider for Azure services.

Supports two flows:

1. **Client-credentials (daemon)** — the bot operates without interactive
   user sign-in.  Used for background tasks (joining calls, transcription).
2. **On-Behalf-Of (OBO)** — the backend exchanges a user's delegated access
   token for a new token scoped to downstream APIs (e.g. Microsoft Graph).
   Used when the React frontend sends a user's Bearer token and the backend
   needs to call Graph API *as that user*.

Tokens are cached internally by the MSAL ``ConfidentialClientApplication``
and refreshed automatically when they approach expiry.
"""

from __future__ import annotations

import logging
from typing import Any

import msal  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

# Well-known scope constants.
_GRAPH_SCOPE = "https://graph.microsoft.com/.default"
_ACS_SCOPE = "https://communication.azure.com/.default"


class TokenProvider:
    """Acquire Azure AD tokens via the MSAL confidential-client flow.

    Supports client-credentials (daemon) and On-Behalf-Of (OBO) flows.
    Tokens are cached internally by MSAL and refreshed automatically.

    Args:
        tenant_id: Azure AD / Entra ID tenant identifier.
        client_id: Application (client) ID registered in Entra ID.
        client_secret: Client secret value (not the secret ID).
        authority: Override the login authority URL. Defaults to
            ``https://login.microsoftonline.com/{tenant_id}``.
    """

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        *,
        authority: str | None = None,
    ) -> None:
        self._tenant_id = tenant_id
        self._client_id = client_id
        self._authority = authority or f"https://login.microsoftonline.com/{tenant_id}"

        self._app: msal.ConfidentialClientApplication = (
            msal.ConfidentialClientApplication(
                client_id=client_id,
                client_credential=client_secret,
                authority=self._authority,
            )
        )

    # -- core ----------------------------------------------------------------

    async def get_token(self, scopes: list[str]) -> str:
        """Acquire an access token for the given *scopes*.

        MSAL's ``acquire_token_silent`` is attempted first (returns a cached /
        refreshed token). On a cache miss ``acquire_token_for_client`` issues
        a fresh token request to Azure AD.

        Args:
            scopes: List of OAuth 2.0 scope strings to request.

        Returns:
            The raw access-token string.

        Raises:
            RuntimeError: When token acquisition fails for any reason.
        """
        # Try the token cache first.
        result: dict[str, Any] | None = self._app.acquire_token_silent(
            scopes,
            account=None,
        )

        if not result:
            logger.debug(
                "Token cache miss for scopes=%s -- acquiring new token.", scopes
            )
            result = self._app.acquire_token_for_client(scopes=scopes)

        if "access_token" in result:  # type: ignore[operator]
            return result["access_token"]  # type: ignore[index]

        error = (
            result.get("error", "unknown_error") if result else "no_result"  # type: ignore[union-attr]
        )
        error_description = (
            result.get("error_description", "") if result else ""  # type: ignore[union-attr]
        )
        logger.error(
            "Token acquisition failed: error=%s description=%s",
            error,
            error_description,
        )
        raise RuntimeError(
            f"Failed to acquire token: {error} -- {error_description}"
        )

    # -- convenience shortcuts -----------------------------------------------

    async def get_graph_token(self) -> str:
        """Shortcut: acquire a Microsoft Graph API token."""
        return await self.get_token([_GRAPH_SCOPE])

    async def get_acs_token(self) -> str:
        """Shortcut: acquire an Azure Communication Services token."""
        return await self.get_token([_ACS_SCOPE])

    # -- On-Behalf-Of (OBO) flow --------------------------------------------

    async def get_token_on_behalf_of(
        self,
        user_assertion: str,
        scopes: list[str] | None = None,
    ) -> str:
        """Exchange a user's access token for a downstream API token (OBO).

        The On-Behalf-Of flow lets the backend call Microsoft Graph (or other
        APIs) *as the signed-in user* rather than as the application.

        Args:
            user_assertion: The access token that the React frontend sent in
                the ``Authorization: Bearer <token>`` header.
            scopes: Target API scopes. Defaults to Microsoft Graph.

        Returns:
            An access token scoped to the downstream API, issued for the
            signed-in user.

        Raises:
            RuntimeError: When the OBO token exchange fails.
        """
        target_scopes = scopes or [_GRAPH_SCOPE]

        result: dict[str, Any] | None = (
            self._app.acquire_token_on_behalf_of(
                user_assertion=user_assertion,
                scopes=target_scopes,
            )
        )

        if result and "access_token" in result:
            return result["access_token"]

        error = (
            result.get("error", "unknown_error") if result else "no_result"
        )
        error_description = (
            result.get("error_description", "") if result else ""
        )
        logger.error(
            "OBO token exchange failed: error=%s description=%s",
            error,
            error_description,
        )
        raise RuntimeError(
            f"OBO token exchange failed: {error} -- {error_description}"
        )

    async def get_graph_token_for_user(self, user_assertion: str) -> str:
        """Shortcut: OBO exchange for a Microsoft Graph token."""
        return await self.get_token_on_behalf_of(user_assertion, [_GRAPH_SCOPE])
