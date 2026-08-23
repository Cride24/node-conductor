"""Public and internal contracts for the restricted Agent API."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


ManagementPolicy = Literal["discovered", "managed", "protected"]
ContainerState = Literal[
    "created",
    "running",
    "paused",
    "restarting",
    "removing",
    "exited",
    "dead",
    "unknown",
]
HealthStatus = Literal["none", "starting", "healthy", "unhealthy", "unknown"]


@dataclass(frozen=True)
class ContainerSnapshot:
    id: str
    name: str
    state: ContainerState
    health_status: HealthStatus
    created_at: datetime


@dataclass(frozen=True)
class ContainerPage:
    items: list[ContainerSnapshot]
    total: int


@dataclass(frozen=True)
class EngineVersion:
    engine_version: str
    api_version: str


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorDetails(StrictModel):
    code: str
    message: str


class ErrorResponse(StrictModel):
    error: ErrorDetails


class HealthResponse(StrictModel):
    agent_id: str = Field(..., pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
    status: Literal["ready", "degraded"]
    agent_version: str
    engine_status: Literal["available", "engine_unavailable"]


class CapabilitiesResponse(StrictModel):
    agent_id: str = Field(..., pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
    agent_version: str
    api_version: str
    engine_available: bool
    engine_version: str | None
    docker_api_version: str | None
    capabilities: list[
        Literal[
            "health",
            "capabilities",
            "container_list",
            "container_inspect",
            "management_policy",
        ]
    ]


class ContainerResponse(StrictModel):
    id: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    name: str = Field(..., min_length=1, max_length=255)
    state: ContainerState
    health_status: HealthStatus
    created_at: datetime
    management_policy: ManagementPolicy


class ContainerListResponse(StrictModel):
    items: list[ContainerResponse]
    limit: int
    offset: int
    total: int


class PolicyUpdateRequest(StrictModel):
    operation_id: UUID
    actor: str = Field(..., min_length=1, max_length=100)
    management_policy: ManagementPolicy

    @field_validator("actor")
    @classmethod
    def normalize_actor(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or any(ord(character) < 32 for character in normalized):
            raise ValueError("actor must contain printable characters")
        return normalized


class PolicyUpdateResponse(StrictModel):
    operation_id: UUID
    container_id: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    actor: str
    previous_policy: ManagementPolicy
    management_policy: ManagementPolicy
    changed_at: datetime
