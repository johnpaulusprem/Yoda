"""
Event triggers for the Agentic AI Component Library.

Provides triggers for starting agents and workflows in response to events,
scheduled execution, and conditional event processing.

Example:
    ```python
    from yoda_foundation.events.triggers import (
        AgentTrigger,
        TriggerConfig,
        WorkflowTrigger,
        WorkflowTriggerConfig,
        ScheduledTrigger,
        ScheduledTriggerConfig,
        ScheduleType,
        ConditionalTrigger,
        ConditionalTriggerConfig,
        Condition,
        ConditionOperator,
    )

    # Setup agent trigger
    agent_trigger = AgentTrigger(
        agent_factory=factory,
        config=TriggerConfig(
            agent_name="processor",
            input_mapping={"data": "payload.data"},
        ),
    )

    await agent_trigger.setup_trigger(
        event_type="data.received",
        event_bus=bus,
        security_context=context,
    )

    # Setup workflow trigger
    workflow_trigger = WorkflowTrigger(
        config=WorkflowTriggerConfig(
            workflow_id="approval",
            input_mapping={"request": "payload.request"},
        ),
    )

    await workflow_trigger.setup_trigger(
        event_type="approval.requested",
        event_bus=bus,
        security_context=context,
    )

    # Setup scheduled trigger
    scheduled_trigger = ScheduledTrigger(
        config=ScheduledTriggerConfig(
            schedule="0 9 * * *",  # Daily at 9 AM
            schedule_type=ScheduleType.CRON,
            action_type="agent",
            action_config={"agent_name": "daily_report"},
        ),
    )

    await scheduled_trigger.start(
        event_bus=bus,
        security_context=context,
    )

    # Setup conditional trigger
    conditional_trigger = ConditionalTrigger(
        config=ConditionalTriggerConfig(
            event_type_pattern="error.*",
            conditions=[
                Condition(
                    field="payload.severity",
                    operator=ConditionOperator.EQ,
                    value="critical",
                ),
            ],
            action_type="agent",
            action_config={"agent_name": "incident_handler"},
        ),
    )

    await conditional_trigger.setup_trigger(
        event_bus=bus,
        security_context=context,
    )
    ```
"""

from yoda_foundation.events.triggers.conditional_trigger import (
    AggregationType,
    Condition,
    ConditionalTrigger,
    ConditionalTriggerConfig,
    ConditionOperator,
)
from yoda_foundation.events.triggers.scheduled_trigger import (
    ScheduledTrigger,
    ScheduledTriggerConfig,
    ScheduleType,
)
from yoda_foundation.events.triggers.workflow_trigger import (
    WorkflowTrigger,
    WorkflowTriggerConfig,
)


__all__ = [
    # Workflow trigger
    "WorkflowTrigger",
    "WorkflowTriggerConfig",
    # Scheduled trigger
    "ScheduledTrigger",
    "ScheduledTriggerConfig",
    "ScheduleType",
    # Conditional trigger
    "ConditionalTrigger",
    "ConditionalTriggerConfig",
    "Condition",
    "ConditionOperator",
    "AggregationType",
]
