from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


JobAction = Literal["start", "stop"]
# Cycle de vie defini dans Docs/Jobs-et-actions.md.
JobStatus = Literal["pending", "running", "succeeded", "failed", "cancelled"]
RequestedByType = Literal["web", "discord", "llm", "system", "unknown"]


class Job(BaseModel):
    """Representation publique d'une demande d'action asynchrone."""

    id: int = Field(..., ge=0)
    service_id: int = Field(..., ge=0)
    action: JobAction
    status: JobStatus
    requested_by_type: RequestedByType = "unknown"
    requested_by_id: str | None = Field(default=None, max_length=100)
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = Field(default=None, max_length=2_000)


class ServiceActionResponse(BaseModel):
    """Reponse commune a start/stop, avec ou sans nouveau job."""

    job_id: int | None = None
    service_id: int = Field(..., ge=0)
    action: JobAction
    job_status: JobStatus | None = None
    service_status: Literal["on", "off", "error", "starting", "stopping"]
    message: str | None = Field(default=None, max_length=500)
