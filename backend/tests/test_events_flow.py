from fastapi.testclient import TestClient

from nodeconductor.main import app
from nodeconductor.repositories.services_repository import reset_rows
from nodeconductor.services.events import record_event, record_system_started_event


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


def test_system_started_event_records_instance_mode() -> None:
    record_system_started_event()

    response = client.get("/api/v1/events")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    event = body["events"][0]
    assert event["event_type"] == "system.started"
    assert event["actor_type"] == "system"
    assert event["details"]["worker_mode"] == "simulation"
    assert event["details"]["event_level"] == "info"
    assert event["details"]["worker_auto_enabled"] is False


def test_events_list_can_filter_by_job_id() -> None:
    job_response = client.post("/api/v1/services/1/start", json={})
    assert job_response.status_code == 202

    response = client.get("/api/v1/events", params={"job_id": 1})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["events"][0]["event_type"] == "job.requested"
    assert body["events"][0]["job_id"] == 1


def test_job_requested_event_keeps_request_actor() -> None:
    job_response = client.post(
        "/api/v1/services/1/start",
        json={"requested_by_type": "llm", "requested_by_id": "agent-1"},
    )
    assert job_response.status_code == 202

    response = client.get("/api/v1/events", params={"job_id": 1})

    assert response.status_code == 200
    event = response.json()["events"][0]
    assert event["event_type"] == "job.requested"
    assert event["actor_type"] == "llm"
    assert event["actor_id"] == "agent-1"


def test_worker_records_job_and_status_events() -> None:
    job_response = client.post("/api/v1/services/1/start", json={})
    assert job_response.status_code == 202

    completion_response = client.post(
        "/api/v1/jobs/1/simulate-complete",
        json={"result": "succeeded"},
    )
    assert completion_response.status_code == 200

    response = client.get("/api/v1/events", params={"job_id": 1})

    assert response.status_code == 200
    event_types = [event["event_type"] for event in response.json()["events"]]
    assert "job.requested" in event_types
    assert "job.started" in event_types
    assert "job.succeeded" in event_types
    assert event_types.count("service.status_changed") == 2


def test_cancel_records_event() -> None:
    job_response = client.post("/api/v1/services/1/start", json={})
    assert job_response.status_code == 202

    cancel_response = client.post("/api/v1/jobs/1/cancel")
    assert cancel_response.status_code == 200

    response = client.get("/api/v1/events", params={"job_id": 1})

    assert response.status_code == 200
    event_types = [event["event_type"] for event in response.json()["events"]]
    assert "job.requested" in event_types
    assert "job.cancelled" in event_types


def test_conflict_records_rejected_event() -> None:
    start_response = client.post("/api/v1/services/1/start", json={})
    assert start_response.status_code == 202

    stop_response = client.post("/api/v1/services/1/stop", json={})
    assert stop_response.status_code == 409

    response = client.get("/api/v1/events", params={"service_id": 1})

    assert response.status_code == 200
    event_types = [event["event_type"] for event in response.json()["events"]]
    assert "job.requested" in event_types
    assert "action.rejected" in event_types
