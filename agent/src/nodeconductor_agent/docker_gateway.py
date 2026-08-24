"""Narrow Docker SDK adapter with inventory plus container start/stop only."""

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
from nodeconductor_agent.action_errors import (
    ActionConfirmedFailure,
    ActionIndeterminateError,
    ActionNotDispatchedError,
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
COMPOSE_PROJECT_LABEL = "com.docker.compose.project"
COMPOSE_SERVICE_LABEL = "com.docker.compose.service"


class DockerGateway(Protocol):
    def ping(self) -> None: ...

    def engine_version(self) -> EngineVersion: ...

    def list_containers(self, limit: int, offset: int) -> ContainerPage: ...

    def list_all_containers(self) -> list[ContainerSnapshot]: ...

    def inspect_container(self, container_id: str) -> ContainerSnapshot: ...

    def start_container(self, container_id: str) -> None: ...

    def stop_container(self, container_id: str, timeout_seconds: int) -> None: ...


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
    classification, project, service = _compose_metadata(attrs)
    return ContainerSnapshot(
        id=raw_id,
        name=raw_name or raw_id[:12],
        state=state,
        health_status=health,
        created_at=_parse_created_at(attrs.get("Created")),
        compose_classification=classification,
        compose_project=project,
        compose_service=service,
    )


def _compose_metadata(attrs: dict) -> tuple[str, str | None, str | None]:
    """Read only the two identity labels; never retain or expose raw labels."""
    config = attrs.get("Config")
    labels = config.get("Labels") if isinstance(config, dict) else None
    if not isinstance(labels, dict):
        return "none", None, None
    project_present = COMPOSE_PROJECT_LABEL in labels
    service_present = COMPOSE_SERVICE_LABEL in labels
    if not project_present and not service_present:
        return "none", None, None
    project = _safe_compose_label(labels.get(COMPOSE_PROJECT_LABEL))
    service = _safe_compose_label(labels.get(COMPOSE_SERVICE_LABEL))
    if project_present and service_present and project and service:
        return "coherent", project, service
    return "ambiguous", project, service


def _safe_compose_label(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > 255
        or any(ord(character) < 32 for character in normalized)
        or "/" in normalized
        or "\\" in normalized
    ):
        return None
    return normalized


class DockerSDKGateway:
    """Allowlist over the official SDK; no generic Docker call is exposed."""

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
        containers = self.list_all_containers()
        return ContainerPage(
            items=containers[offset : offset + limit],
            total=len(containers),
        )

    def list_all_containers(self) -> list[ContainerSnapshot]:
        try:
            containers = sorted(
                self._get_client().containers.list(all=True),
                key=lambda container: container.id,
            )
            items = []
            for container in containers:
                try:
                    items.append(self._inspect_object(container))
                except NotFound:
                    continue
        except (APIError, DockerException) as error:
            raise EngineUnavailableError() from error
        except (KeyError, TypeError, ValueError) as error:
            raise DockerOperationError() from error
        return items

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

    def start_container(self, container_id: str) -> None:
        container = self._container_for_action(container_id)
        try:
            container.start()
        except APIError as error:
            raise ActionConfirmedFailure("container_start_failed") from error
        except DockerException as error:
            raise ActionIndeterminateError("docker_transport_interrupted") from error

    def stop_container(self, container_id: str, timeout_seconds: int) -> None:
        container = self._container_for_action(container_id)
        try:
            container.stop(timeout=timeout_seconds)
        except APIError as error:
            raise ActionConfirmedFailure("container_stop_failed") from error
        except DockerException as error:
            raise ActionIndeterminateError("docker_transport_interrupted") from error

    def _container_for_action(self, container_id: str):
        try:
            return self._get_client().containers.get(container_id)
        except NotFound as error:
            raise ActionNotDispatchedError("container_not_found") from error
        except (APIError, DockerException) as error:
            raise ActionNotDispatchedError("docker_transport_unavailable") from error

    @staticmethod
    def _inspect_object(container) -> ContainerSnapshot:
        container.reload()
        return _snapshot_from_attrs(container.attrs)
