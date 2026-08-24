from dataclasses import replace
from datetime import datetime, timezone
from threading import Lock

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


def snapshot(
    container_id: str,
    name: str,
    *,
    compose_classification: str = "none",
    compose_project: str | None = None,
    compose_service: str | None = None,
    state: str = "running",
    health_status: str = "healthy",
) -> ContainerSnapshot:
    return ContainerSnapshot(
        id=container_id,
        name=name,
        state=state,
        health_status=health_status,
        created_at=datetime(2026, 8, 23, 8, 0, tzinfo=timezone.utc),
        compose_classification=compose_classification,
        compose_project=compose_project,
        compose_service=compose_service,
    )


class FakeDockerGateway:
    def __init__(self, containers=None, unavailable: bool = False) -> None:
        self.containers = {
            container.id: container for container in (containers or [])
        }
        self.unavailable = unavailable
        self.action_calls: list[tuple] = []
        self.action_lock = Lock()

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

    def list_all_containers(self) -> list[ContainerSnapshot]:
        if self.unavailable:
            raise EngineUnavailableError()
        return sorted(self.containers.values(), key=lambda item: item.id)

    def inspect_container(self, container_id: str) -> ContainerSnapshot:
        if self.unavailable:
            raise EngineUnavailableError()
        try:
            return self.containers[container_id]
        except KeyError as error:
            raise ContainerNotFoundError() from error

    def start_container(self, container_id: str) -> None:
        with self.action_lock:
            current = self.inspect_container(container_id)
            self.action_calls.append(("start", container_id))
            self.containers[container_id] = replace(current, state="running")

    def stop_container(self, container_id: str, timeout_seconds: int) -> None:
        with self.action_lock:
            current = self.inspect_container(container_id)
            self.action_calls.append(("stop", container_id, timeout_seconds))
            self.containers[container_id] = replace(current, state="exited")


@pytest.fixture
def fake_gateway() -> FakeDockerGateway:
    return FakeDockerGateway(
        [
            snapshot(CONTAINER_A_ID, "alpha"),
            snapshot(CONTAINER_B_ID, "beta"),
            snapshot(CONTAINER_C_ID, "gamma"),
        ]
    )
