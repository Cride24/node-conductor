"""Narrow Docker SDK adapter that never exposes raw Docker configuration."""

from datetime import datetime, timezone
from typing import Protocol

try:
    import docker
    from docker.errors import APIError, DockerException, NotFound
except ImportError:  # Permet les tests unitaires sans moteur ni SDK installe.
    docker = None

    class DockerException(Exception):
        pass

    class APIError(DockerException):
        pass

    class NotFound(APIError):
        pass

from nodeconductor_agent.errors import (
    ContainerNotFoundError,
    DockerOperationError,
    EngineUnavailableError,
)
from nodeconductor_agent.models import (
    ContainerPage,
    ContainerSnapshot,
    ContainerState,
    EngineVersion,
    HealthStatus,
)


VALID_STATES = {
    "created",
    "running",
    "paused",
    "restarting",
    "removing",
    "exited",
    "dead",
}
VALID_HEALTH_STATUSES = {"starting", "healthy", "unhealthy"}


class DockerGateway(Protocol):
    def ping(self) -> None: ...

    def engine_version(self) -> EngineVersion: ...

    def list_containers(self, limit: int, offset: int) -> ContainerPage: ...

    def inspect_container(self, container_id: str) -> ContainerSnapshot: ...


def _parse_created_at(value: object) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return datetime.fromtimestamp(0, timezone.utc)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return datetime.fromtimestamp(0, timezone.utc)


def _snapshot_from_attrs(attrs: dict) -> ContainerSnapshot:
    state_details = attrs.get("State")
    if not isinstance(state_details, dict):
        state_details = {}
    state_value = str(state_details.get("Status", "unknown")).lower()
    state: ContainerState = (
        state_value if state_value in VALID_STATES else "unknown"
    )
    health_details = state_details.get("Health")
    health_value = (
        str(health_details.get("Status", "none")).lower()
        if isinstance(health_details, dict)
        else "none"
    )
    health: HealthStatus = (
        health_value if health_value in VALID_HEALTH_STATUSES else "none"
    )
    raw_id = str(attrs.get("Id", "")).lower()
    raw_name = str(attrs.get("Name", "")).lstrip("/")
    return ContainerSnapshot(
        id=raw_id,
        name=raw_name or raw_id[:12],
        state=state,
        health_status=health,
        created_at=_parse_created_at(attrs.get("Created")),
    )


class DockerSDKGateway:
    """Read-only allowlist over the official Docker SDK."""

    def __init__(self, timeout_seconds: int = 5, client=None) -> None:
        self._timeout_seconds = timeout_seconds
        self._client = client

    def _get_client(self):
        if self._client is not None:
            return self._client
        if docker is None:
            raise EngineUnavailableError()
        try:
            self._client = docker.from_env(timeout=self._timeout_seconds)
        except DockerException as error:
            raise EngineUnavailableError() from error
        return self._client

    def ping(self) -> None:
        try:
            self._get_client().ping()
        except DockerException as error:
            raise EngineUnavailableError() from error

    def engine_version(self) -> EngineVersion:
        try:
            version = self._get_client().version()
        except DockerException as error:
            raise EngineUnavailableError() from error
        return EngineVersion(
            engine_version=str(version.get("Version", "unknown"))[:100],
            api_version=str(version.get("ApiVersion", "unknown"))[:100],
        )

    def list_containers(self, limit: int, offset: int) -> ContainerPage:
        try:
            containers = sorted(
                self._get_client().containers.list(all=True),
                key=lambda container: container.id,
            )
            selected = containers[offset : offset + limit]
            items = []
            for container in selected:
                try:
                    items.append(self._inspect_object(container))
                except NotFound:
                    continue
        except (APIError, DockerException) as error:
            raise EngineUnavailableError() from error
        except (KeyError, TypeError, ValueError) as error:
            raise DockerOperationError() from error
        return ContainerPage(items=items, total=len(containers))

    def inspect_container(self, container_id: str) -> ContainerSnapshot:
        try:
            container = self._get_client().containers.get(container_id)
            return self._inspect_object(container)
        except NotFound as error:
            raise ContainerNotFoundError() from error
        except (APIError, DockerException) as error:
            raise EngineUnavailableError() from error
        except (KeyError, TypeError, ValueError) as error:
            raise DockerOperationError() from error

    @staticmethod
    def _inspect_object(container) -> ContainerSnapshot:
        container.reload()
        return _snapshot_from_attrs(container.attrs)
