from fastapi.testclient import TestClient

from conftest import CONTAINER_A_ID, FakeDockerGateway
from nodeconductor_agent.api import create_app


def test_list_is_paginated_and_returns_only_allowed_inventory(
    tmp_path,
    fake_gateway,
) -> None:
    client = TestClient(create_app(fake_gateway, tmp_path / "agent.sqlite3"))

    response = client.get(
        "/api/v1/containers",
        params={"limit": 1, "offset": 1},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 1
    assert body["offset"] == 1
    assert body["total"] == 3
    assert len(body["items"]) == 1
    assert set(body["items"][0]) == {
        "id",
        "name",
        "state",
        "health_status",
        "created_at",
        "management_policy",
    }
    assert body["items"][0]["management_policy"] == "discovered"
    assert "env" not in response.text.lower()
    assert "mount" not in response.text.lower()
    assert "label" not in response.text.lower()


def test_pagination_and_container_id_are_bounded(tmp_path, fake_gateway) -> None:
    client = TestClient(create_app(fake_gateway, tmp_path / "agent.sqlite3"))

    assert client.get("/api/v1/containers?limit=0").status_code == 422
    assert client.get("/api/v1/containers?limit=101").status_code == 422
    assert client.get("/api/v1/containers?offset=100001").status_code == 422
    response = client.get("/api/v1/containers/not-a-docker-id")

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "invalid_request",
            "message": "Request validation failed",
        }
    }


def test_inspection_of_missing_container_is_normalized(
    tmp_path,
    fake_gateway,
) -> None:
    client = TestClient(create_app(fake_gateway, tmp_path / "agent.sqlite3"))

    response = client.get(f"/api/v1/containers/{'f' * 64}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "container_not_found"


def test_engine_unavailable_is_reported_without_host_details(tmp_path) -> None:
    gateway = FakeDockerGateway(unavailable=True)
    client = TestClient(create_app(gateway, tmp_path / "agent.sqlite3"))

    health = client.get("/api/v1/health")
    capabilities = client.get("/api/v1/capabilities")
    listing = client.get("/api/v1/containers")

    assert health.status_code == 200
    assert health.json()["status"] == "degraded"
    assert health.json()["engine_status"] == "engine_unavailable"
    assert capabilities.status_code == 200
    assert capabilities.json()["engine_available"] is False
    assert "container_list" not in capabilities.json()["capabilities"]
    assert "management_policy" not in capabilities.json()["capabilities"]
    assert listing.status_code == 503
    assert listing.json()["error"]["code"] == "engine_unavailable"
    assert set(listing.json()["error"]) == {"code", "message"}


def test_capabilities_report_only_implemented_operations(
    tmp_path,
    fake_gateway,
) -> None:
    client = TestClient(create_app(fake_gateway, tmp_path / "agent.sqlite3"))

    response = client.get("/api/v1/capabilities")

    assert response.status_code == 200
    assert response.json()["engine_version"] == "27.1.1"
    assert response.json()["docker_api_version"] == "1.46"
    assert set(response.json()["capabilities"]) == {
        "health",
        "capabilities",
        "container_list",
        "container_inspect",
        "management_policy",
    }
    assert "start" not in response.text
    assert "stop" not in response.text


def test_request_body_size_is_bounded(tmp_path, fake_gateway) -> None:
    client = TestClient(
        create_app(
            fake_gateway,
            tmp_path / "agent.sqlite3",
            max_request_body_bytes=128,
        )
    )

    response = client.put(
        f"/api/v1/containers/{CONTAINER_A_ID}/management-policy",
        content="x" * 129,
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"
