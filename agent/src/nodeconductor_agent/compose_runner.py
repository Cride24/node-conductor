"""Fixed Docker Compose start/stop runner with no free-form command surface."""

from collections.abc import Callable
import shutil
import subprocess
from typing import Protocol

from nodeconductor_agent.action_errors import (
    ActionConfirmedFailure,
    ActionIndeterminateError,
    ActionNotDispatchedError,
)
from nodeconductor_agent.compose_registry import ComposeProjectDefinition
from nodeconductor_agent.models import ResourceAction


class ComposeRunner(Protocol):
    def is_available(self) -> bool: ...

    def execute(
        self,
        project: ComposeProjectDefinition,
        action: ResourceAction,
    ) -> None: ...


class SubprocessComposeRunner:
    def __init__(
        self,
        *,
        start_timeout_seconds: int = 30,
        stop_timeout_margin_seconds: int = 10,
        run_command: Callable = subprocess.run,
        find_executable: Callable[[str], str | None] = shutil.which,
    ) -> None:
        if not 1 <= start_timeout_seconds <= 60:
            raise ValueError("Compose start timeout must be between 1 and 60")
        if not 1 <= stop_timeout_margin_seconds <= 30:
            raise ValueError("Compose stop timeout margin must be between 1 and 30")
        self._start_timeout_seconds = start_timeout_seconds
        self._stop_timeout_margin_seconds = stop_timeout_margin_seconds
        self._run_command = run_command
        self._find_executable = find_executable

    def is_available(self) -> bool:
        if self._find_executable("docker") is None:
            return False
        try:
            result = self._run_command(
                ["docker", "compose", "version"],
                shell=False,
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0

    def execute(
        self,
        project: ComposeProjectDefinition,
        action: ResourceAction,
    ) -> None:
        if action not in {"start", "stop"}:
            raise ActionNotDispatchedError("unsupported_action")
        arguments = [
            "docker",
            "compose",
            "--project-name",
            project.project_name,
            "--project-directory",
            str(project.working_directory),
        ]
        for compose_file in project.compose_files:
            arguments.extend(["-f", str(compose_file)])
        arguments.append(action)
        if action == "stop":
            arguments.extend(["--timeout", str(project.stop_timeout_seconds)])
            process_timeout = (
                project.stop_timeout_seconds + self._stop_timeout_margin_seconds
            )
        else:
            process_timeout = self._start_timeout_seconds
        try:
            result = self._run_command(
                arguments,
                cwd=str(project.working_directory),
                shell=False,
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=process_timeout,
            )
        except subprocess.TimeoutExpired as error:
            raise ActionIndeterminateError("compose_timeout") from error
        except OSError as error:
            raise ActionNotDispatchedError("compose_process_unavailable") from error
        if result.returncode != 0:
            raise ActionConfirmedFailure("compose_action_failed")
