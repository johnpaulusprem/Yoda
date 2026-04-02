# Microsoft Entra ID Integration — Digital Twin Setup Guide

> **Purpose**: Configure the CXO AI Companion as your digital twin within your Microsoft 365 organization. This gives the app access to your calendar, email, Teams, OneDrive, org directory, and people — all through Microsoft Entra ID (formerly Azure AD).

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Prerequisites](#2-prerequisites)
3. [Step 1 — App Registration in Azure Portal](#3-step-1--app-registration-in-azure-portal)
4. [Step 2 — Configure API Permissions](#4-step-2--configure-api-permissions)
5. [Step 3 — Configure Authentication Platforms](#5-step-3--configure-authentication-platforms)
6. [Step 4 — Expose an API (Backend Token Validation)](#6-step-4--expose-an-api-backend-token-validation)
7. [Step 5 — Certificates & Secrets](#7-step-5--certificates--secrets)
8. [Step 6 — Admin Consent](#8-step-6--admin-consent)
9. [Step 7 — Environment Variables](#9-step-7--environment-variables)
10. [Step 8 — React Frontend MSAL Configuration](#10-step-8--react-frontend-msal-configuration)
11. [Step 9 — Backend Code Changes Required](#11-step-9--backend-code-changes-required)
12. [Step 10 — Verification Checklist](#12-step-10--verification-checklist)
13. [Appendix A — Permission Reference](#appendix-a--permission-reference)
14. [Appendix B — Auth Flow Diagrams](#appendix-b--auth-flow-diagrams)

---

## 1. Architecture Overview

The app uses **two authentication flows** running side by side:

| Flow | Purpose | Who initiates | Token type |
|------|---------|---------------|------------|
| **Delegated (user sign-in)** | React app → user's data | User signs in via browser | User access token (JWT) |
| **Daemon (client-credentials)** | Bot background tasks | App itself (no user) | App-only access token |

```
┌──────────────────────────────────────────────────┐
│  React Frontend                                  │
│  User signs in with org credentials              │
│  (@yourcompany.com via Microsoft Entra ID)       │
│  MSAL.js handles login + token management        │
└──────────────┬───────────────────────────────────┘
               │ Authorization: Bearer <user_token>
               ▼
┌──────────────────────────────────────────────────┐
│  FastAPI Backend                                 │
│                                                  │
│  ┌─ Delegated path (user-facing) ──────────────┐ │
│  │ Validate JWT → extract user identity        │ │
│  │ On-Behalf-Of → Graph API as that user       │ │
│  │ Sees: their calendar, email, files, Teams   │ │
│  └─────────────────────────────────────────────┘ │
│                                                  │
│  ┌─ Daemon path (bot background) ──────────────┐ │
│  │ Client-credentials → app-only token         │ │
│  │ Join calls, process transcripts, send msgs  │ │
│  └─────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────┐
│  Microsoft Graph API                             │
│  /me, /users, /calendar, /mail, /drive, /teams   │
│  /people, /presence, /directReports, /manager    │
└──────────────────────────────────────────────────┘
```

---

## 2. Prerequisites

- [ ] An **Azure subscription** with an Entra ID tenant
- [ ] **Global Administrator** or **Application Administrator** role in the tenant (for admin consent)
- [ ] A **Microsoft 365 Business** or **Enterprise** license (for Graph API access to mail, calendar, Teams)
- [ ] The existing app registration (used for daemon flow) — or create a new one

---

## 3. Step 1 — App Registration in Azure Portal

> If you already have an app registration for the daemon flow, you can reuse it. Adding delegated permissions to the same registration is fine.

### Create New (if needed)

1. Go to [Azure Portal](https://portal.azure.com) → **Microsoft Entra ID** → **App registrations**
2. Click **+ New registration**
3. Fill in:
   - **Name**: `CXO AI Companion`
   - **Supported account types**: Select **"Accounts in this organizational directory only"** (single tenant)
   - **Redirect URI**: Skip for now (configured in Step 3)
4. Click **Register**
5. Note down:
   - **Application (client) ID**: `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`
   - **Directory (tenant) ID**: `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`

### Use Existing

If reusing your existing app registration, just note the client ID and tenant ID and proceed to Step 2.

---

## 4. Step 2 — Configure API Permissions

Navigate to: **App registration** → **API permissions** → **+ Add a permission** → **Microsoft Graph**

### Delegated Permissions (for user sign-in flow)

Add the following **Delegated** permissions:

| Permission | Category | What it gives access to |
|------------|----------|------------------------|
| `User.Read` | User | Sign in and read the signed-in user's profile |
| `User.ReadBasic.All` | User | Read basic profiles of all users in the org |
| `Calendars.Read` | Calendar | Read the user's calendar events |
| `Calendars.ReadWrite` | Calendar | Read and create calendar events (optional — for scheduling) |
| `Mail.Read` | Mail | Read the user's email messages |
| `Mail.Send` | Mail | Send email as the user (optional — for sharing summaries) |
| `Files.Read.All` | Files | Read all files the user can access (OneDrive + SharePoint) |
| `Chat.Read` | Teams | Read the user's Teams chat messages |
| `ChannelMessage.Read.All` | Teams | Read Teams channel messages |
| `People.Read` | People | Read the user's relevant people (frequent contacts) |
| `Presence.Read.All` | Presence | Read presence/availability status of org users |
| `Contacts.Read` | Contacts | Read the user's contacts |
| `Directory.Read.All` | Directory | Read org directory data (users, groups, org structure) |
| `OnlineMeetings.Read` | Meetings | Read the user's online meeting details |

### Application Permissions (for daemon/bot flow — may already exist)

Verify these **Application** permissions are present:

| Permission | What it's for |
|------------|---------------|
| `Calendars.Read` | Bot reads calendar events to detect meetings |
| `OnlineMeetings.Read.All` | Bot reads meeting metadata to join |
| `Chat.ReadWrite.All` | Bot sends proactive messages |
| `User.Read.All` | Bot looks up user profiles |

### How to Add

1. Click **+ Add a permission**
2. Select **Microsoft Graph**
3. Select **Delegated permissions**
4. Search for each permission name and check the box
5. Click **Add permissions**
6. Repeat for Application permissions if needed

---

## 5. Step 3 — Configure Authentication Platforms

Navigate to: **App registration** → **Authentication**

### Add Single-Page Application (SPA) Platform

1. Click **+ Add a platform**
2. Select **Single-page application**
3. Add **Redirect URIs**:
   - `http://localhost:3000` (local development)
   - `http://localhost:3000/auth/callback` (local callback)
   - `https://your-production-domain.com` (production)
   - `https://your-production-domain.com/auth/callback` (production callback)
4. Under **Implicit grant and hybrid flows**:
   - **Access tokens**: Leave UNCHECKED (SPA uses PKCE, not implicit)
   - **ID tokens**: Leave UNCHECKED
5. Click **Configure**

### Add Web Platform (for backend OBO flow)

1. Click **+ Add a platform**
2. Select **Web**
3. Add **Redirect URI**: `https://your-api-domain.com/auth/callback` (or `http://localhost:8000/auth/callback` for dev)
4. Click **Configure**

### Supported Account Types

Verify: **"Accounts in this organizational directory only"** is selected (single-tenant). This restricts access to your organization's Microsoft 365 users only.

---

## 6. Step 4 — Expose an API (Backend Token Validation)

This step creates a **scope** so your React app can request tokens specifically for your backend API.

Navigate to: **App registration** → **Expose an API**

1. Click **Set** next to "Application ID URI"
   - Accept the default: `api://YOUR_CLIENT_ID`
   - Or set a custom URI: `api://cxo-ai-companion`
2. Click **+ Add a scope**
   - **Scope name**: `access_as_user`
   - **Who can consent**: Admins and users
   - **Admin consent display name**: `Access CXO AI Companion as signed-in user`
   - **Admin consent description**: `Allows the app to access the CXO AI Companion API on behalf of the signed-in user`
   - **User consent display name**: `Access CXO AI Companion`
   - **User consent description**: `Allow the app to access CXO AI Companion on your behalf`
   - **State**: Enabled
3. Click **Add scope**

Note the full scope value: `api://YOUR_CLIENT_ID/access_as_user`

### Add Authorized Client Application

1. Click **+ Add a client application**
2. Enter your **React app's Client ID** (same client ID if single registration, or the separate frontend app ID if you have two registrations)
3. Check the `access_as_user` scope
4. Click **Add application**

---

## 7. Step 5 — Certificates & Secrets

Navigate to: **App registration** → **Certificates & secrets**

### For Development

1. Click **+ New client secret**
2. **Description**: `dev-backend-secret`
3. **Expires**: 6 months (or your org policy)
4. Click **Add**
5. **Copy the Value immediately** — it's only shown once

### For Production (Recommended: Certificate)

For production, use a certificate instead of a secret:
1. Click **Upload certificate**
2. Upload a `.cer` or `.pem` file
3. This is more secure and doesn't expire as frequently

---

## 8. Step 6 — Admin Consent

Navigate to: **App registration** → **API permissions**

1. Click **Grant admin consent for [Your Organization]**
2. Confirm by clicking **Yes**
3. All permissions should now show a green checkmark under "Status"

> **Important**: Without admin consent, users will see a consent prompt on first login. Some permissions (like `Directory.Read.All`) **require** admin consent and won't work without it.

---

## 9. Step 7 — Environment Variables

Add these to your `.env` file (backend):

```env
# ── Entra ID / Azure AD ──────────────────────────────────
AZURE_TENANT_ID=your-tenant-id-here
AZURE_CLIENT_ID=your-client-id-here
AZURE_CLIENT_SECRET=your-client-secret-here

# ── Token Validation (new for delegated flow) ────────────
AZURE_AUTHORITY=https://login.microsoftonline.com/your-tenant-id-here
AZURE_API_SCOPE=api://your-client-id-here/access_as_user
AZURE_JWKS_URI=https://login.microsoftonline.com/your-tenant-id-here/discovery/v2.0/keys
AZURE_ISSUER=https://login.microsoftonline.com/your-tenant-id-here/v2.0

# ── Existing (no changes) ────────────────────────────────
ACS_CONNECTION_STRING=...
ACS_ENDPOINT=...
AI_FOUNDRY_ENDPOINT=...
AI_FOUNDRY_API_KEY=...
DATABASE_URL=...
BASE_URL=...
```

Add these to your React app's `.env`:

```env
# ── React Frontend ───────────────────────────────────────
REACT_APP_AZURE_CLIENT_ID=your-client-id-here
REACT_APP_AZURE_TENANT_ID=your-tenant-id-here
REACT_APP_AZURE_REDIRECT_URI=http://localhost:3000
REACT_APP_API_BASE_URL=http://localhost:8000
REACT_APP_API_SCOPE=api://your-client-id-here/access_as_user
```

---

## 10. Step 8 — React Frontend MSAL Configuration

> **Type**: Configuration + small code

### Install MSAL

```bash
npm install @azure/msal-browser @azure/msal-react
```

### Configuration File

Create `src/auth/authConfig.ts`:

```typescript
import { Configuration, LogLevel } from "@azure/msal-browser";

export const msalConfig: Configuration = {
  auth: {
    clientId: process.env.REACT_APP_AZURE_CLIENT_ID!,
    authority: `https://login.microsoftonline.com/${process.env.REACT_APP_AZURE_TENANT_ID}`,
    redirectUri: process.env.REACT_APP_AZURE_REDIRECT_URI || "http://localhost:3000",
  },
  cache: {
    cacheLocation: "sessionStorage",   // "localStorage" for persistent login
    storeAuthStateInCookie: false,
  },
  system: {
    loggerOptions: {
      logLevel: LogLevel.Warning,
    },
  },
};

// Scopes for the backend API
export const apiRequest = {
  scopes: [process.env.REACT_APP_API_SCOPE!],
};

// Scopes for direct Graph calls (if React calls Graph directly)
export const graphRequest = {
  scopes: ["User.Read", "People.Read"],
};
```

### Wrap App with MSAL Provider

In `src/index.tsx` or `src/App.tsx`:

```typescript
import { PublicClientApplication } from "@azure/msal-browser";
import { MsalProvider } from "@azure/msal-react";
import { msalConfig } from "./auth/authConfig";

const msalInstance = new PublicClientApplication(msalConfig);

// In your render:
<MsalProvider instance={msalInstance}>
  <App />
</MsalProvider>
```

### Add Login Button

```typescript
import { useMsal } from "@azure/msal-react";
import { apiRequest } from "./auth/authConfig";

function LoginButton() {
  const { instance } = useMsal();

  const handleLogin = () => {
    instance.loginPopup(apiRequest);   // or loginRedirect(apiRequest)
  };

  return <button onClick={handleLogin}>Sign in with Microsoft</button>;
}
```

### Attach Token to API Calls

```typescript
import { useMsal } from "@azure/msal-react";
import { apiRequest } from "./auth/authConfig";

async function callBackendApi(endpoint: string) {
  const { instance, accounts } = useMsal();

  const response = await instance.acquireTokenSilent({
    ...apiRequest,
    account: accounts[0],
  });

  const result = await fetch(`${process.env.REACT_APP_API_BASE_URL}${endpoint}`, {
    headers: {
      Authorization: `Bearer ${response.accessToken}`,
    },
  });

  return result.json();
}
```

---

## 11. Step 9 — Backend Code Changes Required

> **Type**: Code (new files + updates to existing files)

The following backend changes are needed. These are NOT configuration — they require Python code.

### 9a. New File: `security/jwt_validator.py`

**Purpose**: Validate the JWT access token sent by the React frontend.

**What it does**:
- Downloads Microsoft's public signing keys (JWKS) from `https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys`
- Validates the JWT signature, expiry, audience, and issuer
- Extracts user identity: `oid` (user ID), `tid` (tenant ID), `name`, `preferred_username` (email), `roles`
- Returns a `SecurityContext` object

**Dependencies**: `pip install PyJWT cryptography`

### 9b. New File: `api/rest/dependencies/auth.py`

**Purpose**: FastAPI dependency that extracts the Bearer token from the request and returns a `SecurityContext`.

**What it does**:
- Reads `Authorization: Bearer <token>` header
- Calls `jwt_validator` to validate and decode
- Returns `SecurityContext(user_id=..., tenant_id=..., context_type=USER)`
- Routes can then use: `ctx: SecurityContext = Depends(get_current_user)`

### 9c. Update: `utilities/auth/token_provider.py`

**Purpose**: Add On-Behalf-Of (OBO) flow method.

**What to add**:
- New method: `acquire_token_on_behalf_of(user_token, scopes)`
- Uses `msal.ConfidentialClientApplication.acquire_token_on_behalf_of()`
- This lets the backend call Graph API as the signed-in user (not as the app)

### 9d. Update: `config/settings.py`

**Purpose**: Add new environment variables for token validation.

**What to add**:
- `AZURE_API_SCOPE: str`
- `AZURE_JWKS_URI: str`
- `AZURE_ISSUER: str`

---

## 12. Step 10 — Verification Checklist

After completing all steps, verify:

### Azure Portal

- [ ] App registration exists with correct client ID and tenant ID
- [ ] SPA platform added with redirect URIs
- [ ] Delegated permissions added (User.Read, Calendars.Read, Mail.Read, etc.)
- [ ] Application permissions present (for daemon flow)
- [ ] Admin consent granted (green checkmarks on all permissions)
- [ ] API exposed with `access_as_user` scope
- [ ] Client secret or certificate configured

### React Frontend

- [ ] `@azure/msal-browser` and `@azure/msal-react` installed
- [ ] `authConfig.ts` created with correct client ID and tenant ID
- [ ] `MsalProvider` wrapping the app
- [ ] Login button working — user can sign in with org credentials
- [ ] Token attached to API calls in `Authorization` header

### Backend

- [ ] JWT validation middleware accepting and decoding tokens
- [ ] `SecurityContext` populated with user identity from token
- [ ] OBO flow working — backend can call Graph API as the user
- [ ] Protected routes returning user-specific data (calendar, email, etc.)

### End-to-End Test

1. Open React app → click "Sign in with Microsoft"
2. Sign in with your `@yourcompany.com` account
3. App should display your name and profile picture
4. Navigate to calendar view → should show YOUR calendar events
5. Navigate to email insights → should show YOUR recent emails
6. Navigate to Teams chats → should show YOUR conversations
7. Navigate to files → should show YOUR OneDrive/SharePoint documents

---

## Appendix A — Permission Reference

### What Each Delegated Permission Unlocks

| Permission | Graph API Endpoints | Digital Twin Feature |
|------------|--------------------|--------------------|
| `User.Read` | `/me` | User profile, photo, sign-in |
| `User.ReadBasic.All` | `/users` | Org directory, search people |
| `Calendars.Read` | `/me/calendar/events` | Calendar view, meeting detection |
| `Calendars.ReadWrite` | `/me/calendar/events` | Schedule meetings from app |
| `Mail.Read` | `/me/messages` | Email insights, pre-meeting briefs |
| `Mail.Send` | `/me/sendMail` | Share summaries via email |
| `Files.Read.All` | `/me/drive`, `/sites` | OneDrive/SharePoint document access |
| `Chat.Read` | `/me/chats` | Teams chat context for meetings |
| `ChannelMessage.Read.All` | `/teams/{id}/channels/{id}/messages` | Teams channel discussions |
| `People.Read` | `/me/people` | Frequent contacts, collaboration graph |
| `Presence.Read.All` | `/communications/presences` | Teams online/offline status |
| `Contacts.Read` | `/me/contacts` | Personal contacts |
| `Directory.Read.All` | `/users`, `/groups`, `/directoryRoles` | Org chart, groups, departments |
| `OnlineMeetings.Read` | `/me/onlineMeetings` | Meeting details, join URLs |

### Application vs Delegated — When to Use Which

| Scenario | Use |
|----------|-----|
| User browses their calendar in the React app | **Delegated** (user's token) |
| Bot joins a Teams call automatically | **Application** (daemon token) |
| User searches for colleagues | **Delegated** (user's token) |
| Bot processes a transcript in the background | **Application** (daemon token) |
| User shares a summary via email | **Delegated** (sends as the user) |
| Bot sends a proactive notification to Teams | **Application** (daemon token) |

---

## Appendix B — Auth Flow Diagrams

### Delegated Flow (User Sign-In)

```
1. User opens React app
2. React calls msalInstance.loginPopup()
3. Browser redirects to: https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize
4. User enters org credentials (@yourcompany.com)
5. Entra ID validates credentials against org directory
6. Entra ID returns authorization code to React redirect URI
7. MSAL.js exchanges code for tokens (using PKCE — no secret needed in browser)
8. React receives: ID token (who the user is) + Access token (what they can access)
9. React stores tokens in sessionStorage
10. Every API call: fetch("/api/...", { headers: { Authorization: "Bearer <access_token>" } })
11. FastAPI validates JWT, extracts user identity, processes request
```

### On-Behalf-Of Flow (Backend Calls Graph as User)

```
1. React sends user's access token to FastAPI endpoint
2. FastAPI validates the token (JWT signature + claims)
3. FastAPI calls MSAL: acquire_token_on_behalf_of(user_token, ["https://graph.microsoft.com/.default"])
4. MSAL exchanges user's token for a Graph API token scoped to that user
5. FastAPI calls Graph API with the new token
6. Graph API returns data visible to THAT user (their calendar, their email, etc.)
7. FastAPI returns response to React
```

### Daemon Flow (Existing — No Changes)

```
1. Bot scheduler triggers (e.g., calendar check, nudge)
2. Backend calls MSAL: acquire_token_for_client(["https://graph.microsoft.com/.default"])
3. MSAL returns app-only token (no user context)
4. Backend calls Graph API with app permissions
5. Graph API returns org-wide data (all users' calendars, etc.)
```

---

## Summary

| Step | Type | Where |
|------|------|-------|
| 1. App registration | Configuration | Azure Portal |
| 2. API permissions | Configuration | Azure Portal |
| 3. Authentication platforms | Configuration | Azure Portal |
| 4. Expose an API | Configuration | Azure Portal |
| 5. Secrets/certificates | Configuration | Azure Portal |
| 6. Admin consent | Configuration | Azure Portal |
| 7. Environment variables | Configuration | `.env` files |
| 8. React MSAL setup | Configuration + Code | React frontend |
| 9a. JWT validator | **Code** | `security/jwt_validator.py` |
| 9b. Auth dependency | **Code** | `api/rest/dependencies/auth.py` |
| 9c. OBO flow | **Code** | `utilities/auth/token_provider.py` |
| 9d. Settings update | **Code** | `config/settings.py` |

**Steps 1-8 are configuration. Steps 9a-9d require backend Python code.**
