"""Tests for the user settings (preferences) API."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from yoda_foundation.models.subscription import UserPreference


@pytest.mark.asyncio
async def test_get_settings_defaults(test_client):
    """GET /api/settings returns defaults when no DB record exists."""
    response = await test_client.get("/api/settings")
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == "test-user-001"
    assert data["opted_in"] is True
    assert data["summary_delivery"] == "chat"
    assert data["notification_channel"] == "chat"
    assert data["auto_join_enabled"] is True
    assert data["nudge_enabled"] is True
    assert data["digest_enabled"] is True


@pytest.mark.asyncio
async def test_get_settings_existing_record(test_client, async_session: AsyncSession):
    """GET /api/settings returns stored preferences when a record exists."""
    pref = UserPreference(
        id=uuid.uuid4(),
        user_id="test-user-001",
        email="alice@contoso.com",
        display_name="Alice Johnson",
        opted_in=True,
        summary_delivery="email",
        notification_channel="email",
        auto_join_enabled=False,
        nudge_enabled=False,
        digest_enabled=True,
    )
    async_session.add(pref)
    await async_session.commit()

    response = await test_client.get("/api/settings")
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == "test-user-001"
    assert data["summary_delivery"] == "email"
    assert data["notification_channel"] == "email"
    assert data["auto_join_enabled"] is False
    assert data["nudge_enabled"] is False
    assert data["digest_enabled"] is True


@pytest.mark.asyncio
async def test_patch_settings_creates_record(test_client, async_session: AsyncSession):
    """PATCH /api/settings creates a new record if none exists (upsert)."""
    response = await test_client.patch(
        "/api/settings",
        json={"summary_delivery": "both", "nudge_enabled": False},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == "test-user-001"
    assert data["summary_delivery"] == "both"
    assert data["nudge_enabled"] is False
    # Defaults for fields not provided
    assert data["notification_channel"] == "chat"
    assert data["auto_join_enabled"] is True
    assert data["digest_enabled"] is True


@pytest.mark.asyncio
async def test_patch_settings_updates_existing(test_client, async_session: AsyncSession):
    """PATCH /api/settings updates only the provided fields on an existing record."""
    pref = UserPreference(
        id=uuid.uuid4(),
        user_id="test-user-001",
        email="alice@contoso.com",
        display_name="Alice Johnson",
        opted_in=True,
        summary_delivery="chat",
        notification_channel="chat",
        auto_join_enabled=True,
        nudge_enabled=True,
        digest_enabled=True,
    )
    async_session.add(pref)
    await async_session.commit()

    response = await test_client.patch(
        "/api/settings",
        json={"auto_join_enabled": False, "digest_enabled": False},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["auto_join_enabled"] is False
    assert data["digest_enabled"] is False
    # Unchanged fields keep their values
    assert data["summary_delivery"] == "chat"
    assert data["notification_channel"] == "chat"
    assert data["nudge_enabled"] is True


@pytest.mark.asyncio
async def test_patch_settings_empty_body(test_client):
    """PATCH /api/settings with empty body creates record with all defaults."""
    response = await test_client.patch("/api/settings", json={})
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == "test-user-001"
    assert data["summary_delivery"] == "chat"
    assert data["auto_join_enabled"] is True


@pytest.mark.asyncio
async def test_patch_settings_single_field(test_client):
    """PATCH /api/settings can update a single field."""
    response = await test_client.patch(
        "/api/settings",
        json={"notification_channel": "email"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["notification_channel"] == "email"
