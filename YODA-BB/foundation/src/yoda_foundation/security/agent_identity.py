"""
Agent identity components for the Agentic AI Component Library.

This module provides agent and service account identity management
for non-human actors in the system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class AgentType(Enum):
    """Type of agent."""

    AUTONOMOUS = "autonomous"
    SEMI_AUTONOMOUS = "semi_autonomous"
    SUPERVISED = "supervised"
    TOOL = "tool"


class ServiceAccountType(Enum):
    """Type of service account."""

    INTERNAL = "internal"
    EXTERNAL = "external"
    SYSTEM = "system"


@dataclass
class AgentCredentials:
    """Credentials for an AI agent.

    Attributes:
        agent_id: Unique agent identifier.
        api_key: API key for authentication.
        scopes: Permission scopes granted to the agent.
        expires_at: When the credentials expire.
    """

    agent_id: str
    api_key: str = ""
    scopes: list[str] = field(default_factory=list)
    expires_at: datetime | None = None

    @property
    def is_expired(self) -> bool:
        """Check if credentials have expired."""
        if self.expires_at is None:
            return False
        return datetime.now(UTC) > self.expires_at


@dataclass
class AgentIdentity:
    """Identity for an AI agent in the system.

    Attributes:
        agent_id: Unique agent identifier.
        agent_type: Type of agent.
        name: Human-readable agent name.
        owner_id: User ID of the agent owner.
        credentials: Agent authentication credentials.
        metadata: Additional agent metadata.
        created_at: When the agent was created.
    """

    agent_id: str
    agent_type: AgentType = AgentType.SUPERVISED
    name: str = ""
    owner_id: str = ""
    credentials: AgentCredentials | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class ServiceAccount:
    """Service account for system-level operations.

    Attributes:
        account_id: Unique service account identifier.
        account_type: Type of service account.
        name: Human-readable service name.
        permissions: Granted permissions.
        metadata: Additional metadata.
        created_at: When the account was created.
    """

    account_id: str
    account_type: ServiceAccountType = ServiceAccountType.INTERNAL
    name: str = ""
    permissions: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
