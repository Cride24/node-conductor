from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
import sqlite3
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from conftest import (
    CONTAINER_A_ID,
    CONTAINER_B_ID,
    FakeDockerGateway,
    snapshot,
)
from nodeconductor_agent.api import create_app
from nodeconductor_agent import policy_repository
from nodeconductor_agent.policy_repository import PolicyRepository


def _policy_payload(policy: str, operation_id=None, actor="controller:test") -> dict:
    return {
        "operation_id": str(operation_id or uuid4()),
        "actor": actor,
        "management_policy": policy,
    }


def test_policy_update_is_idempotent_and_audited_once(
    tmp_path,
    fake_gateway,
) -> None:
    app = create_app(fake_gateway, tmp_path / "agent.sqlite3")
    client = TestClient(app)
    payload = _policy_payload("managed")
    endpoint = f"/api/v1/containers/{CONTAINER_A_ID}/management-policy"

    first = client.put(endpoint, json=payload)
    replay = client.put(endpoint, json=payload)

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["previous_policy"] == "discovered"
    assert first.json()["management_policy"] == "managed"
    audit = app.state.policy_repository.list_audit_rows()
    assert len(audit) == 1
    assert audit[0]["operation_id"] == payload["operation_id"]
    assert audit[0]["actor"] == "controller:test"


def test_operation_id_cannot_be_reused_for_another_request(
    tmp_path,
    fake_gateway,
) -> None:
    client = TestClient(create_app(fake_gateway, tmp_path / "agent.sqlite3"))
    operation_id = uuid4()
    endpoint = f"/api/v1/containers/{CONTAINER_A_ID}/management-policy"

    first = client.put(
        endpoint,
        json=_policy_payload("managed", operation_id),
    )
    conflict = client.put(
        endpoint,
        json=_policy_payload("protected", operation_id),
    )

    assert first.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "operation_id_conflict"


def test_replay_returns_initial_result_after_container_disappears(
    tmp_path,
    fake_gateway,
) -> None:
    app = create_app(fake_gateway, tmp_path / "agent.sqlite3")
    client = TestClient(app)
    payload = _policy_payload("protected")
    endpoint = f"/api/v1/containers/{CONTAINER_A_ID}/management-policy"
    first = client.put(endpoint, json=payload)
    del fake_gateway.containers[CONTAINER_A_ID]

    replay = client.put(endpoint, json=payload)

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert len(app.state.policy_repository.list_audit_rows()) == 1


def test_each_distinct_policy_request_is_audited(
    tmp_path,
    fake_gateway,
) -> None:
    app = create_app(fake_gateway, tmp_path / "agent.sqlite3")
    client = TestClient(app)
    endpoint = f"/api/v1/containers/{CONTAINER_A_ID}/management-policy"

    assert client.put(endpoint, json=_policy_payload("managed")).status_code == 200
    second = client.put(endpoint, json=_policy_payload("managed"))

    assert second.status_code == 200
    assert second.json()["previous_policy"] == "managed"
    assert len(app.state.policy_repository.list_audit_rows()) == 2


def test_missing_container_policy_is_refused_without_audit(
    tmp_path,
    fake_gateway,
) -> None:
    app = create_app(fake_gateway, tmp_path / "agent.sqlite3")
    client = TestClient(app)

    response = client.put(
        f"/api/v1/containers/{'f' * 64}/management-policy",
        json=_policy_payload("managed"),
    )

    assert response.status_code == 404
    assert app.state.policy_repository.list_audit_rows() == []


def test_same_container_id_keeps_policy_after_rename(tmp_path) -> None:
    gateway = FakeDockerGateway([snapshot(CONTAINER_A_ID, "old-name")])
    client = TestClient(create_app(gateway, tmp_path / "agent.sqlite3"))
    endpoint = f"/api/v1/containers/{CONTAINER_A_ID}/management-policy"
    client.put(endpoint, json=_policy_payload("protected"))
    gateway.containers[CONTAINER_A_ID] = snapshot(CONTAINER_A_ID, "new-name")

    response = client.get(f"/api/v1/containers/{CONTAINER_A_ID}")

    assert response.status_code == 200
    assert response.json()["name"] == "new-name"
    assert response.json()["management_policy"] == "protected"


def test_replacement_with_same_name_is_discovered(tmp_path) -> None:
    gateway = FakeDockerGateway([snapshot(CONTAINER_A_ID, "reused-name")])
    client = TestClient(create_app(gateway, tmp_path / "agent.sqlite3"))
    endpoint = f"/api/v1/containers/{CONTAINER_A_ID}/management-policy"
    client.put(endpoint, json=_policy_payload("managed"))
    del gateway.containers[CONTAINER_A_ID]
    gateway.containers[CONTAINER_B_ID] = snapshot(
        CONTAINER_B_ID,
        "reused-name",
    )

    response = client.get(f"/api/v1/containers/{CONTAINER_B_ID}")

    assert response.status_code == 200
    assert response.json()["name"] == "reused-name"
    assert response.json()["management_policy"] == "discovered"


def test_policy_request_rejects_unknown_fields(tmp_path, fake_gateway) -> None:
    client = TestClient(create_app(fake_gateway, tmp_path / "agent.sqlite3"))
    payload = {**_policy_payload("managed"), "authorized": True}

    response = client.put(
        f"/api/v1/containers/{CONTAINER_A_ID}/management-policy",
        json=payload,
    )

    assert response.status_code == 422


def test_concurrent_replay_creates_one_audit_row(tmp_path) -> None:
    repository = PolicyRepository(tmp_path / "agent.sqlite3")
    operation_id = str(uuid4())
    barrier = Barrier(2)

    def update_policy():
        barrier.wait()
        return repository.set_policy(
            "standalone_container",
            CONTAINER_A_ID,
            "alpha",
            "managed",
            operation_id,
            "controller:test",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: update_policy(), range(2)))

    assert results[0] == results[1]
    assert len(repository.list_audit_rows()) == 1


def test_repository_closes_every_sqlite_connection(monkeypatch, tmp_path) -> None:
    real_connect = sqlite3.connect
    opened_connections = []

    def tracked_connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        opened_connections.append(connection)
        return connection

    monkeypatch.setattr(policy_repository.sqlite3, "connect", tracked_connect)
    repository = PolicyRepository(tmp_path / "agent.sqlite3")
    repository.observe("standalone_container", CONTAINER_A_ID, "alpha")
    operation_id = str(uuid4())
    repository.set_policy(
        "standalone_container",
        CONTAINER_A_ID,
        "alpha",
        "managed",
        operation_id,
        "controller:test",
    )
    repository.replay_operation(
        operation_id,
        "standalone_container",
        CONTAINER_A_ID,
        "managed",
        "controller:test",
    )
    repository.list_audit_rows()

    assert len(opened_connections) == 5
    for connection in opened_connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            connection.execute("SELECT 1")
