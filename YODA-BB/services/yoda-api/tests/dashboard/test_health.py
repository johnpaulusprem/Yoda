"""Tests for the health endpoint."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_health_endpoint(test_client):
    """GET /health returns healthy status."""
    response = await test_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "dashboard-service"
