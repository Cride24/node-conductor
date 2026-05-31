from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


EventSeverity = Literal["info", "warning", "error", "debug"]
EventActorType = Literal["web", "discord", "llm", "system", "unknown"]


class Event(BaseModel):
    """Representation publique d'un evenement metier."""

    id: int = Field(..., ge=0)
    event_type: str = Field(..., min_length=1, max_length=80)
    severity: EventSeverity
    message: str = Field(..., min_length=1)
    service_id: int | None = None
    job_id: int | None = None
    actor_type: EventActorType = "unknown"
    actor_id: str | None = None
    created_at: datetime
    details: dict[str, Any] | None = None
