from fastapi.testclient import TestClient

from nodeconductor.main import app
from nodeconductor.repositories.services_repository import reset_rows
from nodeconductor.services.events import record_event


client = TestClient(app)


def setup_function() -> None:
    reset_rows()


def test_events_list_is_empty_after_reset() -> None:
    response = client.get("/api/v1/events")

    assert response.status_code == 200
    assert response.json() == {"total": 0, "events": []}


def test_events_list_returns_recorded_event() -> None:
    record_event(
        event_type="service.created",
        severity="info",
        message="Service created",
        service_id=1,
        actor_type="system",
        details={"name": "steampunk"},
    )

    response = client.get("/api/v1/events")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    event = body["events"][0]
    assert event["event_type"] == "service.created"
    assert event["severity"] == "info"
    assert event["service_id"] == 1
    assert event["details"] == {"name": "steampunk"}


def test_events_list_can_filter_by_job_id() -> None:
    job_response = client.post("/api/v1/services/1/start", json={})
    assert job_response.status_code == 202
    record_event(
        event_type="job.requested",
        severity="info",
        message="Start requested",
        service_id=1,
        job_id=1,
        actor_type="system",
    )

    response = client.get("/api/v1/events", params={"job_id": 1})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["events"][0]["job_id"] == 1
