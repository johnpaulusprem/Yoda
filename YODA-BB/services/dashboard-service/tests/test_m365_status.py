"""Tests for the M365 status check endpoint."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from dashboard_service.routes.health import router as health_router


_BASE_ENV = {
    "DATABASE_URL": "sqlite+aiosqlite://",
    "BASE_URL": "https://test.example.com",
    "AI_FOUNDRY_ENDPOINT": "https://test-ai.openai.azure.com/",
    "AI_FOUNDRY_API_KEY": "test-api-key",
    "REDIS_URL": "redis://localhost:6379/0",
}


@pytest_asyncio.fixture
async def m365_client_configured():
    """Test client with Azure credentials configured."""
    env = {
        **_BASE_ENV,
        "AZURE_TENANT_ID": "test-tenant-id",
        "AZURE_CLIENT_ID": "test-client-id",
        "AZURE_CLIENT_SECRET": "test-client-secret",
    }
    with patch.dict("os.environ", env, clear=False):
        from dashboard_service.config import Settings

        app = FastAPI()
        app.include_router(health_router)
        app.state.settings = Settings()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


@pytest_asyncio.fixture
async def m365_client_missing_tenant():
    """Test client with AZURE_TENANT_ID missing."""
    env = {
        **_BASE_ENV,
        "AZURE_TENANT_ID": "",
        "AZURE_CLIENT_ID": "test-client-id",
        "AZURE_CLIENT_SECRET": "test-client-secret",
    }
    with patch.dict("os.environ", env, clear=False):
        from dashboard_service.config import Settings

        app = FastAPI()
        app.include_router(health_router)
        app.state.settings = Settings()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


@pytest_asyncio.fixture
async def m365_client_missing_both():
    """Test client with both Azure credential fields missing."""
    env = {
        **_BASE_ENV,
        "AZURE_TENANT_ID": "",
        "AZURE_CLIENT_ID": "",
        "AZURE_CLIENT_SECRET": "",
    }
    with patch.dict("os.environ", env, clear=False):
        from dashboard_service.config import Settings

        app = FastAPI()
        app.include_router(health_router)
        app.state.settings = Settings()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


@pytest.mark.asyncio
async def test_m365_status_connected(m365_client_configured):
    """GET /api/dashboard/m365-status returns connected when credentials are set."""
    response = await m365_client_configured.get("/api/dashboard/m365-status")
    assert response.status_code == 200
    data = response.json()
    assert data["connected"] is True
    assert "configured" in data["details"].lower()


@pytest.mark.asyncio
async def test_m365_status_missing_tenant(m365_client_missing_tenant):
    """GET /api/dashboard/m365-status returns not connected when tenant ID is missing."""
    response = await m365_client_missing_tenant.get("/api/dashboard/m365-status")
    assert response.status_code == 200
    data = response.json()
    assert data["connected"] is False
    assert "AZURE_TENANT_ID" in data["details"]


@pytest.mark.asyncio
async def test_m365_status_missing_both(m365_client_missing_both):
    """GET /api/dashboard/m365-status reports both missing credentials."""
    response = await m365_client_missing_both.get("/api/dashboard/m365-status")
    assert response.status_code == 200
    data = response.json()
    assert data["connected"] is False
    assert "AZURE_TENANT_ID" in data["details"]
    assert "AZURE_CLIENT_ID" in data["details"]


@pytest.mark.asyncio
async def test_m365_status_no_auth_required(test_client):
    """M365 status endpoint does not require authentication."""
    response = await test_client.get("/api/dashboard/m365-status")
    assert response.status_code == 200
    data = response.json()
    # Should return a valid response (connected or not), proving no auth wall
    assert "connected" in data
    assert "details" in data
