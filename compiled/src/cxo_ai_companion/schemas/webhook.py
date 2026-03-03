"""Pydantic v2 schemas for Microsoft Graph webhook payloads."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class GraphResourceData(BaseModel):
    """Resource data included in a Microsoft Graph change notification.

    Contains OData metadata and the resource identifier for the changed entity.

    Attributes:
        odata_type: OData type of the resource (aliased from ``@odata.type``).
        odata_id: OData ID of the resource (aliased from ``@odata.id``).
        odata_etag: OData ETag for concurrency (aliased from ``@odata.etag``).
        id: Unique identifier of the changed resource.
    """

    odata_type: str | None = Field(default=None, alias="@odata.type")
    odata_id: str | None = Field(default=None, alias="@odata.id")
    odata_etag: str | None = Field(default=None, alias="@odata.etag")
    id: str


class GraphNotification(BaseModel):
    """A single change notification from Microsoft Graph.

    Graph sends these when a subscribed resource changes (created, updated,
    or deleted). See: https://learn.microsoft.com/en-us/graph/webhooks

    Attributes:
        subscription_id: Graph subscription that triggered this notification.
        subscription_expiration_date_time: When the subscription expires.
        change_type: Kind of change (created, updated, deleted).
        resource: Resource path (e.g. ``users/{id}/events/{id}``).
        resource_data: Embedded resource metadata, if included.
        client_state: Client-supplied secret for validation.
        tenant_id: Azure AD tenant ID where the change occurred.
    """

    subscription_id: str = Field(alias="subscriptionId")
    subscription_expiration_date_time: datetime | None = Field(
        default=None, alias="subscriptionExpirationDateTime"
    )
    change_type: str = Field(alias="changeType")  # created | updated | deleted
    resource: str  # e.g. "users/{userId}/events/{eventId}"
    resource_data: GraphResourceData | None = Field(
        default=None, alias="resourceData"
    )
    client_state: str | None = Field(default=None, alias="clientState")
    tenant_id: str | None = Field(default=None, alias="tenantId")

    model_config = {"populate_by_name": True}


class GraphWebhookPayload(BaseModel):
    """Top-level payload for Microsoft Graph webhook notifications.

    Graph always sends notifications wrapped in a ``value`` array,
    even when there is only a single notification.

    Attributes:
        value: Array of individual change notifications.
    """

    value: list[GraphNotification]

    model_config = {"populate_by_name": True}


class GraphValidationResponse(BaseModel):
    """Response body for Graph subscription validation requests.

    When creating a subscription, Graph sends a validation request with a
    ``validationToken`` query parameter. The endpoint must echo it back
    as plain text with a 200 status.

    Attributes:
        validation_token: The token to echo back to Graph for validation.
    """

    validation_token: str
