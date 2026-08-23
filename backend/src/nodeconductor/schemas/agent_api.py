"""Contrats stricts de l'API interne NodeConductor Agent."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ManagementPolicy = Literal["discovered", "managed", "protected"]
ObservedState = Literal[
    "created",
    "running",
    "paused",
    "restarting",
    "removing",
    "exited",
    "dead",
    "unknown",
]
ObservedHealthStatus = Literal[
    "none",
    "starting",
    "healthy",
    "unhealthy",
    "unknown",
]


class AgentModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentHealth(AgentModel):
    agent_id: str = Field(..., pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
    status: Literal["ready", "degraded"]
    agent_version: str = Field(..., min_length=1, max_length=50)
    engine_status: Literal["available", "engine_unavailable"]


class AgentCapabilities(AgentModel):
    agent_id: str = Field(..., pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
    agent_version: str = Field(..., min_length=1, max_length=50)
    api_version: str = Field(..., min_length=1, max_length=20)
    engine_available: bool
    engine_version: str | None = Field(None, max_length=100)
    docker_api_version: str | None = Field(None, max_length=100)
    capabilities: list[str] = Field(..., max_length=20)


class AgentContainer(AgentModel):
    id: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    name: str = Field(..., min_length=1, max_length=255)
    state: ObservedState
    health_status: ObservedHealthStatus
    created_at: datetime
    management_policy: ManagementPolicy


class AgentContainerPage(AgentModel):
    items: list[AgentContainer] = Field(..., max_length=100)
    limit: int = Field(..., ge=1, le=100)
    offset: int = Field(..., ge=0, le=100_000)
    total: int = Field(..., ge=0, le=100_000)
