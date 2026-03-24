"""
Workflow trigger for starting workflows from events.

This module provides triggers that automatically start workflows
in response to events.

Example:
    ```python
    from yoda_foundation.events import WorkflowTrigger, WorkflowTriggerConfig

    # Define trigger configuration
    config = WorkflowTriggerConfig(
        workflow_id="document_processing",
        input_mapping={
            "document_id": "payload.document_id",
            "user_id": "payload.user_id",
        },
    )

    # Create and setup trigger
    trigger = WorkflowTrigger(config=config)

    await trigger.setup_trigger(
        event_type="document.uploaded",
        event_bus=bus,
        security_context=security_context,
    )

    # Trigger will now automatically start workflow on events
    ```
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from yoda_foundation.events.bus.event_bus import Event, EventBus
from yoda_foundation.events.handlers.event_handler import EventHandler, HandlerConfig
from yoda_foundation.exceptions import (
    EventTriggerError,
)
from yoda_foundation.security import SecurityContext


logger = logging.getLogger(__name__)


@dataclass
class WorkflowTriggerConfig:
    """
    Configuration for workflow triggers.

    Attributes:
        workflow_id: ID of workflow to execute
        workflow_version: Specific version to use (None = latest)
        input_mapping: Map event fields to workflow input
        timeout_seconds: Timeout for workflow execution
        async_execution: Whether to run workflow asynchronously
        propagate_correlation_id: Whether to use event correlation_id
        max_concurrent: Maximum concurrent workflow runs

    Example:
        ```python
        config = WorkflowTriggerConfig(
            workflow_id="approval_workflow",
            input_mapping={
                "request_id": "payload.request_id",
                "requestor": "payload.user_id",
            },
            timeout_seconds=3600.0,
            async_execution=True,
        )
        ```
    """

    workflow_id: str
    workflow_version: str | None = None
    input_mapping: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = 3600.0
    async_execution: bool = True
    propagate_correlation_id: bool = True
    max_concurrent: int = 10


class WorkflowTrigger(EventHandler):
    """
    Trigger that starts workflows in response to events.

    Automatically initiates workflows when matching events
    are received on the event bus.

    Attributes:
        name: Trigger name
        config: Trigger configuration
        _trigger_semaphore: Semaphore for concurrency control
        _active_workflows: Currently running workflows

    Example:
        ```python
        # Create trigger
        trigger = WorkflowTrigger(
            config=WorkflowTriggerConfig(
                workflow_id="onboarding",
                input_mapping={"user_id": "payload.user_id"},
            ),
        )

        # Setup on event bus
        await trigger.setup_trigger(
            event_type="user.created",
            event_bus=bus,
            security_context=context,
        )

        # Events will now trigger workflow automatically
        ```

    Raises:
        EventTriggerError: If trigger activation fails
    """

    name: str = "workflow_trigger"

    def __init__(
        self,
        config: WorkflowTriggerConfig | None = None,
        handler_config: HandlerConfig | None = None,
    ) -> None:
        """
        Initialize workflow trigger.

        Args:
            config: Trigger configuration
            handler_config: Handler configuration
        """
        super().__init__(config=handler_config)

        self.config = config or WorkflowTriggerConfig(workflow_id="default_workflow")
        self._trigger_semaphore = asyncio.Semaphore(self.config.max_concurrent)
        self._active_workflows: dict[str, asyncio.Task] = {}

    async def setup_trigger(
        self,
        event_type: str,
        event_bus: EventBus,
        security_context: SecurityContext,
    ) -> str:
        """
        Setup trigger on event bus.

        Subscribes to events and starts workflow on match.

        Args:
            event_type: Event type pattern to trigger on
            event_bus: Event bus to subscribe to
            security_context: Security context for subscription

        Returns:
            Subscription ID

        Raises:
            EventTriggerError: If setup fails

        Example:
            ```python
            sub_id = await trigger.setup_trigger(
                event_type="order.placed",
                event_bus=bus,
                security_context=context,
            )
            ```
        """
        try:
            # Subscribe to events
            subscription_id = await event_bus.subscribe(
                event_type_pattern=event_type,
                handler=lambda event: self.on_event(event, security_context),
                security_context=security_context,
            )

            logger.info(
                f"Workflow trigger setup for {event_type} -> {self.config.workflow_id}",
                extra={
                    "event_type": event_type,
                    "workflow_id": self.config.workflow_id,
                    "subscription_id": subscription_id,
                },
            )

            return subscription_id

        except (EventTriggerError, ValueError, TypeError) as e:
            raise EventTriggerError(
                message=f"Failed to setup workflow trigger: {e}",
                event_type=event_type,
                trigger_name=self.name,
                target_type="workflow",
                cause=e,
            )

    async def on_event(
        self,
        event: Event,
        security_context: SecurityContext,
    ) -> None:
        """
        Handle event by triggering workflow.

        Args:
            event: Event that triggered
            security_context: Security context

        Raises:
            EventTriggerError: If workflow trigger fails
        """
        # Acquire semaphore for concurrency control
        async with self._trigger_semaphore:
            try:
                if self.config.async_execution:
                    # Start workflow asynchronously
                    task = asyncio.create_task(self._trigger_workflow(event, security_context))
                    self._active_workflows[event.event_id] = task

                    # Cleanup completed tasks
                    asyncio.create_task(self._cleanup_workflow(event.event_id))
                else:
                    # Execute workflow synchronously
                    await self._trigger_workflow(event, security_context)

            except (EventTriggerError, ValueError, TypeError) as e:
                logger.error(
                    f"Workflow trigger failed for event {event.event_id}: {e}",
                    exc_info=True,
                )
                raise

    async def _trigger_workflow(
        self,
        event: Event,
        security_context: SecurityContext,
    ) -> None:
        """
        Create and execute workflow.

        Args:
            event: Triggering event
            security_context: Security context

        Raises:
            EventTriggerError: If workflow trigger fails

        Note:
            This is a placeholder implementation. When the workflow module
            is available, this should be updated to use the actual workflow
            execution engine.
        """
        try:
            # Map event to workflow input
            workflow_input = self._map_event_to_input(event)

            # Use event correlation ID if configured
            if self.config.propagate_correlation_id and event.correlation_id:
                security_context.with_correlation_id(
                    event.correlation_id
                )
            else:
                pass

            logger.info(
                f"Starting workflow {self.config.workflow_id} from event {event.event_id}",
                extra={
                    "workflow_id": self.config.workflow_id,
                    "event_type": event.event_type,
                    "event_id": event.event_id,
                    "workflow_input": workflow_input,
                },
            )

            # TODO: Integrate with actual workflow execution engine
            # For now, this is a placeholder that logs the intent
            # When workflow module is available, replace with:
            # workflow_engine = get_workflow_engine()
            # result = await workflow_engine.execute(
            #     workflow_id=self.config.workflow_id,
            #     workflow_version=self.config.workflow_version,
            #     input_data=workflow_input,
            #     security_context=workflow_security_context,
            #     timeout=self.config.timeout_seconds,
            # )

            logger.warning(
                "Workflow execution not yet implemented. "
                "This is a placeholder that will be updated when "
                "the workflow module is available."
            )

            # Simulate workflow execution
            await asyncio.sleep(0.1)

            logger.info(
                f"Workflow {self.config.workflow_id} triggered for event {event.event_id}",
                extra={
                    "workflow_id": self.config.workflow_id,
                    "event_id": event.event_id,
                },
            )

        except TimeoutError as e:
            raise EventTriggerError(
                message=f"Workflow {self.config.workflow_id} timed out",
                event_type=event.event_type,
                event_id=event.event_id,
                trigger_name=self.name,
                target_type="workflow",
                retryable=True,
                cause=e,
            )
        except (ValueError, TypeError, KeyError, OSError) as e:
            raise EventTriggerError(
                message=f"Failed to trigger workflow: {e}",
                event_type=event.event_type,
                event_id=event.event_id,
                trigger_name=self.name,
                target_type="workflow",
                cause=e,
            )

    def _map_event_to_input(self, event: Event) -> dict[str, Any]:
        """
        Map event data to workflow input using configured mapping.

        Args:
            event: Event to map

        Returns:
            Mapped input data

        Example:
            Mapping: {"user_id": "payload.user_id"}
            Event: {payload: {user_id: "123"}}
            Result: {"user_id": "123"}
        """
        input_data = {}
        event_dict = event.to_dict()

        for target_field, source_path in self.config.input_mapping.items():
            # Navigate source path (e.g., "payload.user_id")
            value = event_dict
            for part in source_path.split("."):
                if isinstance(value, dict) and part in value:
                    value = value[part]
                else:
                    value = None
                    break

            if value is not None:
                input_data[target_field] = value

        return input_data

    async def _cleanup_workflow(self, event_id: str) -> None:
        """
        Cleanup completed workflow task.

        Args:
            event_id: Event ID associated with workflow
        """
        if event_id in self._active_workflows:
            task = self._active_workflows[event_id]
            try:
                await task
            except (EventTriggerError, ValueError, TypeError) as e:
                logger.error(
                    f"Workflow failed for event {event_id}: {e}",
                    exc_info=True,
                )
            finally:
                del self._active_workflows[event_id]

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
            Always True (filtering done by event bus)
        """
        return True

    async def get_active_workflows(self) -> dict[str, dict[str, Any]]:
        """
        Get information about active workflows.

        Returns:
            Dictionary of event_id -> workflow info

        Example:
            ```python
            active = await trigger.get_active_workflows()
            print(f"Active workflows: {len(active)}")
            ```
        """
        active = {}
        for event_id, task in self._active_workflows.items():
            active[event_id] = {
                "done": task.done(),
                "cancelled": task.cancelled(),
            }
        return active

    async def cancel_workflow(self, event_id: str) -> bool:
        """
        Cancel an active workflow.

        Args:
            event_id: Event ID of workflow to cancel

        Returns:
            True if cancelled, False if not found

        Example:
            ```python
            cancelled = await trigger.cancel_workflow(event_id)
            ```
        """
        if event_id in self._active_workflows:
            task = self._active_workflows[event_id]
            if not task.done():
                task.cancel()
                logger.info(f"Cancelled workflow for event {event_id}")
                return True
        return False

    async def close(self) -> None:
        """
        Cancel all active workflows and cleanup.

        Example:
            ```python
            await trigger.close()
            ```
        """
        logger.info(f"Closing workflow trigger, cancelling {len(self._active_workflows)} workflows")

        # Cancel all active workflows
        for event_id, task in list(self._active_workflows.items()):
            if not task.done():
                task.cancel()

        # Wait for all to complete
        if self._active_workflows:
            await asyncio.gather(
                *self._active_workflows.values(),
                return_exceptions=True,
            )

        self._active_workflows.clear()
        logger.info("Workflow trigger closed")
