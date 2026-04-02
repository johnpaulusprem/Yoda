"""
Handler registry for managing event handlers.

This module provides a registry for registering, discovering, and
managing event handlers.

Example:
    ```python
    from yoda_foundation.events import HandlerRegistry, EventHandler

    # Create registry
    registry = HandlerRegistry()

    # Register handlers
    registry.register_handler(
        "document.*",
        DocumentHandler(),
        priority=10,
    )

    registry.register_handler(
        "user.*",
        UserHandler(),
        priority=5,
    )

    # Get handlers for event type
    handlers = registry.get_handlers("document.uploaded")
    for handler in handlers:
        if await handler.can_handle(event):
            await handler.handle(event, security_context)
    ```
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from yoda_foundation.events.bus.event_bus import Event
from yoda_foundation.events.handlers.event_handler import EventHandler
from yoda_foundation.exceptions import (
    EventSubscriptionError,
    ValidationError,
)


logger = logging.getLogger(__name__)


@dataclass
class HandlerBinding:
    """
    Binding of handler to event type pattern.

    Represents a registered handler with its configuration.

    Attributes:
        binding_id: Unique binding identifier
        event_type_pattern: Event type pattern to match
        handler: Event handler instance
        priority: Handler priority (higher = earlier execution)
        enabled: Whether binding is active
        created_at: When binding was created
        metadata: Additional binding metadata

    Example:
        ```python
        binding = HandlerBinding(
            binding_id="binding_123",
            event_type_pattern="agent.*",
            handler=agent_handler,
            priority=10,
        )
        ```
    """

    binding_id: str
    event_type_pattern: str
    handler: EventHandler
    priority: int = 0
    enabled: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, any] = field(default_factory=dict)

    def matches_event(self, event: Event) -> bool:
        """
        Check if this binding matches the event.

        Args:
            event: Event to check

        Returns:
            True if binding matches and is enabled
        """
        if not self.enabled:
            return False

        return event.matches_pattern(self.event_type_pattern)


class HandlerRegistry:
    """
    Registry for managing event handlers.

    Provides a centralized registry for registering handlers,
    discovering handlers for events, and managing handler lifecycle.

    Attributes:
        _bindings: Registered handler bindings
        _handlers_by_name: Index of handlers by name

    Example:
        ```python
        registry = HandlerRegistry()

        # Register handlers
        handler_id = registry.register_handler(
            event_type_pattern="document.*",
            handler=DocumentHandler(),
            priority=10,
        )

        # Get handlers for event
        event = Event(event_type="document.uploaded", payload={})
        handlers = registry.get_handlers_for_event(event)

        # Execute handlers
        for handler in handlers:
            if await handler.can_handle(event):
                await handler.handle(event, security_context)

        # Unregister
        registry.unregister_handler(handler_id)
        ```

    Raises:
        EventSubscriptionError: If registration fails
        ValidationError: If handler is invalid
    """

    def __init__(self) -> None:
        """Initialize handler registry."""
        self._bindings: dict[str, HandlerBinding] = {}
        self._handlers_by_name: dict[str, list[str]] = {}
        self._lock = None  # Will be created when needed in async context

    async def _get_lock(self):
        """Get or create async lock."""
        if self._lock is None:
            import asyncio

            self._lock = asyncio.Lock()
        return self._lock

    def register_handler(
        self,
        event_type_pattern: str,
        handler: EventHandler,
        priority: int = 0,
        metadata: dict[str, any] | None = None,
    ) -> str:
        """
        Register an event handler.

        Args:
            event_type_pattern: Pattern to match (supports wildcards)
            handler: Handler instance
            priority: Handler priority (higher = earlier)
            metadata: Additional metadata

        Returns:
            Binding ID for later unregister

        Raises:
            ValidationError: If handler is invalid
            EventSubscriptionError: If registration fails

        Example:
            ```python
            handler_id = registry.register_handler(
                "agent.*",
                AgentEventHandler(),
                priority=10,
                metadata={"team": "agents"},
            )
            ```
        """
        # Validate handler
        if not isinstance(handler, EventHandler):
            raise ValidationError(
                message="Handler must inherit from EventHandler",
                field_name="handler",
            )

        if not event_type_pattern:
            raise ValidationError(
                message="Event type pattern is required",
                field_name="event_type_pattern",
            )

        try:
            # Create binding
            import uuid

            binding_id = str(uuid.uuid4())

            binding = HandlerBinding(
                binding_id=binding_id,
                event_type_pattern=event_type_pattern,
                handler=handler,
                priority=priority,
                metadata=metadata or {},
            )

            # Store binding
            self._bindings[binding_id] = binding

            # Index by handler name
            if handler.name not in self._handlers_by_name:
                self._handlers_by_name[handler.name] = []
            self._handlers_by_name[handler.name].append(binding_id)

            logger.info(
                f"Registered handler {handler.name} for {event_type_pattern}",
                extra={
                    "binding_id": binding_id,
                    "handler_name": handler.name,
                    "event_type_pattern": event_type_pattern,
                    "priority": priority,
                },
            )

            return binding_id

        except (ValueError, TypeError) as e:
            raise EventSubscriptionError(
                message=f"Failed to register handler: {e}",
                event_type=event_type_pattern,
                cause=e,
            )

    def unregister_handler(self, binding_id: str) -> None:
        """
        Unregister a handler binding.

        Args:
            binding_id: ID returned from register_handler()

        Raises:
            EventSubscriptionError: If unregister fails

        Example:
            ```python
            registry.unregister_handler(handler_id)
            ```
        """
        try:
            if binding_id in self._bindings:
                binding = self._bindings[binding_id]

                # Remove from bindings
                del self._bindings[binding_id]

                # Remove from handler index
                handler_name = binding.handler.name
                if handler_name in self._handlers_by_name:
                    self._handlers_by_name[handler_name].remove(binding_id)
                    if not self._handlers_by_name[handler_name]:
                        del self._handlers_by_name[handler_name]

                logger.info(
                    f"Unregistered handler {binding.handler.name}",
                    extra={"binding_id": binding_id},
                )
            else:
                logger.warning(f"Handler binding not found: {binding_id}")

        except (ValueError, KeyError) as e:
            raise EventSubscriptionError(
                message=f"Failed to unregister handler: {e}",
                subscription_id=binding_id,
                cause=e,
            )

    def get_handlers(
        self,
        event_type_pattern: str,
    ) -> list[EventHandler]:
        """
        Get all handlers matching an event type pattern.

        Args:
            event_type_pattern: Event type pattern

        Returns:
            List of matching handlers, sorted by priority

        Example:
            ```python
            # Get all handlers for document events
            handlers = registry.get_handlers("document.*")
            ```
        """
        matching_bindings = []

        for binding in self._bindings.values():
            if binding.enabled:
                # Create a dummy event to test pattern matching
                test_event = Event(
                    event_type=event_type_pattern,
                    payload={},
                )
                if binding.matches_event(test_event):
                    matching_bindings.append(binding)

        # Sort by priority (higher first)
        matching_bindings.sort(key=lambda b: b.priority, reverse=True)

        return [b.handler for b in matching_bindings]

    def get_handlers_for_event(self, event: Event) -> list[EventHandler]:
        """
        Get all handlers that should process an event.

        Args:
            event: Event to match against

        Returns:
            List of matching handlers, sorted by priority

        Example:
            ```python
            event = Event(event_type="document.uploaded", payload={})
            handlers = registry.get_handlers_for_event(event)

            for handler in handlers:
                if await handler.can_handle(event):
                    await handler.handle(event, security_context)
            ```
        """
        matching_bindings = []

        for binding in self._bindings.values():
            if binding.matches_event(event):
                matching_bindings.append(binding)

        # Sort by priority (higher first)
        matching_bindings.sort(key=lambda b: b.priority, reverse=True)

        return [b.handler for b in matching_bindings]

    def get_handler_by_name(self, handler_name: str) -> EventHandler | None:
        """
        Get first handler with the given name.

        Args:
            handler_name: Name of handler to find

        Returns:
            Handler instance or None if not found

        Example:
            ```python
            handler = registry.get_handler_by_name("document_handler")
            if handler:
                await handler.handle(event, security_context)
            ```
        """
        binding_ids = self._handlers_by_name.get(handler_name, [])
        if binding_ids:
            binding = self._bindings.get(binding_ids[0])
            if binding:
                return binding.handler
        return None

    def enable_handler(self, binding_id: str) -> None:
        """
        Enable a handler binding.

        Args:
            binding_id: Binding ID to enable

        Example:
            ```python
            registry.enable_handler(handler_id)
            ```
        """
        if binding_id in self._bindings:
            self._bindings[binding_id].enabled = True
            logger.info(f"Enabled handler: {binding_id}")
        else:
            logger.warning(f"Handler binding not found: {binding_id}")

    def disable_handler(self, binding_id: str) -> None:
        """
        Disable a handler binding.

        Args:
            binding_id: Binding ID to disable

        Example:
            ```python
            registry.disable_handler(handler_id)
            ```
        """
        if binding_id in self._bindings:
            self._bindings[binding_id].enabled = False
            logger.info(f"Disabled handler: {binding_id}")
        else:
            logger.warning(f"Handler binding not found: {binding_id}")

    def list_bindings(self) -> list[HandlerBinding]:
        """
        Get all registered bindings.

        Returns:
            List of all bindings

        Example:
            ```python
            bindings = registry.list_bindings()
            for binding in bindings:
                print(f"{binding.handler.name}: {binding.event_type_pattern}")
            ```
        """
        return list(self._bindings.values())

    def clear(self) -> None:
        """
        Remove all registered handlers.

        Example:
            ```python
            registry.clear()
            ```
        """
        self._bindings.clear()
        self._handlers_by_name.clear()
        logger.info("Cleared all handler registrations")

    def __len__(self) -> int:
        """Get number of registered bindings."""
        return len(self._bindings)

    def __contains__(self, binding_id: str) -> bool:
        """Check if binding ID is registered."""
        return binding_id in self._bindings
