"""Public and internal contracts for the restricted Agent API."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ManagementPolicy = Literal["discovered", "managed", "protected"]
TargetKind = Literal["compose_project", "standalone_container"]
ResourceAction = Literal["start", "stop"]
ActionStatus = Literal["completed", "rejected", "failed", "indeterminate"]
ComposeClassification = Literal["none", "coherent", "ambiguous"]
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
ComposeState = Literal[
    "stopped",
    "starting",
    "running",
    "degraded",
    "partial",
    "unknown",
]
HealthStatus = Literal["none", "starting", "healthy", "unhealthy", "unknown"]
ProtectionStatus = Literal[
    "not_configured",
    "protected",
    "configured_absent",
    "configured_inconsistent",
]


@dataclass(frozen=True)
class ContainerSnapshot:
    id: str
    name: str
    state: ContainerState
    health_status: HealthStatus
    created_at: datetime
    compose_classification: ComposeClassification = "none"
    compose_project: str | None = None
    compose_service: str | None = None


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
            "resource_inventory_v1",
            "typed_management_policy",
            "standalone_start_stop",
            "compose_start_stop",
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


class ResourceMemberResponse(StrictModel):
    docker_id: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    name: str = Field(..., min_length=1, max_length=255)
    compose_service: str = Field(..., min_length=1, max_length=255)
    state: ContainerState
    health_status: HealthStatus
    is_present: Literal[True] = True
    last_observed_at: datetime


class ResourceResponse(StrictModel):
    classification: Literal["operational", "ambiguous"]
    target_kind: TargetKind | None
    target: str = Field(..., min_length=1, max_length=255)
    display_name: str = Field(..., min_length=1, max_length=255)
    state: ContainerState | ComposeState
    health_status: HealthStatus
    management_policy: ManagementPolicy | None
    operable: bool
    protection_forced: bool = False
    diagnostic_status: Literal["compose_labels_incomplete_or_invalid"] | None = None
    members: list[ResourceMemberResponse] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_classification(self):
        if self.classification == "operational":
            if self.target_kind is None or self.management_policy is None:
                raise ValueError("operational resources require a typed identity")
            if not self.operable or self.diagnostic_status is not None:
                raise ValueError("operational resource flags are inconsistent")
        else:
            if self.target_kind is not None or self.management_policy is not None:
                raise ValueError("ambiguous resources are never operational targets")
            if self.operable or self.protection_forced:
                raise ValueError("ambiguous resources are never operable")
        if self.target_kind != "compose_project" and self.members:
            raise ValueError("only compose projects expose members")
        return self


class ResourceListResponse(StrictModel):
    items: list[ResourceResponse]
    limit: int
    offset: int
    total: int
    snapshot_id: UUID
    snapshot_observed_at: datetime
    protection_status: ProtectionStatus


class PolicyUpdateRequest(StrictModel):
    operation_id: UUID
    actor: str = Field(..., min_length=1, max_length=100)
    management_policy: ManagementPolicy

    @field_validator("actor")
    @classmethod
    def normalize_actor(cls, value: str) -> str:
        return _normalize_actor(value)


class PolicyUpdateResponse(StrictModel):
    operation_id: UUID
    target_kind: TargetKind
    target: str = Field(..., min_length=1, max_length=255)
    actor: str
    previous_policy: ManagementPolicy
    management_policy: ManagementPolicy
    changed_at: datetime


def _normalize_actor(value: str) -> str:
    normalized = value.strip()
    if not normalized or not all(
        character.isprintable() for character in normalized
    ):
        raise ValueError("actor must contain printable characters")
    return normalized


class ResourceActionRequest(StrictModel):
    operation_id: UUID
    actor: str = Field(..., min_length=1, max_length=100)
    action: ResourceAction

    @field_validator("actor")
    @classmethod
    def normalize_actor(cls, value: str) -> str:
        return _normalize_actor(value)


class ActionResourceState(StrictModel):
    target_kind: TargetKind
    target: str = Field(..., min_length=1, max_length=255)
    state: ContainerState | ComposeState
    health_status: HealthStatus
    management_policy: ManagementPolicy
    is_pilotable: bool


class ResourceActionResponse(StrictModel):
    operation_id: UUID
    actor: str
    action: ResourceAction
    target_kind: TargetKind
    target: str = Field(..., min_length=1, max_length=255)
    status: ActionStatus
    result_code: str = Field(..., min_length=1, max_length=100)
    message: str = Field(..., min_length=1, max_length=255)
    resource: ActionResourceState | None = None
    started_at: datetime
    finished_at: datetime | None = None
