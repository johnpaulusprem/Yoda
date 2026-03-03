#!/usr/bin/env bash
# ---------------------------------------------------------------------------
#  Grant admin consent for Microsoft Graph API permissions
# ---------------------------------------------------------------------------
#
# This script constructs the admin-consent URL for the Entra ID (Azure AD)
# app registration used by the Teams Meeting Assistant Bot and opens it in
# the default browser.
#
# Prerequisites:
#   - The app registration must already exist in the Azure portal.
#   - Required Graph API **application** permissions should be added to the
#     app registration BEFORE running this script:
#       * Calendars.Read          - read calendar events
#       * OnlineMeetings.Read.All - read online meeting details
#       * Chat.ReadWrite.All      - post Adaptive Cards to meeting chats
#       * User.Read.All           - resolve action item owners
#       * Calls.JoinGroupCall.All - (optional, for Graph-based call join)
#   - The person running this script must be a **tenant administrator**.
#
# Usage:
#   1. Set APP_ID and TENANT_ID below (or export them as env vars).
#   2. Run:  ./grant_graph_permissions.sh
#   3. Sign in as a tenant admin in the browser window that opens.
#   4. Click "Accept" to grant admin consent.
#
# After consent is granted the bot can acquire app-only tokens via the
# client-credentials (daemon) flow and call Graph API without any user
# interaction.
# ---------------------------------------------------------------------------

set -euo pipefail

# ---------- Configuration ----------

# Read from environment or fall back to placeholders.
APP_ID="${AZURE_CLIENT_ID:-your-app-client-id}"
TENANT_ID="${AZURE_TENANT_ID:-your-tenant-id}"
REDIRECT_URI="https://localhost"

# ---------- Validation ----------

if [[ "$APP_ID" == "your-app-client-id" ]]; then
    echo "ERROR: AZURE_CLIENT_ID is not set."
    echo ""
    echo "Either export it as an environment variable:"
    echo "  export AZURE_CLIENT_ID=<your-app-registration-client-id>"
    echo ""
    echo "Or edit this script and replace the placeholder."
    exit 1
fi

if [[ "$TENANT_ID" == "your-tenant-id" ]]; then
    echo "ERROR: AZURE_TENANT_ID is not set."
    echo ""
    echo "Either export it as an environment variable:"
    echo "  export AZURE_TENANT_ID=<your-azure-ad-tenant-id>"
    echo ""
    echo "Or edit this script and replace the placeholder."
    exit 1
fi

# ---------- Build consent URL ----------

CONSENT_URL="https://login.microsoftonline.com/${TENANT_ID}/adminconsent?client_id=${APP_ID}&redirect_uri=${REDIRECT_URI}"

echo "================================================================"
echo "  Grant Admin Consent for Graph API Permissions"
echo "================================================================"
echo ""
echo "  Tenant ID  : ${TENANT_ID}"
echo "  Client ID  : ${APP_ID}"
echo "  Redirect   : ${REDIRECT_URI}"
echo ""
echo "  Consent URL:"
echo "  ${CONSENT_URL}"
echo ""
echo "----------------------------------------------------------------"
echo "  Sign in as a tenant administrator and click 'Accept' to"
echo "  grant the requested application permissions."
echo "----------------------------------------------------------------"
echo ""

# ---------- Open in browser ----------

open_url() {
    local url="$1"
    if command -v open &> /dev/null; then
        # macOS
        open "$url"
    elif command -v xdg-open &> /dev/null; then
        # Linux (freedesktop)
        xdg-open "$url"
    elif command -v wslview &> /dev/null; then
        # Windows Subsystem for Linux
        wslview "$url"
    elif command -v explorer.exe &> /dev/null; then
        # WSL fallback
        explorer.exe "$url"
    else
        echo "Could not detect a browser opener."
        echo "Please open the URL above manually in your browser."
        return 1
    fi
}

read -rp "Open the consent URL in your browser now? [Y/n] " answer
answer="${answer:-Y}"

if [[ "$answer" =~ ^[Yy] ]]; then
    echo "Opening browser..."
    open_url "$CONSENT_URL" || true
    echo ""
    echo "If the browser did not open, copy and paste the URL above."
else
    echo ""
    echo "Skipped.  Copy the URL above and open it in a browser manually."
fi

echo ""
echo "After granting consent, the app can use the client-credentials"
echo "flow to call Microsoft Graph API without user interaction."
echo ""
echo "Done."
