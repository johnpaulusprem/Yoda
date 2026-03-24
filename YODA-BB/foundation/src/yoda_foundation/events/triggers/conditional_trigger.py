"""
Conditional trigger for event-driven actions with complex conditions.

This module provides triggers that execute actions when complex conditions
are met, including event aggregation, pattern matching, and state-based rules.

Example:
    ```python
    from yoda_foundation.events import ConditionalTrigger, ConditionalTriggerConfig

    # Define trigger configuration
    config = ConditionalTriggerConfig(
        event_type_pattern="error.*",
        conditions=[
            {
                "field": "payload.severity",
                "operator": "eq",
                "value": "critical",
            },
            {
                "field": "payload.count",
                "operator": "gt",
                "value": 5,
            },
        ],
        action_type="agent",
        action_config={
            "agent_name": "incident_response",
        },
    )

    # Create and setup trigger
    trigger = ConditionalTrigger(config=config)
    await trigger.setup_trigger(
        event_bus=bus,
        security_context=security_context,
    )
    ```
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

from yoda_foundation.events.bus.event_bus import Event, EventBus
from yoda_foundation.events.handlers.event_handler import EventHandler, HandlerConfig
from yoda_foundation.exceptions import (
    EventTriggerError,
    ValidationError,
)
from yoda_foundation.security import SecurityContext


logger = logging.getLogger(__name__)


class AggregationType(Enum):
    """Type of event aggregation for triggers."""

    NONE = "none"  # No aggregation, trigger on first match
    COUNT = "count"  # Trigger after N matching events
    TIME_WINDOW = "time_window"  # Trigger after N events within time window
    SEQUENCE = "sequence"  # Trigger when events match sequence


class ConditionOperator(Enum):
    """Operators for condition evaluation."""

    EQ = "eq"  # Equal
    NE = "ne"  # Not equal
    GT = "gt"  # Greater than
    GTE = "gte"  # Greater than or equal
    LT = "lt"  # Less than
    LTE = "lte"  # Less than or equal
    IN = "in"  # In list
    NOT_IN = "not_in"  # Not in list
    CONTAINS = "contains"  # Contains value
    MATCHES = "matches"  # Regex match
    EXISTS = "exists"  # Field exists


@dataclass
class Condition:
    """
    Condition for trigger evaluation.

    Attributes:
        field: Field path to evaluate (e.g., "payload.severity")
        operator: Comparison operator
        value: Value to compare against
        negate: Whether to negate the condition

    Example:
        ```python
        condition = Condition(
            field="payload.severity",
            operator=ConditionOperator.EQ,
            value="critical",
        )
        ```
    """

    field: str
    operator: ConditionOperator
    value: Any
    negate: bool = False

    def evaluate(self, event: Event) -> bool:
        """
        Evaluate condition against event.

        Args:
            event: Event to evaluate

        Returns:
            True if condition matches

        Example:
            ```python
            if condition.evaluate(event):
                print("Condition matched!")
            ```
        """
        # Navigate to field
        event_dict = event.to_dict()
        field_value = event_dict

        for part in self.field.split("."):
            if isinstance(field_value, dict) and part in field_value:
                field_value = field_value[part]
            else:
                field_value = None
                break

        # Handle exists operator specially
        if self.operator == ConditionOperator.EXISTS:
            result = field_value is not None
            return not result if self.negate else result

        # If field doesn't exist and not checking exists, condition fails
        if field_value is None:
            return self.negate

        # Evaluate operator
        result = False

        if self.operator == ConditionOperator.EQ:
            result = field_value == self.value
        elif self.operator == ConditionOperator.NE:
            result = field_value != self.value
        elif self.operator == ConditionOperator.GT:
            result = field_value > self.value
        elif self.operator == ConditionOperator.GTE:
            result = field_value >= self.value
        elif self.operator == ConditionOperator.LT:
            result = field_value < self.value
        elif self.operator == ConditionOperator.LTE:
            result = field_value <= self.value
        elif self.operator == ConditionOperator.IN:
            result = (
                field_value in self.value if isinstance(self.value, (list, set, tuple)) else False
            )
        elif self.operator == ConditionOperator.NOT_IN:
            result = (
                field_value not in self.value
                if isinstance(self.value, (list, set, tuple))
                else True
            )
        elif self.operator == ConditionOperator.CONTAINS:
            result = (
                self.value in field_value
                if isinstance(field_value, (list, set, tuple, str))
                else False
            )
        elif self.operator == ConditionOperator.MATCHES:
            import re

            result = bool(re.search(self.value, str(field_value)))

        return not result if self.negate else result


@dataclass
class ConditionalTriggerConfig:
    """
    Configuration for conditional triggers.

    Attributes:
        event_type_pattern: Event type pattern to match
        conditions: List of conditions (all must match by default)
        condition_mode: "all" or "any" for condition evaluation
        aggregation_type: Type of event aggregation
        aggregation_count: Number of events for aggregation
        aggregation_window_seconds: Time window for aggregation
        action_type: Type of action (agent, workflow, event)
        action_config: Configuration for the action
        cooldown_seconds: Cooldown period after trigger
        max_triggers: Maximum number of triggers (None = unlimited)

    Example:
        ```python
        # Simple condition trigger
        config = ConditionalTriggerConfig(
            event_type_pattern="api.error",
            conditions=[
                Condition(
                    field="payload.status_code",
                    operator=ConditionOperator.EQ,
                    value=500,
                )
            ],
            action_type="event",
            action_config={
                "event_type": "alert.api_error",
            },
        )

        # Aggregation trigger (trigger after 10 errors in 5 minutes)
        config = ConditionalTriggerConfig(
            event_type_pattern="error.*",
            conditions=[
                Condition(
                    field="payload.severity",
                    operator=ConditionOperator.EQ,
                    value="high",
                )
            ],
            aggregation_type=AggregationType.TIME_WINDOW,
            aggregation_count=10,
            aggregation_window_seconds=300,
            action_type="agent",
            action_config={
                "agent_name": "incident_handler",
            },
        )
        ```
    """

    event_type_pattern: str
    conditions: list[Condition] = field(default_factory=list)
    condition_mode: str = "all"
    aggregation_type: AggregationType = AggregationType.NONE
    aggregation_count: int = 1
    aggregation_window_seconds: float = 60.0
    action_type: str = "event"
    action_config: dict[str, Any] = field(default_factory=dict)
    cooldown_seconds: float = 0.0
    max_triggers: int | None = None

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if not self.event_type_pattern:
            raise ValidationError(
                message="Event type pattern is required",
                field_name="event_type_pattern",
            )

        if self.condition_mode not in ["all", "any"]:
            raise ValidationError(
                message=f"Invalid condition_mode: {self.condition_mode}",
                field_name="condition_mode",
            )

        if self.action_type not in ["agent", "workflow", "event"]:
            raise ValidationError(
                message=f"Invalid action_type: {self.action_type}",
                field_name="action_type",
            )

        if self.aggregation_count <= 0:
            raise ValidationError(
                message=f"aggregation_count must be positive, got {self.aggregation_count}",
                field_name="aggregation_count",
            )


class ConditionalTrigger(EventHandler):
    """
    Trigger that executes actions when complex conditions are met.

    Supports condition evaluation, event aggregation, and cooldown periods.

    Attributes:
        name: Trigger name
        config: Trigger configuration
        _event_buffer: Buffer for aggregated events
        _trigger_count: Number of times triggered
        _last_trigger: Last trigger timestamp
        _subscription_id: Event bus subscription ID

    Example:
        ```python
        # Create conditional trigger
        trigger = ConditionalTrigger(
            config=ConditionalTriggerConfig(
                event_type_pattern="payment.failed",
                conditions=[
                    Condition(
                        field="payload.amount",
                        operator=ConditionOperator.GT,
                        value=1000,
                    ),
                ],
                action_type="agent",
                action_config={
                    "agent_name": "payment_investigator",
                },
            ),
        )

        # Setup on event bus
        await trigger.setup_trigger(
            event_bus=bus,
            security_context=context,
        )

        # Check status
        status = trigger.get_status()
        print(f"Triggers: {status['trigger_count']}")
        ```

    Raises:
        EventTriggerError: If trigger execution fails
        ValidationError: If configuration is invalid
    """

    name: str = "conditional_trigger"

    def __init__(
        self,
        config: ConditionalTriggerConfig,
        handler_config: HandlerConfig | None = None,
    ) -> None:
        """
        Initialize conditional trigger.

        Args:
            config: Trigger configuration
            handler_config: Handler configuration
        """
        super().__init__(config=handler_config)

        self.config = config
        self._event_buffer: list[tuple[Event, datetime]] = []
        self._trigger_count = 0
        self._last_trigger: datetime | None = None
        self._subscription_id: str | None = None
        self._event_bus: EventBus | None = None
        self._security_context: SecurityContext | None = None

    async def setup_trigger(
        self,
        event_bus: EventBus,
        security_context: SecurityContext,
    ) -> str:
        """
        Setup trigger on event bus.

        Subscribes to events and evaluates conditions on match.

        Args:
            event_bus: Event bus to subscribe to
            security_context: Security context for subscription

        Returns:
            Subscription ID

        Raises:
            EventTriggerError: If setup fails

        Example:
            ```python
            sub_id = await trigger.setup_trigger(
                event_bus=bus,
                security_context=context,
            )
            ```
        """
        try:
            self._event_bus = event_bus
            self._security_context = security_context

            # Subscribe to events
            self._subscription_id = await event_bus.subscribe(
                event_type_pattern=self.config.event_type_pattern,
                handler=lambda event: self.on_event(event, security_context),
                security_context=security_context,
            )

            logger.info(
                f"Conditional trigger setup for {self.config.event_type_pattern}",
                extra={
                    "event_type_pattern": self.config.event_type_pattern,
                    "condition_count": len(self.config.conditions),
                    "aggregation_type": self.config.aggregation_type.value,
                    "subscription_id": self._subscription_id,
                },
            )

            return self._subscription_id

        except (EventTriggerError, ValueError, TypeError) as e:
            raise EventTriggerError(
                message=f"Failed to setup conditional trigger: {e}",
                event_type=self.config.event_type_pattern,
                trigger_name=self.name,
                target_type=self.config.action_type,
                cause=e,
            )

    async def on_event(
        self,
        event: Event,
        security_context: SecurityContext,
    ) -> None:
        """
        Handle event by evaluating conditions.

        Args:
            event: Event to evaluate
            security_context: Security context

        Raises:
            EventTriggerError: If evaluation fails
        """
        try:
            # Check cooldown
            if self._in_cooldown():
                logger.debug(
                    f"Trigger in cooldown, skipping event {event.event_id}",
                    extra={"event_id": event.event_id},
                )
                return

            # Check max triggers
            if self.config.max_triggers and self._trigger_count >= self.config.max_triggers:
                logger.info(f"Trigger reached max triggers: {self.config.max_triggers}")
                return

            # Evaluate conditions
            if not self._evaluate_conditions(event):
                return

            # Handle aggregation
            if self.config.aggregation_type == AggregationType.NONE:
                # No aggregation, trigger immediately
                await self._trigger_action(event, security_context)

            elif self.config.aggregation_type == AggregationType.COUNT:
                # Count-based aggregation
                self._add_to_buffer(event)
                if len(self._event_buffer) >= self.config.aggregation_count:
                    await self._trigger_action(event, security_context)
                    self._clear_buffer()

            elif self.config.aggregation_type == AggregationType.TIME_WINDOW:
                # Time window aggregation
                self._add_to_buffer(event)
                self._clean_buffer()
                if len(self._event_buffer) >= self.config.aggregation_count:
                    await self._trigger_action(event, security_context)
                    self._clear_buffer()

            elif self.config.aggregation_type == AggregationType.SEQUENCE:
                # Sequence-based aggregation
                # TODO: Implement sequence matching
                logger.warning("Sequence aggregation not yet implemented")

        except (EventTriggerError, ValueError, TypeError, KeyError) as e:
            logger.error(
                f"Conditional trigger error for event {event.event_id}: {e}",
                exc_info=True,
            )
            raise

    def _evaluate_conditions(self, event: Event) -> bool:
        """
        Evaluate all conditions against event.

        Args:
            event: Event to evaluate

        Returns:
            True if conditions match
        """
        if not self.config.conditions:
            return True

        results = [condition.evaluate(event) for condition in self.config.conditions]

        if self.config.condition_mode == "all":
            return all(results)
        else:  # "any"
            return any(results)

    async def _trigger_action(
        self,
        event: Event,
        security_context: SecurityContext,
    ) -> None:
        """
        Execute the configured action.

        Args:
            event: Triggering event
            security_context: Security context

        Raises:
            EventTriggerError: If action execution fails
        """
        action_type = self.config.action_type
        action_config = self.config.action_config

        logger.info(
            f"Conditional trigger firing: {action_type}",
            extra={
                "action_type": action_type,
                "trigger_count": self._trigger_count + 1,
                "event_type": event.event_type,
                "event_id": event.event_id,
            },
        )

        try:
            if action_type == "event":
                await self._execute_event_action(event, action_config)
            elif action_type == "agent":
                await self._execute_agent_action(event, action_config)
            elif action_type == "workflow":
                await self._execute_workflow_action(event, action_config)

            # Update state
            self._trigger_count += 1
            self._last_trigger = datetime.now(UTC)

        except (EventTriggerError, ValueError, TypeError, OSError) as e:
            raise EventTriggerError(
                message=f"Conditional trigger action failed: {e}",
                event_type=event.event_type,
                event_id=event.event_id,
                trigger_name=self.name,
                target_type=action_type,
                retryable=True,
                cause=e,
            )

    async def _execute_event_action(
        self,
        triggering_event: Event,
        config: dict[str, Any],
    ) -> None:
        """
        Execute event action by publishing to event bus.

        Args:
            triggering_event: Event that triggered action
            config: Event configuration

        Raises:
            EventTriggerError: If event bus not configured
        """
        if not self._event_bus or not self._security_context:
            raise EventTriggerError(
                message="Event bus and security context required for event actions",
                trigger_name=self.name,
                target_type="event",
            )

        event = Event(
            event_type=config.get("event_type", "conditional.triggered"),
            payload=config.get("payload", {}),
            metadata={
                "conditional_trigger": True,
                "triggering_event_id": triggering_event.event_id,
                "triggering_event_type": triggering_event.event_type,
                "trigger_count": self._trigger_count + 1,
                "buffer_size": len(self._event_buffer),
            },
            source="conditional_trigger",
            correlation_id=triggering_event.correlation_id,
        )

        await self._event_bus.publish(event, self._security_context)

    async def _execute_agent_action(
        self,
        triggering_event: Event,
        config: dict[str, Any],
    ) -> None:
        """
        Execute agent action.

        Args:
            triggering_event: Event that triggered action
            config: Agent configuration

        Note:
            Placeholder for agent execution integration.
        """
        logger.warning("Agent execution from conditional trigger not yet implemented")

    async def _execute_workflow_action(
        self,
        triggering_event: Event,
        config: dict[str, Any],
    ) -> None:
        """
        Execute workflow action.

        Args:
            triggering_event: Event that triggered action
            config: Workflow configuration

        Note:
            Placeholder for workflow execution integration.
        """
        logger.warning("Workflow execution from conditional trigger not yet implemented")

    def _add_to_buffer(self, event: Event) -> None:
        """Add event to buffer with timestamp."""
        self._event_buffer.append((event, datetime.now(UTC)))

    def _clean_buffer(self) -> None:
        """Remove events outside the time window."""
        now = datetime.now(UTC)
        window = timedelta(seconds=self.config.aggregation_window_seconds)
        self._event_buffer = [(event, ts) for event, ts in self._event_buffer if now - ts <= window]

    def _clear_buffer(self) -> None:
        """Clear the event buffer."""
        self._event_buffer.clear()

    def _in_cooldown(self) -> bool:
        """Check if trigger is in cooldown period."""
        if self.config.cooldown_seconds <= 0:
            return False

        if self._last_trigger is None:
            return False

        elapsed = (datetime.now(UTC) - self._last_trigger).total_seconds()
        return elapsed < self.config.cooldown_seconds

    async def handle(
        self,
        event: Event,
        security_context: SecurityContext,
    ) -> None:
        """
        Handle event (required by EventHandler).

        Args:
            event: Event to handle
            security_context: Security context
        """
        await self.on_event(event, security_context)

    async def can_handle(self, event: Event) -> bool:
        """
        Check if trigger can handle event.

        Args:
            event: Event to check

        Returns:
            True if event matches pattern
        """
        return event.matches_pattern(self.config.event_type_pattern)

    def get_status(self) -> dict[str, Any]:
        """
        Get current status of conditional trigger.

        Returns:
            Dictionary with trigger status

        Example:
            ```python
            status = trigger.get_status()
            print(f"Triggers: {status['trigger_count']}")
            print(f"Buffer size: {status['buffer_size']}")
            ```
        """
        return {
            "event_type_pattern": self.config.event_type_pattern,
            "condition_count": len(self.config.conditions),
            "condition_mode": self.config.condition_mode,
            "aggregation_type": self.config.aggregation_type.value,
            "aggregation_count": self.config.aggregation_count,
            "trigger_count": self._trigger_count,
            "buffer_size": len(self._event_buffer),
            "in_cooldown": self._in_cooldown(),
            "last_trigger": self._last_trigger.isoformat() if self._last_trigger else None,
            "max_triggers": self.config.max_triggers,
            "subscription_id": self._subscription_id,
        }

    def to_dict(self) -> dict[str, Any]:
        """
        Convert trigger to dictionary for serialization.

        Returns:
            Dictionary representation

        Example:
            ```python
            trigger_dict = trigger.to_dict()
            await storage.save("trigger", trigger_dict)
            ```
        """
        return {
            "config": {
                "event_type_pattern": self.config.event_type_pattern,
                "conditions": [
                    {
                        "field": c.field,
                        "operator": c.operator.value,
                        "value": c.value,
                        "negate": c.negate,
                    }
                    for c in self.config.conditions
                ],
                "condition_mode": self.config.condition_mode,
                "aggregation_type": self.config.aggregation_type.value,
                "aggregation_count": self.config.aggregation_count,
                "aggregation_window_seconds": self.config.aggregation_window_seconds,
                "action_type": self.config.action_type,
                "action_config": self.config.action_config,
                "cooldown_seconds": self.config.cooldown_seconds,
                "max_triggers": self.config.max_triggers,
            },
            "status": self.get_status(),
        }

    def __str__(self) -> str:
        """String representation."""
        return (
            f"ConditionalTrigger("
            f"pattern={self.config.event_type_pattern}, "
            f"conditions={len(self.config.conditions)}, "
            f"action={self.config.action_type})"
        )

    def __repr__(self) -> str:
        """Detailed representation."""
        return (
            f"ConditionalTrigger("
            f"event_type_pattern={self.config.event_type_pattern!r}, "
            f"conditions={self.config.conditions!r}, "
            f"action_type={self.config.action_type!r})"
        )
