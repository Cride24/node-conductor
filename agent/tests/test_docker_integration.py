import os

import pytest
from fastapi.testclient import TestClient

from nodeconductor_agent.api import create_app
from nodeconductor_agent.docker_gateway import DockerSDKGateway
from nodeconductor_agent.errors import EngineUnavailableError


@pytest.mark.docker_integration
def test_real_docker_inventory_list_and_inspect_are_read_only() -> None:
    if os.getenv("NODECONDUCTOR_AGENT_SKIP_DOCKER_INTEGRATION") == "1":
        pytest.skip("Docker integration disabled by environment")
    gateway = DockerSDKGateway(timeout_seconds=2)
    try:
        gateway.ping()
        page = gateway.list_containers(limit=5, offset=0)
    except EngineUnavailableError:
        pytest.skip("Docker Engine is unavailable")

    assert page.total >= len(page.items)
    assert len(page.items) <= 5
    if not page.items:
        pytest.skip("No existing container is available for read-only inspect")
    inspected = gateway.inspect_container(page.items[0].id)

    assert inspected.id == page.items[0].id
    assert len(inspected.id) == 64


@pytest.mark.docker_integration
def test_real_docker_compose_inventory_is_grouped_read_only(tmp_path) -> None:
    if os.getenv("NODECONDUCTOR_AGENT_SKIP_DOCKER_INTEGRATION") == "1":
        pytest.skip("Docker integration disabled by environment")
    gateway = DockerSDKGateway(timeout_seconds=2)
    try:
        snapshots = gateway.list_all_containers()
    except EngineUnavailableError:
        pytest.skip("Docker Engine is unavailable")
    compose_ids = {
        snapshot.id
        for snapshot in snapshots
        if snapshot.compose_classification == "coherent"
    }
    if not compose_ids:
        pytest.skip("No existing Compose project is available")

    with TestClient(
        create_app(gateway, tmp_path / "integration.sqlite3")
    ) as client:
        response = client.get("/api/v2/resources?limit=100")

    assert response.status_code == 200
    projects = [
        item for item in response.json()["items"]
        if item["target_kind"] == "compose_project"
    ]
    assert projects
    returned_member_ids = {
        member["docker_id"]
        for project in projects
        for member in project["members"]
    }
    assert compose_ids <= returned_member_ids
