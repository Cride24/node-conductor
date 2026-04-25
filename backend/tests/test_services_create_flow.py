from fastapi.testclient import TestClient

from nodeconductor.main import app
from nodeconductor.repositories.services_repository import reset_rows


client = TestClient(app)


def setup_function() -> None:
    reset_rows()


def test_create_service_then_list_contains_new_service() -> None:
    create_payload = {
        "name": "forge",
        "type": "LXC",
        "category": "game",
        "description": "instance minecraft forge",
        "dependencies": [1],
        "device_dependencies": None,
    }

    create_response = client.post("/api/v1/services/", json=create_payload)
    assert create_response.status_code == 201

    created = create_response.json()
    assert created["id"] > 0
    assert created["name"] == create_payload["name"]
    assert created["status"] == "off"

    list_response = client.get("/api/v1/services")
    assert list_response.status_code == 200

    listed_services = list_response.json()["services"]
    names = [service["name"] for service in listed_services]
    assert "forge" in names


def test_create_service_with_duplicate_name_returns_409() -> None:
    create_payload = {
        "name": "forge",
        "type": "LXC",
        "category": "game",
        "description": "instance minecraft forge",
        "dependencies": None,
        "device_dependencies": None,
    }

    first_response = client.post("/api/v1/services/", json=create_payload)
    assert first_response.status_code == 201

    duplicate_response = client.post("/api/v1/services/", json=create_payload)
    assert duplicate_response.status_code == 409
    assert "already exists" in duplicate_response.json()["detail"]
