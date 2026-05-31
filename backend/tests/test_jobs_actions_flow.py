from fastapi.testclient import TestClient

from nodeconductor.main import app
from nodeconductor.repositories.services_repository import reset_rows


client = TestClient(app)


def setup_function() -> None:
    reset_rows()


def test_start_service_creates_pending_job_without_changing_service_status() -> None:
    # L'API accepte la demande, mais le worker reste responsable du status service.
    response = client.post(
        "/api/v1/services/1/start",
        json={"requested_by_type": "llm", "requested_by_id": "agent-1"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["job_id"] == 1
    assert body["service_id"] == 1
    assert body["action"] == "start"
    assert body["job_status"] == "pending"
    assert body["service_status"] == "off"

    service_response = client.get("/api/v1/services/1")
    assert service_response.status_code == 200
    assert service_response.json()["status"] == "off"

    job_response = client.get("/api/v1/jobs/1")
    assert job_response.status_code == 200
    job = job_response.json()
    assert job["status"] == "pending"
    assert job["requested_by_type"] == "llm"
    assert job["requested_by_id"] == "agent-1"


def test_start_service_with_existing_start_job_is_idempotent() -> None:
    # Un LLM peut repeter la meme action: on renvoie le job existant.
    first_response = client.post("/api/v1/services/1/start", json={})
    assert first_response.status_code == 202

    second_response = client.post("/api/v1/services/1/start", json={})

    assert second_response.status_code == 200
    body = second_response.json()
    assert body["job_id"] == 1
    assert body["job_status"] == "pending"
    assert body["service_status"] == "off"
    assert "already requested" in body["message"]


def test_stop_service_with_active_start_job_returns_409() -> None:
    # Une action opposee a un job actif doit etre rejetee clairement.
    start_response = client.post("/api/v1/services/1/start", json={})
    assert start_response.status_code == 202

    stop_response = client.post("/api/v1/services/1/stop", json={})

    assert stop_response.status_code == 409
    assert "active start job" in stop_response.json()["detail"]


def test_stop_service_with_existing_stop_job_is_idempotent() -> None:
    # Meme garantie d'idempotence pour stop.
    first_response = client.post("/api/v1/services/2/stop", json={})
    assert first_response.status_code == 202

    second_response = client.post("/api/v1/services/2/stop", json={})

    assert second_response.status_code == 200
    body = second_response.json()
    assert body["job_id"] == 1
    assert body["job_status"] == "pending"
    assert body["service_status"] == "on"
    assert "already requested" in body["message"]


def test_start_service_with_active_stop_job_returns_409() -> None:
    stop_response = client.post("/api/v1/services/2/stop", json={})
    assert stop_response.status_code == 202

    start_response = client.post("/api/v1/services/2/start", json={})

    assert start_response.status_code == 409
    assert "active stop job" in start_response.json()["detail"]


def test_cancel_pending_job() -> None:
    # Annuler un job pending annule la demande, pas l'etat du service.
    start_response = client.post("/api/v1/services/1/start", json={})
    assert start_response.status_code == 202

    cancel_response = client.post("/api/v1/jobs/1/cancel")

    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "cancelled"

    service_response = client.get("/api/v1/services/1")
    assert service_response.status_code == 200
    assert service_response.json()["status"] == "off"


def test_simulate_cancelled_job_returns_409() -> None:
    start_response = client.post("/api/v1/services/1/start", json={})
    assert start_response.status_code == 202
    cancel_response = client.post("/api/v1/jobs/1/cancel")
    assert cancel_response.status_code == 200

    completion_response = client.post(
        "/api/v1/jobs/1/simulate-complete",
        json={"result": "succeeded"},
    )

    assert completion_response.status_code == 409
    assert "cannot be completed" in completion_response.json()["detail"]


def test_simulate_start_job_completion_sets_service_on() -> None:
    # simulate-complete joue le role du worker dans le MVP.
    start_response = client.post("/api/v1/services/1/start", json={})
    assert start_response.status_code == 202

    completion_response = client.post(
        "/api/v1/jobs/1/simulate-complete",
        json={"result": "succeeded"},
    )

    assert completion_response.status_code == 200
    assert completion_response.json()["status"] == "succeeded"

    service_response = client.get("/api/v1/services/1")
    assert service_response.status_code == 200
    assert service_response.json()["status"] == "on"


def test_simulate_missing_job_returns_404() -> None:
    completion_response = client.post(
        "/api/v1/jobs/999/simulate-complete",
        json={"result": "succeeded"},
    )

    assert completion_response.status_code == 404
    assert completion_response.json()["detail"] == "Job not found"


def test_simulate_succeeded_job_returns_409() -> None:
    start_response = client.post("/api/v1/services/1/start", json={})
    assert start_response.status_code == 202
    completion_response = client.post(
        "/api/v1/jobs/1/simulate-complete",
        json={"result": "succeeded"},
    )
    assert completion_response.status_code == 200

    second_completion_response = client.post(
        "/api/v1/jobs/1/simulate-complete",
        json={"result": "succeeded"},
    )

    assert second_completion_response.status_code == 409
    assert "cannot be completed" in second_completion_response.json()["detail"]


def test_cancel_succeeded_job_returns_409() -> None:
    start_response = client.post("/api/v1/services/1/start", json={})
    assert start_response.status_code == 202
    completion_response = client.post(
        "/api/v1/jobs/1/simulate-complete",
        json={"result": "succeeded"},
    )
    assert completion_response.status_code == 200

    cancel_response = client.post("/api/v1/jobs/1/cancel")

    assert cancel_response.status_code == 409
    assert "cannot be cancelled" in cancel_response.json()["detail"]


def test_stop_service_creates_pending_job_and_simulates_to_off() -> None:
    response = client.post("/api/v1/services/2/stop", json={})

    assert response.status_code == 202
    assert response.json()["action"] == "stop"
    assert response.json()["service_status"] == "on"

    completion_response = client.post(
        "/api/v1/jobs/1/simulate-complete",
        json={"result": "succeeded"},
    )
    assert completion_response.status_code == 200

    service_response = client.get("/api/v1/services/2")
    assert service_response.status_code == 200
    assert service_response.json()["status"] == "off"
