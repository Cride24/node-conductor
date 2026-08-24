from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from nodeconductor_agent.action_errors import ActionIndeterminateError
from nodeconductor_agent.compose_registry import (
    ComposeProjectRegistry,
    ComposeRegistryError,
)
from nodeconductor_agent.compose_runner import SubprocessComposeRunner


def _registry_file(tmp_path: Path, **updates) -> Path:
    working_directory = updates.get("working_directory", tmp_path / "stack")
    working_directory.mkdir(exist_ok=True)
    compose_file = updates.get("compose_file", working_directory / "compose.yml")
    if updates.get("create_compose_file", True):
        compose_file.write_text("services: {}\n", encoding="utf-8")
    project_name = updates.get("project_name", "n8n")
    timeout = updates.get("timeout", 30)
    registry = tmp_path / "compose-projects.toml"
    registry.write_text(
        "\n".join(
            [
                f"[projects.{project_name}]",
                f'project_name = "{project_name}"',
                f'working_directory = "{working_directory.as_posix()}"',
                f'compose_files = ["{compose_file.as_posix()}"]',
                f"stop_timeout_seconds = {timeout}",
            ]
        ),
        encoding="utf-8",
    )
    return registry


def test_registry_resolves_only_existing_absolute_local_paths(tmp_path) -> None:
    registry = ComposeProjectRegistry.load(_registry_file(tmp_path))

    project = registry.get("n8n")

    assert project.project_name == "n8n"
    assert project.working_directory.is_absolute()
    assert project.working_directory == project.working_directory.resolve()
    assert all(path.is_file() for path in project.compose_files)
    assert project.stop_timeout_seconds == 30


@pytest.mark.parametrize("timeout", [0, 301])
def test_registry_rejects_unbounded_stop_timeout(tmp_path, timeout) -> None:
    with pytest.raises(ComposeRegistryError):
        ComposeProjectRegistry.load(_registry_file(tmp_path, timeout=timeout))


def test_registry_rejects_relative_registry_path() -> None:
    with pytest.raises(ComposeRegistryError):
        ComposeProjectRegistry.load("compose-projects.toml")


def test_registry_rejects_missing_compose_file(tmp_path) -> None:
    with pytest.raises(ComposeRegistryError):
        ComposeProjectRegistry.load(
            _registry_file(tmp_path, create_compose_file=False)
        )


def test_registry_rejects_relative_registered_path(tmp_path) -> None:
    registry = tmp_path / "compose-projects.toml"
    registry.write_text(
        """
[projects.n8n]
project_name = "n8n"
working_directory = "relative"
compose_files = ["relative/compose.yml"]
stop_timeout_seconds = 30
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ComposeRegistryError):
        ComposeProjectRegistry.load(registry)


def test_runner_builds_exact_fixed_start_and_stop_arguments(tmp_path) -> None:
    project = ComposeProjectRegistry.load(_registry_file(tmp_path)).get("n8n")
    calls = []

    def run_command(arguments, **kwargs):
        calls.append((arguments, kwargs))
        return SimpleNamespace(returncode=0)

    runner = SubprocessComposeRunner(
        run_command=run_command,
        find_executable=lambda _: "docker",
    )

    runner.execute(project, "start")
    runner.execute(project, "stop")

    prefix = [
        "docker",
        "compose",
        "--project-name",
        "n8n",
        "--project-directory",
        str(project.working_directory),
        "-f",
        str(project.compose_files[0]),
    ]
    assert calls[0][0] == prefix + ["start"]
    assert calls[1][0] == prefix + ["stop", "--timeout", "30"]
    assert calls[0][1]["shell"] is False
    assert calls[1][1]["shell"] is False
    assert calls[0][1]["cwd"] == str(project.working_directory)
    forbidden = {"up", "down", "pull", "build", "create", "remove", "recreate"}
    assert forbidden.isdisjoint(calls[0][0])
    assert forbidden.isdisjoint(calls[1][0])


def test_runner_timeout_is_indeterminate_and_does_not_expose_output(tmp_path) -> None:
    project = ComposeProjectRegistry.load(_registry_file(tmp_path)).get("n8n")

    def timeout(arguments, **kwargs):
        raise subprocess.TimeoutExpired(arguments, kwargs["timeout"], output="secret")

    runner = SubprocessComposeRunner(
        run_command=timeout,
        find_executable=lambda _: "docker",
    )

    with pytest.raises(ActionIndeterminateError) as raised:
        runner.execute(project, "stop")

    assert raised.value.result_code == "compose_timeout"
    assert "secret" not in str(raised.value)


def test_compose_capability_probe_is_fixed_and_fail_closed() -> None:
    calls = []

    def run_command(arguments, **kwargs):
        calls.append((arguments, kwargs))
        return SimpleNamespace(returncode=0)

    runner = SubprocessComposeRunner(
        run_command=run_command,
        find_executable=lambda _: "docker",
    )

    assert runner.is_available() is True
    assert calls[0][0] == ["docker", "compose", "version"]
    assert calls[0][1]["shell"] is False
