"""
Event router for the Agentic AI Component Library.

This module provides event routing capabilities with filtering,
priority-based routing, and handler selection.

Example:
    ```python
    from yoda_foundation.events.bus.event_router import (
        EventRouter,
        RouteConfig,
        EventFilter,
        FilterOperator,
    )
    from yoda_foundation.events import Event, EventHandler

    # Create router
    router = EventRouter()

    # Define handler
    async def agent_handler(event: Event) -> None:
        print(f"Agent event: {event.event_type}")

    # Add route with filter
    await router.add_route(
        pattern="agent.*",
        handler=agent_handler,
        config=RouteConfig(
            priority=10,
            filters=[
                EventFilter(
                    field="payload.severity",
                    operator=FilterOperator.EQ,
                    value="high",
                ),
            ],
        ),
        security_context=context,
    )

    # Route event
    await router.route(event, security_context)
    ```
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from yoda_foundation.events.bus.event_bus import Event
from yoda_foundation.exceptions import (
    EventError,
    EventHandlerError,
    ValidationError,
)
from yoda_foundation.security import SecurityContext


logger = logging.getLogger(__name__)

# Type alias for route handlers
RouteHandler = Callable[[Event], Awaitable[None]]


class FilterOperator(Enum):
    """
    Operators for event filtering.

    Supported operators for comparing event fields.

    Example:
        ```python
        filter = EventFilter(
            field="payload.status",
            operator=FilterOperator.EQ,
            value="completed",
        )
        ```
    """

    EQ = "eq"  # Equal
    NE = "ne"  # Not equal
    GT = "gt"  # Greater than
    GE = "ge"  # Greater than or equal
    LT = "lt"  # Less than
    LE = "le"  # Less than or equal
    IN = "in"  # In list
    NOT_IN = "not_in"  # Not in list
    CONTAINS = "contains"  # Contains substring or element
    STARTS_WITH = "starts_with"  # Starts with string
    ENDS_WITH = "ends_with"  # Ends with string
    REGEX = "regex"  # Regex match
    EXISTS = "exists"  # Field exists
    NOT_EXISTS = "not_exists"  # Field does not exist


@dataclass
class EventFilter:
    """
    Filter for event routing.

    Used to filter events based on field values.

    Attributes:
        field: Dot-separated path to field (e.g., "payload.status")
        operator: Comparison operator
        value: Value to compare against

    Example:
        ```python
        # Filter by exact match
        filter1 = EventFilter(
            field="event_type",
            operator=FilterOperator.EQ,
            value="agent.completed",
        )

        # Filter by severity level
        filter2 = EventFilter(
            field="metadata.severity",
            operator=FilterOperator.IN,
            value=["high", "critical"],
        )

        # Filter by source prefix
        filter3 = EventFilter(
            field="source",
            operator=FilterOperator.STARTS_WITH,
            value="agent:",
        )
        ```
    """

    field: str
    operator: FilterOperator
    value: Any

    def matches(self, event: Event) -> bool:
        """
        Check if event matches this filter.

        Args:
            event: Event to check

        Returns:
            True if event matches filter

        Example:
            ```python
            if filter.matches(event):
                await handler(event)
            ```
        """
        import re

        # Get field value from event
        field_value = self._get_field_value(event)

        # Handle exists/not_exists first
        if self.operator == FilterOperator.EXISTS:
            return field_value is not None
        if self.operator == FilterOperator.NOT_EXISTS:
            return field_value is None

        # If field doesn't exist, filter doesn't match
        if field_value is None:
            return False

        # Apply operator
        try:
            if self.operator == FilterOperator.EQ:
                return field_value == self.value
            elif self.operator == FilterOperator.NE:
                return field_value != self.value
            elif self.operator == FilterOperator.GT:
                return field_value > self.value
            elif self.operator == FilterOperator.GE:
                return field_value >= self.value
            elif self.operator == FilterOperator.LT:
                return field_value < self.value
            elif self.operator == FilterOperator.LE:
                return field_value <= self.value
            elif self.operator == FilterOperator.IN:
                return field_value in self.value
            elif self.operator == FilterOperator.NOT_IN:
                return field_value not in self.value
            elif self.operator == FilterOperator.CONTAINS:
                if isinstance(field_value, str) or isinstance(field_value, (list, set, tuple)):
                    return self.value in field_value
                return False
            elif self.operator == FilterOperator.STARTS_WITH:
                return isinstance(field_value, str) and field_value.startswith(self.value)
            elif self.operator == FilterOperator.ENDS_WITH:
                return isinstance(field_value, str) and field_value.endswith(self.value)
            elif self.operator == FilterOperator.REGEX:
                return isinstance(field_value, str) and bool(re.match(self.value, field_value))
            else:
                return False
        except (TypeError, ValueError):
            return False

    def _get_field_value(self, event: Event) -> Any:
        """
        Get field value from event using dot notation.

        Args:
            event: Event to extract field from

        Returns:
            Field value or None if not found
        """
        # Convert event to dict for field access
        data = event.to_dict()

        # Navigate field path
        current = data
        for part in self.field.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        return current


@dataclass
class RouteConfig:
    """
    Configuration for an event route.

    Attributes:
        priority: Route priority (higher = earlier execution)
        filters: List of filters that must all match
        max_retries: Maximum retry attempts
        timeout_seconds: Handler execution timeout
        continue_on_error: Continue routing on handler error
        async_execution: Execute handler asynchronously
        enabled: Whether route is enabled

    Example:
        ```python
        config = RouteConfig(
            priority=10,
            filters=[
                EventFilter("event_type", FilterOperator.STARTS_WITH, "agent."),
            ],
            max_retries=3,
            timeout_seconds=30.0,
        )
        ```
    """

    priority: int = 0
    filters: list[EventFilter] = field(default_factory=list)
    max_retries: int = 0
    timeout_seconds: float = 30.0
    continue_on_error: bool = True
    async_execution: bool = False
    enabled: bool = True


@dataclass
class Route:
    """
    Event route definition.

    Represents a registered route with pattern, handler, and config.

    Attributes:
        route_id: Unique route identifier
        pattern: Event type pattern to match
        handler: Async handler function
        config: Route configuration
        created_at: When route was created
        user_id: User who created the route
    """

    route_id: str
    pattern: str
    handler: RouteHandler
    config: RouteConfig
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    user_id: str | None = None

    def matches_event(self, event: Event) -> bool:
        """
        Check if this route matches an event.

        Args:
            event: Event to check

        Returns:
            True if route matches event
        """
        if not self.config.enabled:
            return False

        # Check pattern match
        if not event.matches_pattern(self.pattern):
            return False

        # Check all filters
        for filter in self.config.filters:
            if not filter.matches(event):
                return False

        return True


class EventRouter:
    """
    Event router for routing events to handlers.

    Provides priority-based routing with filtering and error handling.

    Attributes:
        default_timeout: Default handler timeout
        max_concurrent_handlers: Maximum concurrent handler executions

    Example:
        ```python
        # Create router
        router = EventRouter(
            default_timeout=30.0,
            max_concurrent_handlers=100,
        )

        # Add high-priority route for critical events
        await router.add_route(
            pattern="*.error",
            handler=error_handler,
            config=RouteConfig(
                priority=100,
                filters=[
                    EventFilter("severity", FilterOperator.EQ, "critical"),
                ],
            ),
            security_context=context,
        )

        # Add default route for agent events
        await router.add_route(
            pattern="agent.**",
            handler=agent_handler,
            config=RouteConfig(priority=10),
            security_context=context,
        )

        # Route an event
        matched = await router.route(event, security_context)
        print(f"Matched {matched} routes")

        # Remove route
        await router.remove_route(route_id, security_context)
        ```

    Raises:
        EventError: If routing fails
        EventHandlerError: If handler execution fails
    """

    def __init__(
        self,
        default_timeout: float = 30.0,
        max_concurrent_handlers: int = 100,
    ) -> None:
        """
        Initialize event router.

        Args:
            default_timeout: Default handler timeout in seconds
            max_concurrent_handlers: Maximum concurrent handlers
        """
        self.default_timeout = default_timeout
        self.max_concurrent_handlers = max_concurrent_handlers
        self._routes: dict[str, Route] = {}
        self._semaphore = asyncio.Semaphore(max_concurrent_handlers)
        self._logger = logging.getLogger(__name__)

    async def add_route(
        self,
        pattern: str,
        handler: RouteHandler,
        config: RouteConfig | None = None,
        *,
        security_context: SecurityContext,
    ) -> str:
        """
        Add a route to the router.

        Args:
            pattern: Event type pattern (supports wildcards)
            handler: Async handler function
            config: Route configuration
            security_context: Security context for authorization

        Returns:
            Route ID

        Raises:
            ValidationError: If pattern is invalid
            AuthorizationError: If user lacks permission

        Example:
            ```python
            route_id = await router.add_route(
                pattern="agent.*",
                handler=my_handler,
                config=RouteConfig(priority=10),
                security_context=context,
            )
            ```
        """
        security_context.require_permission("event.router.add_route")

        if not pattern:
            raise ValidationError(
                message="Route pattern cannot be empty",
                field_name="pattern",
            )

        route_id = str(uuid.uuid4())
        route = Route(
            route_id=route_id,
            pattern=pattern,
            handler=handler,
            config=config or RouteConfig(),
            user_id=security_context.user_id,
        )

        self._routes[route_id] = route

        self._logger.info(
            f"Added route {route_id[:8]} for pattern '{pattern}'",
            extra={
                "route_id": route_id,
                "pattern": pattern,
                "priority": route.config.priority,
            },
        )

        return route_id

    async def remove_route(
        self,
        route_id: str,
        security_context: SecurityContext,
    ) -> None:
        """
        Remove a route from the router.

        Args:
            route_id: Route ID to remove
            security_context: Security context for authorization

        Raises:
            EventError: If route not found
            AuthorizationError: If user lacks permission

        Example:
            ```python
            await router.remove_route(route_id, security_context)
            ```
        """
        security_context.require_permission("event.router.remove_route")

        if route_id not in self._routes:
            raise EventError(
                message=f"Route {route_id} not found",
                event_type="route.not_found",
            )

        del self._routes[route_id]

        self._logger.info(
            f"Removed route {route_id[:8]}",
            extra={"route_id": route_id},
        )

    async def update_route(
        self,
        route_id: str,
        config: RouteConfig,
        security_context: SecurityContext,
    ) -> None:
        """
        Update route configuration.

        Args:
            route_id: Route ID to update
            config: New route configuration
            security_context: Security context for authorization

        Raises:
            EventError: If route not found
            AuthorizationError: If user lacks permission

        Example:
            ```python
            await router.update_route(
                route_id,
                RouteConfig(priority=20, enabled=False),
                security_context,
            )
            ```
        """
        security_context.require_permission("event.router.update_route")

        if route_id not in self._routes:
            raise EventError(
                message=f"Route {route_id} not found",
                event_type="route.not_found",
            )

        route = self._routes[route_id]
        route.config = config

        self._logger.info(
            f"Updated route {route_id[:8]}",
            extra={
                "route_id": route_id,
                "new_priority": config.priority,
                "enabled": config.enabled,
            },
        )

    async def route(
        self,
        event: Event,
        security_context: SecurityContext,
    ) -> int:
        """
        Route an event to matching handlers.

        Handlers are executed in priority order (highest first).

        Args:
            event: Event to route
            security_context: Security context for authorization

        Returns:
            Number of routes matched

        Raises:
            EventError: If routing fails
            EventHandlerError: If handler fails and continue_on_error is False

        Example:
            ```python
            matched_count = await router.route(event, security_context)
            print(f"Event routed to {matched_count} handlers")
            ```
        """
        security_context.require_permission("event.router.route")

        # Find matching routes
        matching_routes = self._find_matching_routes(event)

        if not matching_routes:
            self._logger.debug(
                f"No routes matched for event {event.event_type}",
                extra={"event_id": event.event_id},
            )
            return 0

        # Sort by priority (descending)
        matching_routes.sort(key=lambda r: r.config.priority, reverse=True)

        # Execute handlers
        tasks: list[asyncio.Task[None]] = []
        errors: list[Exception] = []

        for route in matching_routes:
            if route.config.async_execution:
                # Execute asynchronously
                task = asyncio.create_task(self._execute_handler(event, route, security_context))
                tasks.append(task)
            else:
                # Execute synchronously
                try:
                    await self._execute_handler(event, route, security_context)
                except (EventHandlerError, ValueError, TypeError) as e:
                    errors.append(e)
                    if not route.config.continue_on_error:
                        raise

        # Wait for async handlers
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    errors.append(result)

        if errors:
            self._logger.warning(
                f"Event {event.event_id[:8]} had {len(errors)} handler errors",
                extra={
                    "event_id": event.event_id,
                    "error_count": len(errors),
                },
            )

        return len(matching_routes)

    async def route_all(
        self,
        events: list[Event],
        security_context: SecurityContext,
        parallel: bool = True,
    ) -> dict[str, int]:
        """
        Route multiple events.

        Args:
            events: List of events to route
            security_context: Security context for authorization
            parallel: Execute event routing in parallel

        Returns:
            Dict mapping event_id to matched route count

        Example:
            ```python
            results = await router.route_all(events, security_context)
            for event_id, count in results.items():
                print(f"Event {event_id}: {count} routes")
            ```
        """
        results: dict[str, int] = {}

        if parallel:
            tasks = [self.route(event, security_context) for event in events]
            counts = await asyncio.gather(*tasks, return_exceptions=True)
            for event, count in zip(events, counts):
                if isinstance(count, Exception):
                    results[event.event_id] = 0
                else:
                    results[event.event_id] = count
        else:
            for event in events:
                try:
                    count = await self.route(event, security_context)
                    results[event.event_id] = count
                except (EventError, EventHandlerError):
                    results[event.event_id] = 0

        return results

    def get_routes(self) -> list[Route]:
        """
        Get all registered routes.

        Returns:
            List of routes
        """
        return list(self._routes.values())

    def get_route(self, route_id: str) -> Route | None:
        """
        Get a specific route by ID.

        Args:
            route_id: Route identifier

        Returns:
            Route or None if not found
        """
        return self._routes.get(route_id)

    async def clear_routes(self, security_context: SecurityContext) -> int:
        """
        Remove all routes.

        Args:
            security_context: Security context for authorization

        Returns:
            Number of routes removed

        Example:
            ```python
            count = await router.clear_routes(security_context)
            print(f"Removed {count} routes")
            ```
        """
        security_context.require_permission("event.router.clear_routes")

        count = len(self._routes)
        self._routes.clear()

        self._logger.info(f"Cleared {count} routes")
        return count

    def _find_matching_routes(self, event: Event) -> list[Route]:
        """
        Find routes that match an event.

        Args:
            event: Event to match

        Returns:
            List of matching routes
        """
        matching = []
        for route in self._routes.values():
            if route.matches_event(event):
                matching.append(route)
        return matching

    async def _execute_handler(
        self,
        event: Event,
        route: Route,
        security_context: SecurityContext,
    ) -> None:
        """
        Execute a route handler with retry and timeout.

        Args:
            event: Event to handle
            route: Route with handler
            security_context: Security context

        Raises:
            EventHandlerError: If handler fails
        """
        async with self._semaphore:
            timeout = route.config.timeout_seconds or self.default_timeout
            retries = 0
            last_error: Exception | None = None

            while retries <= route.config.max_retries:
                try:
                    await asyncio.wait_for(
                        route.handler(event),
                        timeout=timeout,
                    )
                    return
                except TimeoutError as e:
                    last_error = e
                    self._logger.warning(
                        f"Handler timeout for route {route.route_id[:8]}",
                        extra={
                            "route_id": route.route_id,
                            "event_id": event.event_id,
                            "retry": retries,
                        },
                    )
                except (ValueError, TypeError, KeyError, OSError) as e:
                    last_error = e
                    self._logger.warning(
                        f"Handler error for route {route.route_id[:8]}: {e}",
                        extra={
                            "route_id": route.route_id,
                            "event_id": event.event_id,
                            "retry": retries,
                        },
                    )

                retries += 1
                if retries <= route.config.max_retries:
                    await asyncio.sleep(0.1 * retries)  # Exponential backoff

            # All retries exhausted
            if last_error:
                raise EventHandlerError(
                    message=f"Handler failed after {retries} attempts: {last_error}",
                    event_type=event.event_type,
                    event_id=event.event_id,
                    handler_name=route.route_id,
                    retry_count=retries,
                    retryable=False,
                    cause=last_error,
                )


__all__ = [
    "EventFilter",
    "EventRouter",
    "FilterOperator",
    "Route",
    "RouteConfig",
    "RouteHandler",
]
