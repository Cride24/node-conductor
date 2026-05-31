from pydantic import BaseModel, Field

from nodeconductor.schemas.events.common import Event


class EventsListResponse(BaseModel):
    total: int = Field(..., ge=0)
    events: list[Event]
