import os

import pytest

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
