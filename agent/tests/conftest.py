from datetime import datetime, timezone

import pytest

from nodeconductor_agent.errors import (
    ContainerNotFoundError,
    EngineUnavailableError,
)
from nodeconductor_agent.models import (
    ContainerPage,
    ContainerSnapshot,
    EngineVersion,
)


CONTAINER_A_ID = "a" * 64
CONTAINER_B_ID = "b" * 64
CONTAINER_C_ID = "c" * 64


def snapshot(container_id: str, name: str) -> ContainerSnapshot:
    return ContainerSnapshot(
        id=container_id,
        name=name,
        state="running",
        health_status="healthy",
        created_at=datetime(2026, 8, 23, 8, 0, tzinfo=timezone.utc),
    )


class FakeDockerGateway:
    def __init__(self, containers=None, unavailable: bool = False) -> None:
        self.containers = {
            container.id: container for container in (containers or [])
        }
        self.unavailable = unavailable

    def ping(self) -> None:
        if self.unavailable:
            raise EngineUnavailableError()

    def engine_version(self) -> EngineVersion:
        if self.unavailable:
            raise EngineUnavailableError()
        return EngineVersion(engine_version="27.1.1", api_version="1.46")

    def list_containers(self, limit: int, offset: int) -> ContainerPage:
        if self.unavailable:
            raise EngineUnavailableError()
        containers = sorted(self.containers.values(), key=lambda item: item.id)
        return ContainerPage(
            items=containers[offset : offset + limit],
            total=len(containers),
        )

    def inspect_container(self, container_id: str) -> ContainerSnapshot:
        if self.unavailable:
            raise EngineUnavailableError()
        try:
            return self.containers[container_id]
        except KeyError as error:
            raise ContainerNotFoundError() from error


@pytest.fixture
def fake_gateway() -> FakeDockerGateway:
    return FakeDockerGateway(
        [
            snapshot(CONTAINER_A_ID, "alpha"),
            snapshot(CONTAINER_B_ID, "beta"),
            snapshot(CONTAINER_C_ID, "gamma"),
        ]
    )
