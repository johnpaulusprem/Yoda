from msal import ConfidentialClientApplication


class TokenProvider:
    def __init__(self, tenant_id: str, client_id: str, client_secret: str):
        self.app = ConfidentialClientApplication(
            client_id,
            authority=f"https://login.microsoftonline.com/{tenant_id}",
            client_credential=client_secret,
        )

    async def get_graph_token(self) -> str:
        """Acquire token for Microsoft Graph API."""
        result = self.app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )
        if "access_token" in result:
            return result["access_token"]
        raise Exception(
            f"Token acquisition failed: {result.get('error_description')}"
        )

    async def get_acs_token(self) -> str:
        """Acquire token for ACS if needed (usually connection string is sufficient)."""
        # ACS typically uses connection string auth, not MSAL
        # This method is here if you switch to Entra ID auth for ACS later
        raise NotImplementedError("ACS uses connection string auth by default")
