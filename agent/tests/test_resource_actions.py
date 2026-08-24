from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import sqlite3
from threading import Barrier, Event
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from conftest import (
    CONTAINER_A_ID,
    CONTAINER_B_ID,
    FakeDockerGateway,
    snapshot,
)
from nodeconductor_agent.action_errors import (
    ActionConfirmedFailure,
    ActionIndeterminateError,
    ActionNotDispatchedError,
)
from nodeconductor_agent.action_repository import ActionRepository
from nodeconductor_agent.api import create_app
from nodeconductor_agent.compose_registry import (
    ComposeProjectDefinition,
    ComposeProjectRegistry,
)
from nodeconductor_agent.models import ResourceActionRequest


class FakeComposeRunner:
    def __init__(self, gateway, available=True) -> None:
        self.gateway = gateway
        self.available = available
        self.calls = []

    def is_available(self) -> bool:
        return self.available

    def execute(self, project, action) -> None:
        self.calls.append((project.project_name, action))
        desired = "running" if action == "start" else "exited"
        for container_id, container in list(self.gateway.containers.items()):
            if container.compose_project == project.project_name:
                self.gateway.containers[container_id] = replace(
                    container,
                    state=desired,
                )


def _registry(tmp_path: Path, project_name: str = "n8n"):
    directory = tmp_path / project_name
    directory.mkdir(exist_ok=True)
    compose_file = directory / "compose.yml"
    compose_file.write_text("services: {}\n", encoding="utf-8")
    return ComposeProjectRegistry(
        {
            project_name: ComposeProjectDefinition(
                project_name=project_name,
                working_directory=directory.resolve(),
                compose_files=(compose_file.resolve(),),
                stop_timeout_seconds=30,
            )
        }
    )


def _policy_payload(policy: str) -> dict:
    return {
        "operation_id": str(uuid4()),
        "actor": "controller:test",
        "management_policy": policy,
    }


def _action_payload(action: str, operation_id=None) -> dict:
    return {
        "operation_id": str(operation_id or uuid4()),
        "actor": "controller:test",
        "action": action,
    }


def _set_managed(client: TestClient, target_kind: str, target: str) -> None:
    response = client.put(
        f"/api/v2/resources/{target_kind}/{target}/management-policy",
        json=_policy_payload("managed"),
    )
    assert response.status_code == 200


def _action_endpoint(target_kind: str, target: str) -> str:
    return f"/api/v2/resources/{target_kind}/{target}/actions"


def test_standalone_start_and_stop_are_verified_and_bounded(tmp_path) -> None:
    gateway = FakeDockerGateway(
        [snapshot(CONTAINER_A_ID, "alpha", state="exited")]
    )
    client = TestClient(create_app(gateway, tmp_path / "agent.sqlite3"))
    _set_managed(client, "standalone_container", CONTAINER_A_ID)

    started = client.post(
        _action_endpoint("standalone_container", CONTAINER_A_ID),
        json=_action_payload("start"),
    )
    stopped = client.post(
        _action_endpoint("standalone_container", CONTAINER_A_ID),
        json=_action_payload("stop"),
    )

    assert started.status_code == 200
    assert started.json()["status"] == "completed"
    assert started.json()["resource"]["state"] == "running"
    assert stopped.json()["status"] == "completed"
    assert stopped.json()["resource"]["state"] == "exited"
    assert gateway.action_calls == [
        ("start", CONTAINER_A_ID),
        ("stop", CONTAINER_A_ID, 30),
    ]


def test_already_conforming_state_completes_without_dispatch(tmp_path) -> None:
    gateway = FakeDockerGateway([snapshot(CONTAINER_A_ID, "alpha")])
    client = TestClient(create_app(gateway, tmp_path / "agent.sqlite3"))
    _set_managed(client, "standalone_container", CONTAINER_A_ID)

    response = client.post(
        _action_endpoint("standalone_container", CONTAINER_A_ID),
        json=_action_payload("start"),
    )

    assert response.json()["status"] == "completed"
    assert response.json()["result_code"] == "already_in_desired_state"
    assert gateway.action_calls == []


def test_registered_compose_project_start_and_stop_use_whole_project(tmp_path) -> None:
    gateway = FakeDockerGateway(
        [
            snapshot(
                CONTAINER_A_ID,
                "n8n-app",
                compose_classification="coherent",
                compose_project="n8n",
                compose_service="app",
                state="exited",
            ),
            snapshot(
                CONTAINER_B_ID,
                "n8n-db",
                compose_classification="coherent",
                compose_project="n8n",
                compose_service="db",
                state="exited",
            ),
        ]
    )
    runner = FakeComposeRunner(gateway)
    client = TestClient(
        create_app(
            gateway,
            tmp_path / "agent.sqlite3",
            compose_registry=_registry(tmp_path),
            compose_runner=runner,
        )
    )
    _set_managed(client, "compose_project", "n8n")

    started = client.post(
        _action_endpoint("compose_project", "n8n"),
        json=_action_payload("start"),
    )
    stopped = client.post(
        _action_endpoint("compose_project", "n8n"),
        json=_action_payload("stop"),
    )

    assert started.json()["status"] == "completed"
    assert stopped.json()["status"] == "completed"
    assert runner.calls == [("n8n", "start"), ("n8n", "stop")]
    capabilities = client.get("/api/v1/capabilities").json()["capabilities"]
    assert "compose_start_stop" in capabilities
    assert not any("service" in call for call in runner.calls)


def test_discovered_compose_project_is_not_implicitly_authorized(tmp_path) -> None:
    gateway = FakeDockerGateway(
        [
            snapshot(
                CONTAINER_A_ID,
                "n8n-app",
                compose_classification="coherent",
                compose_project="n8n",
                compose_service="app",
                state="exited",
            )
        ]
    )
    runner = FakeComposeRunner(gateway)
    client = TestClient(
        create_app(
            gateway,
            tmp_path / "agent.sqlite3",
            compose_registry=_registry(tmp_path),
            compose_runner=runner,
        )
    )

    response = client.post(
        _action_endpoint("compose_project", "n8n"),
        json=_action_payload("start"),
    )

    assert response.json()["status"] == "rejected"
    assert response.json()["result_code"] == "management_policy_not_managed"
    assert runner.calls == []


def test_conforming_registered_compose_state_needs_no_runner_dispatch(tmp_path) -> None:
    gateway = FakeDockerGateway(
        [
            snapshot(
                CONTAINER_A_ID,
                "n8n-app",
                compose_classification="coherent",
                compose_project="n8n",
                compose_service="app",
                state="running",
            )
        ]
    )
    runner = FakeComposeRunner(gateway, available=False)
    client = TestClient(
        create_app(
            gateway,
            tmp_path / "agent.sqlite3",
            compose_registry=_registry(tmp_path),
            compose_runner=runner,
        )
    )
    _set_managed(client, "compose_project", "n8n")

    response = client.post(
        _action_endpoint("compose_project", "n8n"),
        json=_action_payload("start"),
    )

    assert response.json()["status"] == "completed"
    assert response.json()["result_code"] == "already_in_desired_state"
    assert runner.calls == []
    assert "compose_start_stop" not in client.get(
        "/api/v1/capabilities"
    ).json()["capabilities"]


def test_managed_but_unregistered_compose_project_is_rejected(tmp_path) -> None:
    gateway = FakeDockerGateway(
        [
            snapshot(
                CONTAINER_A_ID,
                "n8n-app",
                compose_classification="coherent",
                compose_project="n8n",
                compose_service="app",
                state="exited",
            )
        ]
    )
    runner = FakeComposeRunner(gateway)
    client = TestClient(
        create_app(
            gateway,
            tmp_path / "agent.sqlite3",
            compose_registry=ComposeProjectRegistry({}),
            compose_runner=runner,
        )
    )
    _set_managed(client, "compose_project", "n8n")

    response = client.post(
        _action_endpoint("compose_project", "n8n"),
        json=_action_payload("start"),
    )

    assert response.json()["status"] == "rejected"
    assert response.json()["result_code"] == "compose_project_not_registered"
    assert runner.calls == []
    assert "compose_start_stop" not in client.get(
        "/api/v1/capabilities"
    ).json()["capabilities"]


def test_invalid_compose_registry_fails_before_dispatch(tmp_path) -> None:
    gateway = FakeDockerGateway(
        [
            snapshot(
                CONTAINER_A_ID,
                "n8n-app",
                compose_classification="coherent",
                compose_project="n8n",
                compose_service="app",
                state="exited",
            )
        ]
    )
    runner = FakeComposeRunner(gateway)
    client = TestClient(
        create_app(
            gateway,
            tmp_path / "agent.sqlite3",
            compose_registry=ComposeProjectRegistry(usable=False),
            compose_runner=runner,
        )
    )
    _set_managed(client, "compose_project", "n8n")

    response = client.post(
        _action_endpoint("compose_project", "n8n"),
        json=_action_payload("start"),
    )

    assert response.json()["status"] == "failed"
    assert response.json()["result_code"] == "compose_registry_unavailable"
    assert runner.calls == []


def test_discovered_protected_and_forced_targets_are_rejected(tmp_path) -> None:
    discovered_gateway = FakeDockerGateway([snapshot(CONTAINER_A_ID, "alpha")])
    discovered = TestClient(
        create_app(discovered_gateway, tmp_path / "discovered.sqlite3")
    )
    response = discovered.post(
        _action_endpoint("standalone_container", CONTAINER_A_ID),
        json=_action_payload("stop"),
    )
    assert response.json()["result_code"] == "management_policy_not_managed"

    protected_gateway = FakeDockerGateway([snapshot(CONTAINER_A_ID, "alpha")])
    protected = TestClient(
        create_app(protected_gateway, tmp_path / "protected.sqlite3")
    )
    protected.put(
        f"/api/v2/resources/standalone_container/{CONTAINER_A_ID}/management-policy",
        json=_policy_payload("protected"),
    )
    response = protected.post(
        _action_endpoint("standalone_container", CONTAINER_A_ID),
        json=_action_payload("stop"),
    )
    assert response.json()["result_code"] == "protected_resource"

    forced_gateway = FakeDockerGateway([snapshot(CONTAINER_A_ID, "controller")])
    forced = TestClient(
        create_app(
            forced_gateway,
            tmp_path / "forced.sqlite3",
            protected_target_kind="standalone_container",
            protected_target=CONTAINER_A_ID,
        )
    )
    response = forced.post(
        _action_endpoint("standalone_container", CONTAINER_A_ID),
        json=_action_payload("stop"),
    )
    assert response.json()["result_code"] == "nodeconductor_target_protected"
    assert discovered_gateway.action_calls == []
    assert protected_gateway.action_calls == []
    assert forced_gateway.action_calls == []


def test_absent_ambiguous_and_compose_member_targets_are_rejected(tmp_path) -> None:
    absent_gateway = FakeDockerGateway([])
    absent = TestClient(create_app(absent_gateway, tmp_path / "absent.sqlite3"))
    response = absent.post(
        _action_endpoint("standalone_container", CONTAINER_A_ID),
        json=_action_payload("start"),
    )
    assert response.json()["result_code"] == "resource_not_found"

    ambiguous_gateway = FakeDockerGateway(
        [
            snapshot(
                CONTAINER_A_ID,
                "ambiguous",
                compose_classification="ambiguous",
                compose_project="n8n",
            )
        ]
    )
    ambiguous = TestClient(
        create_app(ambiguous_gateway, tmp_path / "ambiguous.sqlite3")
    )
    response = ambiguous.post(
        _action_endpoint("standalone_container", CONTAINER_A_ID),
        json=_action_payload("start"),
    )
    assert response.json()["result_code"] == "resource_not_pilotable"

    member_gateway = FakeDockerGateway(
        [
            snapshot(
                CONTAINER_A_ID,
                "n8n-app",
                compose_classification="coherent",
                compose_project="n8n",
                compose_service="app",
            )
        ]
    )
    member = TestClient(create_app(member_gateway, tmp_path / "member.sqlite3"))
    response = member.post(
        _action_endpoint("standalone_container", CONTAINER_A_ID),
        json=_action_payload("stop"),
    )
    assert response.json()["result_code"] == "resource_not_pilotable"
    assert member_gateway.action_calls == []


def test_action_request_and_typed_target_are_strictly_validated(tmp_path) -> None:
    gateway = FakeDockerGateway([snapshot(CONTAINER_A_ID, "alpha")])
    client = TestClient(create_app(gateway, tmp_path / "agent.sqlite3"))
    endpoint = _action_endpoint("standalone_container", CONTAINER_A_ID)

    unknown = client.post(
        endpoint,
        json={**_action_payload("start"), "command": "anything"},
    )
    unsupported = client.post(endpoint, json=_action_payload("restart"))
    invalid_operation = client.post(
        endpoint,
        json={**_action_payload("start"), "operation_id": "not-a-uuid"},
    )
    invalid_target = client.post(
        _action_endpoint("compose_project", "Invalid Project"),
        json=_action_payload("start"),
    )

    assert unknown.status_code == 422
    assert unsupported.status_code == 422
    assert invalid_operation.status_code == 422
    assert invalid_target.status_code == 422
    assert gateway.action_calls == []


def test_sequential_idempotence_and_operation_conflict(tmp_path) -> None:
    gateway = FakeDockerGateway(
        [snapshot(CONTAINER_A_ID, "alpha", state="exited")]
    )
    app = create_app(gateway, tmp_path / "agent.sqlite3")
    client = TestClient(app)
    _set_managed(client, "standalone_container", CONTAINER_A_ID)
    operation_id = uuid4()
    endpoint = _action_endpoint("standalone_container", CONTAINER_A_ID)

    first = client.post(endpoint, json=_action_payload("start", operation_id))
    replay = client.post(endpoint, json=_action_payload("start", operation_id))
    conflict = client.post(endpoint, json=_action_payload("stop", operation_id))

    assert first.json() == replay.json()
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "operation_id_conflict"
    assert gateway.action_calls == [("start", CONTAINER_A_ID)]
    assert len(app.state.action_repository.list_rows()) == 1


class BlockingGateway(FakeDockerGateway):
    def __init__(self, containers) -> None:
        super().__init__(containers)
        self.started = Event()
        self.release = Event()

    def start_container(self, container_id: str) -> None:
        self.started.set()
        assert self.release.wait(5)
        super().start_container(container_id)


def test_concurrent_identical_operation_dispatches_once(tmp_path) -> None:
    gateway = BlockingGateway(
        [snapshot(CONTAINER_A_ID, "alpha", state="exited")]
    )
    app = create_app(gateway, tmp_path / "agent.sqlite3")
    client = TestClient(app)
    _set_managed(client, "standalone_container", CONTAINER_A_ID)
    request = ResourceActionRequest(
        operation_id=uuid4(),
        actor="controller:test",
        action="start",
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            app.state.action_service.execute,
            "standalone_container",
            CONTAINER_A_ID,
            request,
        )
        assert gateway.started.wait(2)
        second = executor.submit(
            app.state.action_service.execute,
            "standalone_container",
            CONTAINER_A_ID,
            request,
        )
        gateway.release.set()
        results = [first.result(timeout=5), second.result(timeout=5)]

    assert results[0] == results[1]
    assert gateway.action_calls == [("start", CONTAINER_A_ID)]


def test_different_concurrent_action_on_same_resource_is_rejected(tmp_path) -> None:
    gateway = BlockingGateway(
        [snapshot(CONTAINER_A_ID, "alpha", state="exited")]
    )
    app = create_app(gateway, tmp_path / "agent.sqlite3")
    client = TestClient(app)
    _set_managed(client, "standalone_container", CONTAINER_A_ID)
    start_request = ResourceActionRequest(
        operation_id=uuid4(), actor="controller:test", action="start"
    )
    stop_request = ResourceActionRequest(
        operation_id=uuid4(), actor="controller:test", action="stop"
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        active = executor.submit(
            app.state.action_service.execute,
            "standalone_container",
            CONTAINER_A_ID,
            start_request,
        )
        assert gateway.started.wait(2)
        rejected = app.state.action_service.execute(
            "standalone_container", CONTAINER_A_ID, stop_request
        )
        gateway.release.set()
        assert active.result(timeout=5).status == "completed"

    assert rejected.status == "rejected"
    assert rejected.result_code == "resource_busy"
    assert gateway.action_calls == [("start", CONTAINER_A_ID)]


class ParallelGateway(FakeDockerGateway):
    def __init__(self, containers) -> None:
        super().__init__(containers)
        self.barrier = Barrier(2)

    def start_container(self, container_id: str) -> None:
        self.barrier.wait(timeout=5)
        super().start_container(container_id)


def test_different_resources_can_dispatch_in_parallel(tmp_path) -> None:
    gateway = ParallelGateway(
        [
            snapshot(CONTAINER_A_ID, "alpha", state="exited"),
            snapshot(CONTAINER_B_ID, "beta", state="exited"),
        ]
    )
    app = create_app(gateway, tmp_path / "agent.sqlite3")
    client = TestClient(app)
    _set_managed(client, "standalone_container", CONTAINER_A_ID)
    _set_managed(client, "standalone_container", CONTAINER_B_ID)

    def execute(target):
        return app.state.action_service.execute(
            "standalone_container",
            target,
            ResourceActionRequest(
                operation_id=uuid4(), actor="controller:test", action="start"
            ),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(execute, [CONTAINER_A_ID, CONTAINER_B_ID]))

    assert {result.status for result in results} == {"completed"}
    assert len(gateway.action_calls) == 2


class TimeoutGateway(FakeDockerGateway):
    def __init__(self, containers, after_dispatch: bool) -> None:
        super().__init__(containers)
        self.after_dispatch = after_dispatch

    def start_container(self, container_id: str) -> None:
        if self.after_dispatch:
            raise ActionIndeterminateError("local_timeout_after_dispatch")
        raise ActionNotDispatchedError("local_timeout_before_dispatch")


def test_timeouts_before_and_after_dispatch_are_classified(tmp_path) -> None:
    before_gateway = TimeoutGateway(
        [snapshot(CONTAINER_A_ID, "alpha", state="exited")],
        after_dispatch=False,
    )
    before_app = create_app(before_gateway, tmp_path / "before.sqlite3")
    before_client = TestClient(before_app)
    _set_managed(before_client, "standalone_container", CONTAINER_A_ID)
    before = before_client.post(
        _action_endpoint("standalone_container", CONTAINER_A_ID),
        json=_action_payload("start"),
    )

    after_gateway = TimeoutGateway(
        [snapshot(CONTAINER_A_ID, "alpha", state="exited")],
        after_dispatch=True,
    )
    after_app = create_app(after_gateway, tmp_path / "after.sqlite3")
    after_client = TestClient(after_app)
    _set_managed(after_client, "standalone_container", CONTAINER_A_ID)
    after = after_client.post(
        _action_endpoint("standalone_container", CONTAINER_A_ID),
        json=_action_payload("start"),
    )

    assert before.json()["status"] == "failed"
    assert before.json()["result_code"] == "local_timeout_before_dispatch"
    assert after.json()["status"] == "indeterminate"
    assert after.json()["result_code"] == "local_timeout_after_dispatch"


def test_incomplete_sqlite_operation_recovers_as_indeterminate_without_dispatch(
    tmp_path,
) -> None:
    database = tmp_path / "agent.sqlite3"
    ActionRepository(database)
    operation_id = str(uuid4())
    with closing(sqlite3.connect(database)) as connection:
        with connection:
            connection.execute(
                """
                INSERT INTO resource_action_operations (
                    operation_id, target_kind, target, actor, action,
                    status, dispatched, started_at
                ) VALUES (?, 'standalone_container', ?, 'controller:test',
                          'start', 'in_progress', 1, ?)
                """,
                (operation_id, CONTAINER_A_ID, "2026-08-24T08:00:00+00:00"),
            )
    gateway = FakeDockerGateway(
        [snapshot(CONTAINER_A_ID, "alpha", state="exited")]
    )
    app = create_app(gateway, database)

    result = app.state.action_service.execute(
        "standalone_container",
        CONTAINER_A_ID,
        ResourceActionRequest(
            operation_id=UUID(operation_id),
            actor="controller:test",
            action="start",
        ),
    )

    assert result.status == "indeterminate"
    assert result.result_code == "recovered_incomplete_operation"
    assert gateway.action_calls == []


class SecretFailureGateway(FakeDockerGateway):
    def start_container(self, container_id: str) -> None:
        try:
            raise RuntimeError("PASSWORD=secret /srv/private raw-output")
        except RuntimeError as error:
            raise ActionConfirmedFailure("container_start_failed") from error


def test_responses_and_sqlite_never_store_paths_or_raw_adapter_output(tmp_path) -> None:
    gateway = SecretFailureGateway(
        [snapshot(CONTAINER_A_ID, "alpha", state="exited")]
    )
    app = create_app(gateway, tmp_path / "agent.sqlite3")
    client = TestClient(app)
    _set_managed(client, "standalone_container", CONTAINER_A_ID)

    response = client.post(
        _action_endpoint("standalone_container", CONTAINER_A_ID),
        json=_action_payload("start"),
    )
    serialized_rows = repr(app.state.action_repository.list_rows())

    assert response.json()["status"] == "failed"
    assert set(response.json()) == {
        "operation_id",
        "actor",
        "action",
        "target_kind",
        "target",
        "status",
        "result_code",
        "message",
        "resource",
        "started_at",
        "finished_at",
    }
    for forbidden in ["PASSWORD", "/srv/private", "raw-output", "compose.yml"]:
        assert forbidden not in response.text
        assert forbidden not in serialized_rows


def test_sqlite_action_migration_creates_active_resource_guard(tmp_path) -> None:
    database = tmp_path / "agent.sqlite3"
    ActionRepository(database)

    with closing(sqlite3.connect(database)) as connection:
        table = connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name = 'resource_action_operations'
            """
        ).fetchone()
        index = connection.execute(
            """
            SELECT sql FROM sqlite_master
            WHERE type = 'index' AND name = 'one_active_action_per_resource'
            """
        ).fetchone()

    assert table == ("resource_action_operations",)
    assert "WHERE status = 'in_progress'" in index[0]
