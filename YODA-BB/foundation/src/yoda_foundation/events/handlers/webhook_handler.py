"""
Webhook event handler for forwarding events to HTTP endpoints.

This module provides a webhook handler that forwards events to
configured HTTP endpoints with retry logic and signature verification.

Example:
    ```python
    from yoda_foundation.events.handlers import (
        WebhookEventHandler,
        WebhookConfig,
        WebhookEndpoint,
    )

    # Configure webhook endpoint
    endpoint = WebhookEndpoint(
        url="https://api.example.com/webhook",
        secret="webhook_secret_key",
        headers={"X-API-Key": "api_key"},
    )

    # Create handler
    handler = WebhookEventHandler(
        config=WebhookConfig(
            endpoints=[endpoint],
            max_retries=3,
            timeout_seconds=30.0,
            sign_payloads=True,
        ),
    )

    # Forward event
    await handler.handle(event, security_context)
    ```
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from yoda_foundation.events.bus.event_bus import Event
from yoda_foundation.events.handlers.event_handler import EventHandler, HandlerConfig
from yoda_foundation.exceptions import (
    ValidationError,
    WebhookDeliveryError,
)
from yoda_foundation.security import SecurityContext


logger = logging.getLogger(__name__)


class WebhookStatus(Enum):
    """
    Status of webhook delivery.

    Attributes:
        PENDING: Delivery pending
        DELIVERED: Successfully delivered
        FAILED: Delivery failed
        RETRYING: Retrying delivery

    Example:
        ```python
        if result.status == WebhookStatus.DELIVERED:
            print("Webhook delivered successfully")
        ```
    """

    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"
    RETRYING = "retrying"


@dataclass
class WebhookEndpoint:
    """
    Configuration for a webhook endpoint.

    Attributes:
        url: Webhook URL
        secret: Secret for HMAC signature (optional)
        headers: Custom headers to include
        event_types: Event types to forward (empty = all)
        enabled: Whether endpoint is enabled
        name: Endpoint name for identification

    Example:
        ```python
        endpoint = WebhookEndpoint(
            url="https://api.example.com/webhook",
            secret="my_secret_key",
            headers={"X-API-Key": "api_key"},
            event_types=["agent.completed", "tool.error"],
            name="main_webhook",
        )
        ```
    """

    url: str
    secret: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    event_types: list[str] = field(default_factory=list)
    enabled: bool = True
    name: str = ""

    def __post_init__(self) -> None:
        """Validate endpoint configuration."""
        if not self.url:
            raise ValidationError(
                message="Webhook URL cannot be empty",
                field_name="url",
            )
        if not self.name:
            # Generate name from URL
            from urllib.parse import urlparse

            parsed = urlparse(self.url)
            self.name = parsed.netloc.replace(".", "_")

    def should_receive(self, event: Event) -> bool:
        """
        Check if endpoint should receive this event.

        Args:
            event: Event to check

        Returns:
            True if endpoint should receive event
        """
        if not self.enabled:
            return False
        if not self.event_types:
            return True
        return any(event.matches_pattern(pattern) for pattern in self.event_types)


@dataclass
class WebhookDeliveryResult:
    """
    Result of webhook delivery attempt.

    Attributes:
        endpoint_name: Name of the endpoint
        event_id: Event that was delivered
        status: Delivery status
        status_code: HTTP status code (if delivered)
        response_body: Response body (if delivered)
        error_message: Error message (if failed)
        attempts: Number of delivery attempts
        delivered_at: When delivery succeeded
        latency_ms: Delivery latency in milliseconds

    Example:
        ```python
        result = await handler.deliver(event, endpoint, security_context)
        if result.status == WebhookStatus.DELIVERED:
            print(f"Delivered in {result.latency_ms}ms")
        else:
            print(f"Failed: {result.error_message}")
        ```
    """

    endpoint_name: str
    event_id: str
    status: WebhookStatus = WebhookStatus.PENDING
    status_code: int | None = None
    response_body: str | None = None
    error_message: str | None = None
    attempts: int = 0
    delivered_at: datetime | None = None
    latency_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary."""
        return {
            "endpoint_name": self.endpoint_name,
            "event_id": self.event_id,
            "status": self.status.value,
            "status_code": self.status_code,
            "response_body": self.response_body,
            "error_message": self.error_message,
            "attempts": self.attempts,
            "delivered_at": (self.delivered_at.isoformat() if self.delivered_at else None),
            "latency_ms": self.latency_ms,
        }


@dataclass
class WebhookConfig(HandlerConfig):
    """
    Configuration for webhook handler.

    Attributes:
        endpoints: List of webhook endpoints
        sign_payloads: Sign payloads with HMAC
        signature_header: Header name for signature
        signature_algorithm: HMAC algorithm (sha256, sha512)
        include_timestamp: Include timestamp in signature
        timestamp_header: Header name for timestamp
        retry_delays: Delay between retries (seconds)
        verify_ssl: Verify SSL certificates
        parallel_delivery: Deliver to endpoints in parallel

    Example:
        ```python
        config = WebhookConfig(
            endpoints=[endpoint1, endpoint2],
            sign_payloads=True,
            signature_header="X-Signature",
            max_retries=3,
            timeout_seconds=30.0,
        )
        ```
    """

    endpoints: list[WebhookEndpoint] = field(default_factory=list)
    sign_payloads: bool = True
    signature_header: str = "X-Webhook-Signature"
    signature_algorithm: str = "sha256"
    include_timestamp: bool = True
    timestamp_header: str = "X-Webhook-Timestamp"
    retry_delays: list[float] = field(default_factory=lambda: [1.0, 5.0, 30.0])
    verify_ssl: bool = True
    parallel_delivery: bool = True


class WebhookEventHandler(EventHandler):
    """
    Webhook event handler for forwarding events to HTTP endpoints.

    Provides:
    - HMAC signature verification
    - Automatic retries with backoff
    - Parallel or sequential delivery
    - Event type filtering

    Attributes:
        name: Handler name
        config: Handler configuration

    Example:
        ```python
        # Configure endpoints
        endpoints = [
            WebhookEndpoint(
                url="https://api.example.com/events",
                secret="secret1",
                event_types=["agent.*"],
            ),
            WebhookEndpoint(
                url="https://backup.example.com/events",
                secret="secret2",
            ),
        ]

        # Create handler
        handler = WebhookEventHandler(
            config=WebhookConfig(
                endpoints=endpoints,
                sign_payloads=True,
                max_retries=3,
            ),
        )

        # Handle events
        await handler.handle(event, security_context)

        # Get delivery results
        results = handler.get_delivery_results(event.event_id)
        for result in results:
            print(f"{result.endpoint_name}: {result.status.value}")
        ```

    Raises:
        WebhookDeliveryError: If delivery fails to all endpoints
        EventHandlerError: If handler operation fails
    """

    name: str = "webhook_handler"

    def __init__(
        self,
        config: WebhookConfig | None = None,
    ) -> None:
        """
        Initialize webhook handler.

        Args:
            config: Handler configuration
        """
        self._webhook_config = config or WebhookConfig()
        super().__init__(config=self._webhook_config)

        self._http_client: Any | None = None
        self._delivery_results: dict[str, list[WebhookDeliveryResult]] = {}

    async def handle(
        self,
        event: Event,
        security_context: SecurityContext,
    ) -> None:
        """
        Handle an event by forwarding to webhooks.

        Args:
            event: Event to forward
            security_context: Security context for authorization

        Raises:
            WebhookDeliveryError: If delivery fails to all endpoints
            AuthorizationError: If user lacks permission

        Example:
            ```python
            await handler.handle(event, security_context)
            ```
        """
        security_context.require_permission("webhook.deliver")

        # Get applicable endpoints
        endpoints = [ep for ep in self._webhook_config.endpoints if ep.should_receive(event)]

        if not endpoints:
            self._logger.debug(f"No endpoints configured for event {event.event_type}")
            return

        # Deliver to endpoints
        results: list[WebhookDeliveryResult] = []

        if self._webhook_config.parallel_delivery:
            # Parallel delivery
            tasks = [self._deliver_to_endpoint(event, endpoint) for endpoint in endpoints]
            results = await asyncio.gather(*tasks, return_exceptions=False)
        else:
            # Sequential delivery
            for endpoint in endpoints:
                result = await self._deliver_to_endpoint(event, endpoint)
                results.append(result)

        # Store results
        self._delivery_results[event.event_id] = results

        # Check if all failed
        all_failed = all(r.status == WebhookStatus.FAILED for r in results)
        if all_failed and results:
            errors = [r.error_message for r in results if r.error_message]
            raise WebhookDeliveryError(
                message=f"All webhook deliveries failed: {errors}",
                webhook_url="multiple",
                event_id=event.event_id,
                retry_count=max(r.attempts for r in results),
            )

    async def can_handle(self, event: Event) -> bool:
        """
        Check if handler can process the event.

        Returns True if any endpoint is configured to receive the event.

        Args:
            event: Event to check

        Returns:
            True if any endpoint can receive the event
        """
        return any(ep.should_receive(event) for ep in self._webhook_config.endpoints)

    def add_endpoint(self, endpoint: WebhookEndpoint) -> None:
        """
        Add a webhook endpoint.

        Args:
            endpoint: Endpoint to add

        Example:
            ```python
            handler.add_endpoint(
                WebhookEndpoint(
                    url="https://new.example.com/webhook",
                    secret="new_secret",
                ),
            )
            ```
        """
        self._webhook_config.endpoints.append(endpoint)
        self._logger.info(
            f"Added webhook endpoint: {endpoint.name}",
            extra={"url": endpoint.url},
        )

    def remove_endpoint(self, name: str) -> bool:
        """
        Remove a webhook endpoint by name.

        Args:
            name: Endpoint name

        Returns:
            True if endpoint was removed

        Example:
            ```python
            removed = handler.remove_endpoint("old_webhook")
            ```
        """
        for i, ep in enumerate(self._webhook_config.endpoints):
            if ep.name == name:
                del self._webhook_config.endpoints[i]
                self._logger.info(f"Removed webhook endpoint: {name}")
                return True
        return False

    def get_endpoints(self) -> list[WebhookEndpoint]:
        """Get all configured endpoints."""
        return self._webhook_config.endpoints

    def get_delivery_results(
        self,
        event_id: str,
    ) -> list[WebhookDeliveryResult]:
        """
        Get delivery results for an event.

        Args:
            event_id: Event identifier

        Returns:
            List of delivery results

        Example:
            ```python
            results = handler.get_delivery_results(event.event_id)
            for result in results:
                if result.status == WebhookStatus.DELIVERED:
                    print(f"{result.endpoint_name}: OK")
            ```
        """
        return self._delivery_results.get(event_id, [])

    def clear_delivery_results(self, event_id: str | None = None) -> None:
        """
        Clear delivery results.

        Args:
            event_id: Specific event ID to clear, or None for all

        Example:
            ```python
            handler.clear_delivery_results()  # Clear all
            handler.clear_delivery_results(event_id)  # Clear specific
            ```
        """
        if event_id:
            self._delivery_results.pop(event_id, None)
        else:
            self._delivery_results.clear()

    async def verify_signature(
        self,
        payload: bytes,
        signature: str,
        secret: str,
        timestamp: str | None = None,
    ) -> bool:
        """
        Verify webhook signature.

        Can be used by receivers to verify incoming webhooks.

        Args:
            payload: Raw payload bytes
            signature: Signature to verify
            secret: Secret key
            timestamp: Timestamp (if included in signature)

        Returns:
            True if signature is valid

        Example:
            ```python
            is_valid = await handler.verify_signature(
                payload=request.body,
                signature=request.headers["X-Webhook-Signature"],
                secret="webhook_secret",
            )
            if not is_valid:
                raise HTTPException(401, "Invalid signature")
            ```
        """
        computed = self._compute_signature(payload, secret, timestamp)
        return hmac.compare_digest(computed, signature)

    async def _deliver_to_endpoint(
        self,
        event: Event,
        endpoint: WebhookEndpoint,
    ) -> WebhookDeliveryResult:
        """Deliver event to a single endpoint with retry."""
        result = WebhookDeliveryResult(
            endpoint_name=endpoint.name,
            event_id=event.event_id,
        )

        # Prepare payload
        payload = json.dumps(event.to_dict()).encode("utf-8")

        # Prepare headers
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "AgenticAI-Webhook/1.0",
            **endpoint.headers,
        }

        # Add timestamp
        timestamp: str | None = None
        if self._webhook_config.include_timestamp:
            timestamp = str(int(time.time()))
            headers[self._webhook_config.timestamp_header] = timestamp

        # Add signature
        if self._webhook_config.sign_payloads and endpoint.secret:
            signature = self._compute_signature(payload, endpoint.secret, timestamp)
            headers[self._webhook_config.signature_header] = signature

        # Attempt delivery with retries
        retry_delays = [0.0] + list(self._webhook_config.retry_delays)
        max_attempts = min(
            len(retry_delays),
            self._webhook_config.max_retries + 1,
        )

        for attempt in range(max_attempts):
            result.attempts = attempt + 1

            if attempt > 0:
                result.status = WebhookStatus.RETRYING
                await asyncio.sleep(retry_delays[attempt])

            start_time = time.time()

            try:
                status_code, response_body = await self._send_request(
                    url=endpoint.url,
                    payload=payload,
                    headers=headers,
                )

                result.latency_ms = (time.time() - start_time) * 1000
                result.status_code = status_code
                result.response_body = response_body

                # Check for success
                if 200 <= status_code < 300:
                    result.status = WebhookStatus.DELIVERED
                    result.delivered_at = datetime.now(UTC)

                    self._logger.info(
                        f"Webhook delivered to {endpoint.name}",
                        extra={
                            "endpoint": endpoint.name,
                            "event_id": event.event_id,
                            "status_code": status_code,
                            "latency_ms": result.latency_ms,
                        },
                    )
                    return result

                # Retry on server errors
                if status_code >= 500:
                    result.error_message = f"Server error: {status_code} - {response_body}"
                    continue

                # Don't retry on client errors (4xx)
                result.status = WebhookStatus.FAILED
                result.error_message = f"Client error: {status_code} - {response_body}"
                return result

            except TimeoutError:
                result.error_message = "Request timeout"
                self._logger.warning(
                    f"Webhook timeout for {endpoint.name}",
                    extra={
                        "endpoint": endpoint.name,
                        "event_id": event.event_id,
                        "attempt": attempt + 1,
                    },
                )
            except (OSError, ConnectionError) as e:
                result.error_message = str(e)
                self._logger.warning(
                    f"Webhook error for {endpoint.name}: {e}",
                    extra={
                        "endpoint": endpoint.name,
                        "event_id": event.event_id,
                        "attempt": attempt + 1,
                    },
                )

        # All retries exhausted
        result.status = WebhookStatus.FAILED
        self._logger.error(
            f"Webhook delivery failed to {endpoint.name} after {result.attempts} attempts",
            extra={
                "endpoint": endpoint.name,
                "event_id": event.event_id,
                "error": result.error_message,
            },
        )

        return result

    async def _send_request(
        self,
        url: str,
        payload: bytes,
        headers: dict[str, str],
    ) -> tuple[int, str]:
        """
        Send HTTP request to webhook endpoint.

        Uses httpx for async HTTP requests.

        Args:
            url: Webhook URL
            payload: Request payload
            headers: Request headers

        Returns:
            Tuple of (status_code, response_body)
        """
        try:
            import httpx
        except ImportError:
            # Fallback to aiohttp if httpx not available
            try:
                import aiohttp

                async with (
                    aiohttp.ClientSession() as session,
                    session.post(
                        url,
                        data=payload,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=self._webhook_config.timeout_seconds),
                        ssl=self._webhook_config.verify_ssl,
                    ) as response,
                ):
                    body = await response.text()
                    return response.status, body
            except ImportError:
                raise ImportError("Either httpx or aiohttp must be installed for webhook delivery")

        async with httpx.AsyncClient(
            timeout=self._webhook_config.timeout_seconds,
            verify=self._webhook_config.verify_ssl,
        ) as client:
            response = await client.post(
                url,
                content=payload,
                headers=headers,
            )
            return response.status_code, response.text

    def _compute_signature(
        self,
        payload: bytes,
        secret: str,
        timestamp: str | None = None,
    ) -> str:
        """
        Compute HMAC signature for payload.

        Args:
            payload: Payload bytes
            secret: Secret key
            timestamp: Optional timestamp to include

        Returns:
            Hex-encoded signature
        """
        # Prepare message
        if timestamp:
            message = f"{timestamp}.".encode() + payload
        else:
            message = payload

        # Select algorithm
        if self._webhook_config.signature_algorithm == "sha512":
            algorithm = hashlib.sha512
        else:
            algorithm = hashlib.sha256

        # Compute HMAC
        signature = hmac.new(
            secret.encode("utf-8"),
            message,
            algorithm,
        ).hexdigest()

        return signature


__all__ = [
    "WebhookConfig",
    "WebhookDeliveryResult",
    "WebhookEndpoint",
    "WebhookEventHandler",
    "WebhookStatus",
]
