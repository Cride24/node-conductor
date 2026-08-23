"""Contrats du futur worker reel, sans implementation d'agent ou de driver."""

from typing import Literal

from pydantic import BaseModel, Field


ManagementPolicy = Literal["discovered", "managed", "protected"]
AgentTransport = Literal["unix_socket", "https"]
ReadinessCheck = Literal["docker_state", "docker_health", "http", "tcp"]


class AgentConnection(BaseModel):
    """Connexion non secrete permettant de designer un Agent NodeConductor."""

    id: str = Field(..., min_length=1, max_length=100)
    description: str = Field(..., min_length=3, max_length=200)
    transport: AgentTransport
    endpoint: str = Field(..., min_length=1, max_length=500)
    default_management_policy: Literal["discovered"] = "discovered"


class OperationalTarget(BaseModel):
    """Cible canonique; son triplet metier est unique en PostgreSQL."""

    id: int = Field(..., ge=1)
    driver: str = Field(..., min_length=1, max_length=50)
    connection_id: str = Field(..., min_length=1, max_length=100)
    target: str = Field(..., min_length=1, max_length=255)
    management_policy: ManagementPolicy = "discovered"


class ServiceTargetBinding(BaseModel):
    """Association d'un service logique a sa cible operationnelle."""

    service_id: int = Field(..., ge=1)
    service_description: str = Field(..., min_length=3, max_length=200)
    target_id: int = Field(..., ge=1)
    readiness_check: ReadinessCheck = "docker_state"
