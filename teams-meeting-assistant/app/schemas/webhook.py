"""Pydantic schemas for Microsoft Graph webhook payloads."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class GraphResourceData(BaseModel):
    """Resource data included in a Graph change notification."""

    odata_type: str | None = Field(None, alias="@odata.type")
    odata_id: str | None = Field(None, alias="@odata.id")
    odata_etag: str | None = Field(None, alias="@odata.etag")
    id: str


class GraphChangeNotification(BaseModel):
    """A single change notification from Microsoft Graph.

    Graph sends these when a subscribed resource changes.
    See: https://learn.microsoft.com/en-us/graph/webhooks#notification-payload
    """

    subscription_id: str = Field(alias="subscriptionId")
    subscription_expiration_date_time: datetime | None = Field(
        None, alias="subscriptionExpirationDateTime"
    )
    change_type: str = Field(alias="changeType")  # "created", "updated", "deleted"
    resource: str  # e.g. "users/{userId}/events/{eventId}"
    resource_data: GraphResourceData | None = Field(None, alias="resourceData")
    client_state: str | None = Field(None, alias="clientState")
    tenant_id: str | None = Field(None, alias="tenantId")

    model_config = {"populate_by_name": True}


class GraphWebhookPayload(BaseModel):
    """Top-level payload for Graph webhook notifications.

    Graph always sends notifications wrapped in a `value` array,
    even when there is only a single notification.
    """

    value: list[GraphChangeNotification]

    model_config = {"populate_by_name": True}
