from fastapi import APIRouter, Query

from nodeconductor.schemas.events.read import EventsListResponse
from nodeconductor.services.events import list_events


router = APIRouter()


@router.get("/api/v1/events", response_model=EventsListResponse)
def list_events_endpoint(
    service_id: int | None = None,
    job_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> EventsListResponse:
    return list_events(service_id, job_id, limit)
