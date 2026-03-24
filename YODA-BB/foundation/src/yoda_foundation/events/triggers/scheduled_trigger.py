"""
Scheduled trigger for running actions on a schedule.

This module provides triggers that execute actions on a time-based schedule
using cron expressions or interval-based scheduling.

Example:
    ```python
    from yoda_foundation.events import ScheduledTrigger, ScheduledTriggerConfig

    # Define trigger configuration
    config = ScheduledTriggerConfig(
        schedule="*/5 * * * *",  # Every 5 minutes
        action_type="agent",
        action_config={
            "agent_name": "health_check",
            "input": {"check_type": "full"},
        },
    )

    # Create and start trigger
    trigger = ScheduledTrigger(config=config)
    await trigger.start(security_context=security_context)

    # Trigger will now run action on schedule
    await trigger.stop()
    ```
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

from yoda_foundation.events.bus.event_bus import Event, EventBus
from yoda_foundation.exceptions import (
    EventTriggerError,
    ValidationError,
)
from yoda_foundation.security import SecurityContext


logger = logging.getLogger(__name__)


class ScheduleType(Enum):
    """Type of schedule for trigger."""

    CRON = "cron"
    INTERVAL = "interval"
    ONE_TIME = "one_time"


@dataclass
class ScheduledTriggerConfig:
    """
    Configuration for scheduled triggers.

    Attributes:
        schedule: Schedule expression (cron or interval)
        schedule_type: Type of schedule
        action_type: Type of action (agent, workflow, event)
        action_config: Configuration for the action
        timezone: Timezone for schedule (default UTC)
        max_runs: Maximum number of runs (None = unlimited)
        max_missed_runs: Maximum missed runs before stopping
        enabled: Whether trigger is enabled

    Example:
        ```python
        # Cron-based schedule
        config = ScheduledTriggerConfig(
            schedule="0 */2 * * *",  # Every 2 hours
            schedule_type=ScheduleType.CRON,
            action_type="agent",
            action_config={"agent_name": "report_generator"},
        )

        # Interval-based schedule
        config = ScheduledTriggerConfig(
            schedule="300",  # Every 300 seconds (5 minutes)
            schedule_type=ScheduleType.INTERVAL,
            action_type="event",
            action_config={
                "event_type": "health.check",
                "payload": {"source": "scheduler"},
            },
        )
        ```
    """

    schedule: str
    schedule_type: ScheduleType = ScheduleType.CRON
    action_type: str = "event"
    action_config: dict[str, Any] = field(default_factory=dict)
    timezone: str = "UTC"
    max_runs: int | None = None
    max_missed_runs: int = 3
    enabled: bool = True

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if not self.schedule:
            raise ValidationError(
                message="Schedule is required",
                field_name="schedule",
            )

        if self.action_type not in ["agent", "workflow", "event"]:
            raise ValidationError(
                message=f"Invalid action_type: {self.action_type}",
                field_name="action_type",
            )

        if self.max_runs is not None and self.max_runs <= 0:
            raise ValidationError(
                message=f"max_runs must be positive, got {self.max_runs}",
                field_name="max_runs",
            )


class ScheduledTrigger:
    """
    Trigger that executes actions on a schedule.

    Runs actions (agents, workflows, or events) based on cron expressions
    or interval schedules.

    Attributes:
        config: Trigger configuration
        _task: Background task running the scheduler
        _run_count: Number of times action has been executed
        _missed_runs: Number of consecutive missed runs
        _last_run: Last successful run timestamp
        _next_run: Next scheduled run timestamp

    Example:
        ```python
        # Create scheduled trigger
        trigger = ScheduledTrigger(
            config=ScheduledTriggerConfig(
                schedule="0 9 * * 1-5",  # 9 AM weekdays
                action_type="workflow",
                action_config={
                    "workflow_id": "daily_report",
                },
            ),
        )

        # Start scheduler
        await trigger.start(
            security_context=context,
            event_bus=bus,
        )

        # Check status
        status = trigger.get_status()
        print(f"Next run: {status['next_run']}")

        # Stop scheduler
        await trigger.stop()
        ```

    Raises:
        EventTriggerError: If trigger execution fails
        ValidationError: If configuration is invalid
    """

    def __init__(self, config: ScheduledTriggerConfig) -> None:
        """
        Initialize scheduled trigger.

        Args:
            config: Trigger configuration

        Raises:
            ValidationError: If configuration is invalid
        """
        self.config = config
        self._task: asyncio.Task | None = None
        self._run_count = 0
        self._missed_runs = 0
        self._last_run: datetime | None = None
        self._next_run: datetime | None = None
        self._running = False
        self._event_bus: EventBus | None = None
        self._security_context: SecurityContext | None = None

    async def start(
        self,
        security_context: SecurityContext,
        event_bus: EventBus | None = None,
    ) -> None:
        """
        Start the scheduled trigger.

        Begins the scheduler loop that executes actions on schedule.

        Args:
            security_context: Security context for action execution
            event_bus: Event bus for publishing events

        Raises:
            EventTriggerError: If start fails

        Example:
            ```python
            await trigger.start(
                security_context=context,
                event_bus=bus,
            )
            ```
        """
        if self._running:
            logger.warning("Scheduled trigger already running")
            return

        try:
            self._event_bus = event_bus
            self._security_context = security_context
            self._running = True

            # Calculate next run
            self._next_run = self._calculate_next_run()

            # Start scheduler task
            self._task = asyncio.create_task(self._scheduler_loop())

            logger.info(
                f"Scheduled trigger started with schedule: {self.config.schedule}",
                extra={
                    "schedule": self.config.schedule,
                    "schedule_type": self.config.schedule_type.value,
                    "action_type": self.config.action_type,
                    "next_run": self._next_run.isoformat() if self._next_run else None,
                },
            )

        except (ValueError, TypeError, OSError) as e:
            self._running = False
            raise EventTriggerError(
                message=f"Failed to start scheduled trigger: {e}",
                trigger_name="scheduled_trigger",
                target_type=self.config.action_type,
                cause=e,
            )

    async def stop(self) -> None:
        """
        Stop the scheduled trigger.

        Cancels the scheduler loop and waits for completion.

        Example:
            ```python
            await trigger.stop()
            ```
        """
        if not self._running:
            return

        self._running = False

        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.info(
            f"Scheduled trigger stopped after {self._run_count} runs",
            extra={
                "run_count": self._run_count,
                "missed_runs": self._missed_runs,
            },
        )

    async def _scheduler_loop(self) -> None:
        """
        Main scheduler loop.

        Continuously checks for scheduled runs and executes actions.
        """
        while self._running:
            try:
                # Check if we should run now
                now = datetime.now(UTC)

                if self._next_run and now >= self._next_run:
                    # Execute action
                    try:
                        await self._execute_action()
                        self._run_count += 1
                        self._last_run = now
                        self._missed_runs = 0

                        # Check max runs
                        if self.config.max_runs and self._run_count >= self.config.max_runs:
                            logger.info(
                                f"Scheduled trigger reached max runs: {self.config.max_runs}"
                            )
                            break

                    except (EventTriggerError, ValueError, TypeError) as e:
                        self._missed_runs += 1
                        logger.error(
                            f"Scheduled action failed (missed runs: {self._missed_runs}): {e}",
                            exc_info=True,
                        )

                        # Check max missed runs
                        if self._missed_runs >= self.config.max_missed_runs:
                            logger.error(
                                f"Scheduled trigger stopping after {self._missed_runs} missed runs"
                            )
                            break

                    # Calculate next run
                    self._next_run = self._calculate_next_run()

                    # Check for one-time schedule
                    if self.config.schedule_type == ScheduleType.ONE_TIME:
                        logger.info("One-time schedule completed")
                        break

                # Sleep until next check (check every second)
                await asyncio.sleep(1)

            except asyncio.CancelledError:
                logger.info("Scheduler loop cancelled")
                break
            except (EventTriggerError, ValueError, TypeError, OSError) as e:
                logger.error(f"Scheduler loop error: {e}", exc_info=True)
                await asyncio.sleep(5)  # Wait before retrying

        self._running = False

    async def _execute_action(self) -> None:
        """
        Execute the configured action.

        Raises:
            EventTriggerError: If action execution fails
        """
        action_type = self.config.action_type
        action_config = self.config.action_config

        logger.info(
            f"Executing scheduled action: {action_type}",
            extra={
                "action_type": action_type,
                "run_count": self._run_count + 1,
            },
        )

        try:
            if action_type == "event":
                await self._execute_event_action(action_config)
            elif action_type == "agent":
                await self._execute_agent_action(action_config)
            elif action_type == "workflow":
                await self._execute_workflow_action(action_config)
            else:
                raise EventTriggerError(
                    message=f"Unknown action type: {action_type}",
                    trigger_name="scheduled_trigger",
                    target_type=action_type,
                )

        except (ValueError, TypeError, OSError, ConnectionError) as e:
            raise EventTriggerError(
                message=f"Scheduled action failed: {e}",
                trigger_name="scheduled_trigger",
                target_type=action_type,
                retryable=True,
                cause=e,
            )

    async def _execute_event_action(self, config: dict[str, Any]) -> None:
        """
        Execute event action by publishing to event bus.

        Args:
            config: Event configuration

        Raises:
            EventTriggerError: If event bus not configured
        """
        if not self._event_bus or not self._security_context:
            raise EventTriggerError(
                message="Event bus and security context required for event actions",
                trigger_name="scheduled_trigger",
                target_type="event",
            )

        event = Event(
            event_type=config.get("event_type", "scheduler.triggered"),
            payload=config.get("payload", {}),
            metadata={
                "scheduled": True,
                "schedule": self.config.schedule,
                "run_count": self._run_count + 1,
            },
            source="scheduled_trigger",
        )

        await self._event_bus.publish(event, self._security_context)

    async def _execute_agent_action(self, config: dict[str, Any]) -> None:
        """
        Execute agent action.

        Args:
            config: Agent configuration

        Note:
            This is a placeholder. When agent execution is available,
            this should be updated to use the actual agent runner.
        """
        logger.warning(
            "Agent execution from scheduled trigger not yet implemented. "
            "This will be updated when agent execution is available."
        )

        # TODO: Integrate with agent execution
        # agent_runner = get_agent_runner()
        # await agent_runner.run_agent(
        #     agent_name=config["agent_name"],
        #     input=config.get("input", {}),
        #     security_context=self._security_context,
        # )

    async def _execute_workflow_action(self, config: dict[str, Any]) -> None:
        """
        Execute workflow action.

        Args:
            config: Workflow configuration

        Note:
            This is a placeholder. When workflow execution is available,
            this should be updated to use the actual workflow engine.
        """
        logger.warning(
            "Workflow execution from scheduled trigger not yet implemented. "
            "This will be updated when workflow execution is available."
        )

        # TODO: Integrate with workflow execution
        # workflow_engine = get_workflow_engine()
        # await workflow_engine.execute(
        #     workflow_id=config["workflow_id"],
        #     input_data=config.get("input", {}),
        #     security_context=self._security_context,
        # )

    def _calculate_next_run(self) -> datetime | None:
        """
        Calculate next scheduled run time.

        Returns:
            Next run datetime or None if no more runs

        Raises:
            EventTriggerError: If schedule parsing fails
        """
        now = datetime.now(UTC)

        try:
            if self.config.schedule_type == ScheduleType.INTERVAL:
                # Interval-based schedule (seconds)
                interval_seconds = float(self.config.schedule)
                if self._last_run:
                    next_run = self._last_run + timedelta(seconds=interval_seconds)
                else:
                    next_run = now + timedelta(seconds=interval_seconds)
                return next_run

            elif self.config.schedule_type == ScheduleType.ONE_TIME:
                # One-time schedule (ISO datetime or relative)
                if self._last_run:
                    return None  # Already ran
                try:
                    # Try parsing as ISO datetime
                    return datetime.fromisoformat(self.config.schedule)
                except ValueError:
                    # Try parsing as relative seconds
                    delay_seconds = float(self.config.schedule)
                    return now + timedelta(seconds=delay_seconds)

            elif self.config.schedule_type == ScheduleType.CRON:
                # Cron-based schedule
                try:
                    from croniter import croniter

                    cron = croniter(self.config.schedule, now)
                    return cron.get_next(datetime)
                except ImportError:
                    logger.error(
                        "croniter package not available. Install with: pip install croniter"
                    )
                    raise EventTriggerError(
                        message="croniter package required for cron schedules",
                        trigger_name="scheduled_trigger",
                        target_type=self.config.action_type,
                        suggestions=[
                            "Install croniter: pip install croniter",
                            "Use interval schedule type instead",
                        ],
                    )

            else:
                raise EventTriggerError(
                    message=f"Unknown schedule type: {self.config.schedule_type}",
                    trigger_name="scheduled_trigger",
                    target_type=self.config.action_type,
                )

        except (ValueError, TypeError, ImportError) as e:
            raise EventTriggerError(
                message=f"Failed to calculate next run: {e}",
                trigger_name="scheduled_trigger",
                target_type=self.config.action_type,
                cause=e,
            )

    def get_status(self) -> dict[str, Any]:
        """
        Get current status of scheduled trigger.

        Returns:
            Dictionary with trigger status

        Example:
            ```python
            status = trigger.get_status()
            print(f"Running: {status['running']}")
            print(f"Next run: {status['next_run']}")
            ```
        """
        return {
            "running": self._running,
            "enabled": self.config.enabled,
            "schedule": self.config.schedule,
            "schedule_type": self.config.schedule_type.value,
            "action_type": self.config.action_type,
            "run_count": self._run_count,
            "missed_runs": self._missed_runs,
            "last_run": self._last_run.isoformat() if self._last_run else None,
            "next_run": self._next_run.isoformat() if self._next_run else None,
            "max_runs": self.config.max_runs,
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
                "schedule": self.config.schedule,
                "schedule_type": self.config.schedule_type.value,
                "action_type": self.config.action_type,
                "action_config": self.config.action_config,
                "timezone": self.config.timezone,
                "max_runs": self.config.max_runs,
                "max_missed_runs": self.config.max_missed_runs,
                "enabled": self.config.enabled,
            },
            "status": self.get_status(),
        }

    async def __aenter__(self) -> ScheduledTrigger:
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.stop()

    def __str__(self) -> str:
        """String representation."""
        return (
            f"ScheduledTrigger("
            f"schedule={self.config.schedule}, "
            f"type={self.config.schedule_type.value}, "
            f"action={self.config.action_type})"
        )

    def __repr__(self) -> str:
        """Detailed representation."""
        return (
            f"ScheduledTrigger("
            f"schedule={self.config.schedule!r}, "
            f"schedule_type={self.config.schedule_type!r}, "
            f"action_type={self.config.action_type!r}, "
            f"running={self._running})"
        )
