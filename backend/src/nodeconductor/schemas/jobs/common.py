from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


JobAction = Literal["start", "stop"]
JobStatus = Literal["pending", "running", "succeeded", "failed", "cancelled"]
RequestedByType = Literal["web", "discord", "llm", "system", "unknown"]


class Job(BaseModel):
    id: int = Field(..., ge=0)
    service_id: int = Field(..., ge=0)
    action: JobAction
    status: JobStatus
    requested_by_type: RequestedByType = "unknown"
    requested_by_id: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None


class ServiceActionResponse(BaseModel):
    job_id: int | None = None
    service_id: int = Field(..., ge=0)
    action: JobAction
    job_status: JobStatus | None = None
    service_status: Literal["on", "off", "error", "starting", "stopping"]
    message: str | None = None
