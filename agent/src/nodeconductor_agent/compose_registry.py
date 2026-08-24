"""Agent-local allowlist for pre-existing Docker Compose projects."""

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Mapping

try:
    import tomllib
except ImportError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib


PROJECT_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,254}$")
MAX_COMPOSE_FILES = 16
MIN_STOP_TIMEOUT_SECONDS = 1
MAX_STOP_TIMEOUT_SECONDS = 300


class ComposeRegistryError(ValueError):
    """Invalid or unavailable local registry; details stay local."""


@dataclass(frozen=True)
class ComposeProjectDefinition:
    project_name: str
    working_directory: Path
    compose_files: tuple[Path, ...]
    stop_timeout_seconds: int


class ComposeProjectRegistry:
    def __init__(
        self,
        projects: Mapping[str, ComposeProjectDefinition] | None = None,
        *,
        usable: bool = True,
    ) -> None:
        self._projects = dict(projects or {})
        self.usable = usable

    @classmethod
    def load(cls, registry_path: str | Path) -> "ComposeProjectRegistry":
        path = Path(registry_path)
        if not path.is_absolute():
            raise ComposeRegistryError("registry path must be absolute")
        try:
            resolved_registry = path.resolve(strict=True)
        except OSError as error:
            raise ComposeRegistryError("registry file is unavailable") from error
        if not resolved_registry.is_file():
            raise ComposeRegistryError("registry path must be a regular file")
        try:
            with resolved_registry.open("rb") as handle:
                raw = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError) as error:
            raise ComposeRegistryError("registry TOML is invalid") from error
        if set(raw) != {"projects"} or not isinstance(raw["projects"], dict):
            raise ComposeRegistryError("registry must contain only projects")
        projects: dict[str, ComposeProjectDefinition] = {}
        for registry_name, value in raw["projects"].items():
            projects[registry_name] = cls._parse_project(registry_name, value)
        return cls(projects)

    @classmethod
    def load_or_unavailable(
        cls,
        registry_path: str | Path,
    ) -> "ComposeProjectRegistry":
        try:
            return cls.load(registry_path)
        except ComposeRegistryError:
            return cls(usable=False)

    @staticmethod
    def _parse_project(
        registry_name: object,
        value: object,
    ) -> ComposeProjectDefinition:
        if not isinstance(registry_name, str) or not PROJECT_NAME_PATTERN.fullmatch(
            registry_name
        ):
            raise ComposeRegistryError("registry project key is invalid")
        if not isinstance(value, dict) or set(value) != {
            "project_name",
            "working_directory",
            "compose_files",
            "stop_timeout_seconds",
        }:
            raise ComposeRegistryError("registry project fields are invalid")
        project_name = value["project_name"]
        if (
            not isinstance(project_name, str)
            or project_name != registry_name
            or not PROJECT_NAME_PATTERN.fullmatch(project_name)
        ):
            raise ComposeRegistryError("registered project identity is invalid")
        working_directory = _resolved_directory(value["working_directory"])
        raw_files = value["compose_files"]
        if (
            not isinstance(raw_files, list)
            or not raw_files
            or len(raw_files) > MAX_COMPOSE_FILES
            or not all(isinstance(item, str) for item in raw_files)
        ):
            raise ComposeRegistryError("compose_files is invalid")
        compose_files = tuple(_resolved_file(item) for item in raw_files)
        if len(set(compose_files)) != len(compose_files):
            raise ComposeRegistryError("compose_files contains duplicates")
        timeout = value["stop_timeout_seconds"]
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, int)
            or timeout < MIN_STOP_TIMEOUT_SECONDS
            or timeout > MAX_STOP_TIMEOUT_SECONDS
        ):
            raise ComposeRegistryError("stop timeout is outside allowed bounds")
        return ComposeProjectDefinition(
            project_name=project_name,
            working_directory=working_directory,
            compose_files=compose_files,
            stop_timeout_seconds=timeout,
        )

    def get(self, project_name: str) -> ComposeProjectDefinition | None:
        if not self.usable:
            return None
        return self._projects.get(project_name)

    @property
    def has_projects(self) -> bool:
        return self.usable and bool(self._projects)


def _absolute_path(value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise ComposeRegistryError("registry paths must be non-empty strings")
    path = Path(value)
    if not path.is_absolute():
        raise ComposeRegistryError("registry paths must be absolute")
    try:
        return path.resolve(strict=True)
    except OSError as error:
        raise ComposeRegistryError("registered path is unavailable") from error


def _resolved_directory(value: object) -> Path:
    path = _absolute_path(value)
    if not path.is_dir():
        raise ComposeRegistryError("working directory must be a directory")
    return path


def _resolved_file(value: object) -> Path:
    path = _absolute_path(value)
    if not path.is_file():
        raise ComposeRegistryError("compose path must be a regular file")
    return path
