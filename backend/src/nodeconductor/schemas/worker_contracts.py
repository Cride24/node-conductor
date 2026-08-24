"""Contrats des connexions, cibles et associations du worker reel."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


ManagementPolicy = Literal["discovered", "managed", "protected"]
TargetKind = Literal["compose_project", "standalone_container"]
AgentTransport = Literal["unix_socket", "https"]
ReadinessCheck = Literal["docker_state", "docker_health", "http", "tcp"]
ObservedState = Literal[
    "created",
    "running",
    "paused",
    "restarting",
    "removing",
    "exited",
    "dead",
    "stopped",
    "starting",
    "degraded",
    "partial",
    "unknown",
]
ObservedHealthStatus = Literal[
    "none",
    "starting",
    "healthy",
    "unhealthy",
    "unknown",
]


class AgentConnection(BaseModel):
    """Connexion non secrete permettant de designer un Agent NodeConductor."""

    id: str = Field(..., min_length=1, max_length=100)
    agent_id: str = Field(
        ...,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$",
    )
    description: str = Field(..., min_length=3, max_length=200)
    transport: AgentTransport
    endpoint: str = Field(..., min_length=1, max_length=500)
    default_management_policy: Literal["discovered"] = "discovered"
    credential_ref: str | None = Field(
        None,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$",
    )


class OperationalTarget(BaseModel):
    """Cible canonique; son quadruplet metier est unique en PostgreSQL."""

    id: int = Field(..., ge=1)
    driver: str = Field(..., min_length=1, max_length=50)
    connection_id: str = Field(..., min_length=1, max_length=100)
    target_kind: TargetKind = "standalone_container"
    target: str = Field(..., min_length=1, max_length=255)
    management_policy: ManagementPolicy = "discovered"
    display_name: str | None = Field(None, min_length=1, max_length=255)
    observed_state: ObservedState | None = None
    observed_health_status: ObservedHealthStatus | None = None
    last_seen_at: datetime | None = None
    is_present: bool = False
    is_pilotable: bool = True
    protection_forced: bool = False


class ServiceTargetBinding(BaseModel):
    """Association d'un service logique a sa cible operationnelle."""

    service_id: int = Field(..., ge=1)
    service_description: str = Field(..., min_length=3, max_length=200)
    target_id: int = Field(..., ge=1)
    readiness_check: ReadinessCheck = "docker_state"
