from nodeconductor.repositories.events_repository import (
    create_event,
    fetch_events,
)
from nodeconductor.core.config import settings
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


def record_system_started_event() -> Event:
    """Trace rare au demarrage: utile pour lire le mode de l'instance."""
    return record_event(
        event_type="system.started",
        severity="info",
        message="NodeConductor API started",
        actor_type="system",
        details={
            "worker_mode": settings.worker_mode,
            "event_level": settings.event_level,
            "worker_auto_enabled": settings.worker_auto_enabled,
            "worker_max_concurrency": settings.worker_max_concurrency,
            "worker_max_concurrency_per_connection": (
                settings.worker_max_concurrency_per_connection
            ),
        },
    )
