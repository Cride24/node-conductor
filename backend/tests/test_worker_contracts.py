import psycopg
import pytest
from fastapi.testclient import TestClient

from nodeconductor.main import app
from nodeconductor.repositories.jobs_repository import fetch_job_by_id
from nodeconductor.repositories.services_repository import reset_rows
from nodeconductor.repositories.worker_contracts_repository import (
    create_agent_connection_row,
    create_service_target_binding_row,
    create_target_row,
    fetch_service_target_binding_row,
    update_target_management_policy_row,
)
from nodeconductor.schemas.jobs.common import Job
from nodeconductor.schemas.worker_contracts import (
    AgentConnection,
    OperationalTarget,
    ServiceTargetBinding,
)


client = TestClient(app)


def setup_function() -> None:
    reset_rows()


def _create_connection() -> AgentConnection:
    row = create_agent_connection_row(
        {
            "id": "docker-host-principal",
            "description": "Agent Docker principal",
            "transport": "unix_socket",
            "endpoint": "/run/nodeconductor-agent.sock",
        }
    )
    return AgentConnection(**row)


def _create_target(name: str = "jellyfin") -> OperationalTarget:
    row = create_target_row(
        {
            "driver": "docker",
            "connection_id": "docker-host-principal",
            "target": name,
        }
    )
    return OperationalTarget(**row)


def test_connection_and_target_default_to_discovered() -> None:
    connection = _create_connection()
    target = _create_target()

    assert connection.default_management_policy == "discovered"
    assert target.management_policy == "discovered"
    assert (target.driver, target.connection_id, target.target) == (
        "docker",
        "docker-host-principal",
        "jellyfin",
    )


def test_operational_target_triplet_is_unique() -> None:
    _create_connection()
    _create_target()

    with pytest.raises(psycopg.errors.UniqueViolation):
        _create_target()


@pytest.mark.parametrize("policy", ["managed", "protected", "discovered"])
def test_target_supports_each_management_policy(policy: str) -> None:
    _create_connection()
    target = _create_target()

    updated = update_target_management_policy_row(target.id, policy)

    assert updated is not None
    assert OperationalTarget(**updated).management_policy == policy


@pytest.mark.parametrize(
    "readiness_check",
    ["docker_state", "docker_health", "http", "tcp"],
)
def test_service_binding_supports_each_readiness_check(
    readiness_check: str,
) -> None:
    _create_connection()
    target = _create_target()
    create_service_target_binding_row(
        {
            "service_id": 1,
            "target_id": target.id,
            "readiness_check": readiness_check,
        }
    )

    row = fetch_service_target_binding_row(1)

    assert row is not None
    binding = ServiceTargetBinding(**row)
    assert binding.readiness_check == readiness_check
    assert binding.service_description == (
        "serveur minecraft sur le theme steampunk"
    )


def test_indeterminate_job_sets_service_unknown_and_records_warning() -> None:
    start_response = client.post("/api/v1/services/1/start", json={})
    assert start_response.status_code == 202

    completion_response = client.post(
        "/api/v1/jobs/1/simulate-complete",
        json={"result": "indeterminate"},
    )

    assert completion_response.status_code == 200
    job_body = completion_response.json()
    assert job_body["status"] == "indeterminate"
    assert job_body["queue_duration_ms"] is None
    assert job_body["execution_duration_ms"] is None
    assert job_body["verification_duration_ms"] is None
    assert job_body["total_duration_ms"] is None

    service_response = client.get("/api/v1/services/1")
    assert service_response.status_code == 200
    assert service_response.json()["status"] == "unknown"

    events_response = client.get("/api/v1/events", params={"job_id": 1})
    assert events_response.status_code == 200
    indeterminate_event = next(
        event
        for event in events_response.json()["events"]
        if event["event_type"] == "job.indeterminate"
    )
    assert indeterminate_event["severity"] == "warning"


def test_job_duration_fields_are_reserved_and_non_negative() -> None:
    response = client.post("/api/v1/services/1/start", json={})
    assert response.status_code == 202

    row = fetch_job_by_id(1)

    assert row is not None
    job = Job(**row)
    assert job.queue_duration_ms is None
    assert job.execution_duration_ms is None
    assert job.verification_duration_ms is None
    assert job.total_duration_ms is None

    invalid_row = {**row, "total_duration_ms": -1}
    with pytest.raises(ValueError):
        Job(**invalid_row)
