from fastapi.testclient import TestClient

from nodeconductor.main import app
from nodeconductor.repositories.services_repository import reset_rows


client = TestClient(app)


def setup_function() -> None:
    reset_rows()


def test_update_service_description() -> None:
    # PATCH modifie les metadonnees sans toucher au status operationnel.
    response = client.patch(
        "/api/v1/services/1",
        json={"description": "serveur minecraft steampunk mis a jour"},
    )

    assert response.status_code == 200
    updated = response.json()
    assert updated["id"] == 1
    assert updated["name"] == "steampunk"
    assert updated["description"] == "serveur minecraft steampunk mis a jour"
    assert updated["status"] == "off"

    detail_response = client.get("/api/v1/services/1")
    assert detail_response.status_code == 200
    assert detail_response.json()["description"] == "serveur minecraft steampunk mis a jour"
    assert detail_response.json()["status"] == "off"


def test_update_service_status_is_rejected() -> None:
    # status appartient aux actions metier, pas au PATCH general.
    response = client.patch("/api/v1/services/1", json={"status": "starting"})

    assert response.status_code == 422

    detail_response = client.get("/api/v1/services/1")
    assert detail_response.status_code == 200
    assert detail_response.json()["status"] == "off"


def test_update_unknown_service_returns_404() -> None:
    response = client.patch(
        "/api/v1/services/999",
        json={"description": "service absent"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Service not found"


def test_update_service_with_empty_body_returns_400() -> None:
    response = client.patch("/api/v1/services/1", json={})

    assert response.status_code == 400
    assert "At least one field" in response.json()["detail"]


def test_update_service_with_duplicate_name_returns_409() -> None:
    response = client.patch("/api/v1/services/1", json={"name": "stefano"})

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]
