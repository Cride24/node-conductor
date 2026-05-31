from nodeconductor.repositories.events_repository import (
    create_event,
    fetch_events,
)
from nodeconductor.schemas.events.common import Event
from nodeconductor.schemas.events.read import EventsListResponse


def record_event(
    event_type: str,
    severity: str,
    message: str,
    service_id: int | None = None,
    job_id: int | None = None,
    actor_type: str = "unknown",
    actor_id: str | None = None,
    details: dict | None = None,
) -> Event:
    row = create_event(
        event_type,
        severity,
        message,
        service_id,
        job_id,
        actor_type,
        actor_id,
        details,
    )
    return Event(**row)


def list_events(
    service_id: int | None = None,
    job_id: int | None = None,
    limit: int = 50,
) -> EventsListResponse:
    rows = fetch_events(service_id, job_id, limit)
    events = [Event(**row) for row in rows]
    return EventsListResponse(total=len(events), events=events)
