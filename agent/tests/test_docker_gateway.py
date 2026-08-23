from conftest import CONTAINER_A_ID
from nodeconductor_agent.docker_gateway import DockerSDKGateway


class FakeContainer:
    def __init__(self) -> None:
        self.id = CONTAINER_A_ID
        self.attrs = {
            "Id": CONTAINER_A_ID,
            "Name": "/safe-name",
            "Created": "2026-08-23T08:00:00Z",
            "State": {
                "Status": "running",
                "Health": {"Status": "healthy", "Log": ["secret-output"]},
            },
            "Config": {
                "Env": ["PASSWORD=secret"],
                "Labels": {"secret": "value"},
            },
            "Mounts": [{"Source": "/sensitive/host/path"}],
        }
        self.reload_calls = 0

    def reload(self) -> None:
        self.reload_calls += 1


class FakeContainers:
    def __init__(self, container) -> None:
        self.container = container

    def list(self, all: bool):
        assert all is True
        return [self.container]

    def get(self, container_id: str):
        assert container_id == CONTAINER_A_ID
        return self.container


class FakeClient:
    def __init__(self) -> None:
        self.container = FakeContainer()
        self.containers = FakeContainers(self.container)

    def ping(self) -> bool:
        return True

    def version(self) -> dict:
        return {
            "Version": "27.1.1",
            "ApiVersion": "1.46",
            "KernelVersion": "sensitive-host-detail",
        }


def test_official_sdk_adapter_maps_only_allowlisted_fields() -> None:
    client = FakeClient()
    gateway = DockerSDKGateway(client=client)

    gateway.ping()
    version = gateway.engine_version()
    page = gateway.list_containers(limit=10, offset=0)
    inspected = gateway.inspect_container(CONTAINER_A_ID)

    assert version.engine_version == "27.1.1"
    assert version.api_version == "1.46"
    assert page.total == 1
    assert page.items[0] == inspected
    assert inspected.id == CONTAINER_A_ID
    assert inspected.name == "safe-name"
    assert inspected.state == "running"
    assert inspected.health_status == "healthy"
    serialized = repr(inspected)
    assert "PASSWORD" not in serialized
    assert "sensitive" not in serialized
    assert "Labels" not in serialized
