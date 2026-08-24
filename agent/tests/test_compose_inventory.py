from datetime import datetime, timezone
from contextlib import closing
import sqlite3
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from conftest import (
    CONTAINER_A_ID,
    CONTAINER_B_ID,
    CONTAINER_C_ID,
    FakeDockerGateway,
    snapshot,
)
from nodeconductor_agent.api import create_app
from nodeconductor_agent.docker_gateway import _snapshot_from_attrs
from nodeconductor_agent.inventory_service import aggregate_compose_state
from nodeconductor_agent.models import ResourceMemberResponse
from nodeconductor_agent.policy_repository import PolicyRepository


OBSERVED_AT = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)


def _compose(container_id: str, name: str, service: str, **updates):
    item = snapshot(
        container_id,
        name,
        compose_classification="coherent",
        compose_project="n8n",
        compose_service=service,
    )
    return item.__class__(**{**item.__dict__, **updates})


def _policy_payload(policy: str) -> dict:
    return {
        "operation_id": str(uuid4()),
        "actor": "controller:test",
        "management_policy": policy,
    }


def test_typed_inventory_groups_compose_and_keeps_standalone(tmp_path) -> None:
    gateway = FakeDockerGateway(
        [
            _compose(CONTAINER_A_ID, "n8n-app-1", "app"),
            _compose(CONTAINER_B_ID, "n8n-db-1", "db"),
            snapshot(CONTAINER_C_ID, "standalone"),
        ]
    )
    client = TestClient(create_app(gateway, tmp_path / "typed.sqlite3"))

    response = client.get("/api/v2/resources?limit=10")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    project = next(
        item for item in body["items"]
        if item["target_kind"] == "compose_project"
    )
    standalone = next(
        item for item in body["items"]
        if item["target_kind"] == "standalone_container"
    )
    assert project["target"] == "n8n"
    assert project["state"] == "running"
    assert {member["compose_service"] for member in project["members"]} == {
        "app",
        "db",
    }
    assert {member["docker_id"] for member in project["members"]} == {
        CONTAINER_A_ID,
        CONTAINER_B_ID,
    }
    assert standalone["target"] == CONTAINER_C_ID
    assert standalone["members"] == []
    member_policy = client.put(
        f"/api/v1/containers/{CONTAINER_A_ID}/management-policy",
        json=_policy_payload("managed"),
    )
    assert member_policy.status_code == 409
    assert member_policy.json()["error"]["code"] == "resource_not_operable"
    client.close()


def test_ambiguous_compose_labels_are_visible_but_not_targets(tmp_path) -> None:
    ambiguous = snapshot(
        CONTAINER_A_ID,
        "ambiguous",
        compose_classification="ambiguous",
    )
    client = TestClient(
        create_app(
            FakeDockerGateway([ambiguous]), tmp_path / "ambiguous.sqlite3"
        )
    )

    response = client.get("/api/v2/resources")
    item = response.json()["items"][0]

    assert item["classification"] == "ambiguous"
    assert item["target_kind"] is None
    assert item["management_policy"] is None
    assert item["operable"] is False
    assert item["diagnostic_status"] == (
        "compose_labels_incomplete_or_invalid"
    )
    policy = client.put(
        (
            "/api/v2/resources/standalone_container/"
            f"{CONTAINER_A_ID}/management-policy"
        ),
        json=_policy_payload("managed"),
    )
    assert policy.status_code == 409
    assert policy.json()["error"]["code"] == "resource_not_operable"
    client.close()


def test_only_allowlisted_compose_labels_are_parsed() -> None:
    base = {
        "Id": CONTAINER_A_ID,
        "Name": "/n8n-app-1",
        "Created": "2026-08-23T08:00:00Z",
        "State": {"Status": "running"},
        "Config": {
            "Labels": {
                "com.docker.compose.project": "n8n",
                "com.docker.compose.service": "app",
                "com.docker.compose.project.working_dir": "C:/secret/path",
                "password": "top-secret",
            },
            "Env": ["TOKEN=secret"],
        },
        "Mounts": [{"Source": "C:/private"}],
    }

    coherent = _snapshot_from_attrs(base)
    incomplete = _snapshot_from_attrs(
        {
            **base,
            "Config": {
                "Labels": {"com.docker.compose.project": "n8n"}
            },
        }
    )
    contradictory = _snapshot_from_attrs(
        {
            **base,
            "Config": {
                "Labels": {
                    "com.docker.compose.project": "n8n",
                    "com.docker.compose.service": "../invalid",
                }
            },
        }
    )

    assert coherent.compose_classification == "coherent"
    assert coherent.compose_project == "n8n"
    assert coherent.compose_service == "app"
    assert incomplete.compose_classification == "ambiguous"
    assert contradictory.compose_classification == "ambiguous"
    serialized = repr((coherent, incomplete, contradictory))
    assert "secret" not in serialized
    assert "working_dir" not in serialized
    assert "C:/" not in serialized


def test_pagination_uses_an_immutable_agent_snapshot(tmp_path) -> None:
    gateway = FakeDockerGateway(
        [
            snapshot(CONTAINER_A_ID, "alpha"),
            snapshot(CONTAINER_B_ID, "beta"),
        ]
    )
    client = TestClient(create_app(gateway, tmp_path / "snapshot.sqlite3"))
    first = client.get("/api/v2/resources?limit=1&offset=0").json()
    del gateway.containers[CONTAINER_B_ID]

    second = client.get(
        "/api/v2/resources",
        params={
            "limit": 1,
            "offset": 1,
            "snapshot_id": first["snapshot_id"],
        },
    ).json()

    assert first["total"] == second["total"] == 2
    assert first["snapshot_observed_at"] == second["snapshot_observed_at"]
    assert second["items"][0]["target"] == CONTAINER_B_ID
    client.close()


@pytest.mark.parametrize(
    ("states", "health", "expected"),
    [
        (["exited", "created"], ["none", "none"], "stopped"),
        (["running", "restarting"], ["healthy", "starting"], "starting"),
        (["running", "running"], ["healthy", "healthy"], "running"),
        (["running", "running"], ["healthy", "unhealthy"], "degraded"),
        (["running", "exited"], ["healthy", "none"], "partial"),
        (["running", "unknown"], ["healthy", "unknown"], "unknown"),
    ],
)
def test_compose_state_aggregate_is_deterministic(
    states,
    health,
    expected,
) -> None:
    members = [
        ResourceMemberResponse(
            docker_id=character * 64,
            name=f"member-{index}",
            compose_service=f"service-{index}",
            state=state,
            health_status=health[index],
            last_observed_at=OBSERVED_AT,
        )
        for index, (character, state) in enumerate(zip("ab", states))
    ]

    assert aggregate_compose_state(members) == expected


def test_typed_policies_do_not_collide_and_legacy_policy_is_migrated(
    tmp_path,
) -> None:
    database = tmp_path / "agent.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        connection.executescript(
            """
            CREATE TABLE container_policies (
                container_id TEXT PRIMARY KEY,
                current_name TEXT NOT NULL,
                management_policy TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        connection.execute(
            """
            INSERT INTO container_policies
            VALUES (?, 'legacy', 'managed', ?, ?, ?)
            """,
            (CONTAINER_A_ID, OBSERVED_AT.isoformat(),
             OBSERVED_AT.isoformat(), OBSERVED_AT.isoformat()),
        )
        connection.commit()
    repository = PolicyRepository(database)

    assert repository.observe(
        "standalone_container", CONTAINER_A_ID, "legacy"
    ) == "managed"
    assert repository.observe(
        "compose_project", CONTAINER_A_ID, "project"
    ) == "discovered"


def test_configured_nodeconductor_target_is_forced_protected(tmp_path) -> None:
    gateway = FakeDockerGateway([snapshot(CONTAINER_A_ID, "controller")])
    app = create_app(
        gateway,
        tmp_path / "protected.sqlite3",
        protected_target_kind="standalone_container",
        protected_target=CONTAINER_A_ID,
    )
    with TestClient(app) as client:
        inventory = client.get("/api/v2/resources").json()
        assert inventory["protection_status"] == "protected"
        assert inventory["items"][0]["management_policy"] == "protected"
        assert inventory["items"][0]["protection_forced"] is True
        downgrade = client.put(
            (
                "/api/v2/resources/standalone_container/"
                f"{CONTAINER_A_ID}/management-policy"
            ),
            json=_policy_payload("managed"),
        )
        assert downgrade.status_code == 409
        assert downgrade.json()["error"]["code"] == "protected_resource"


def test_configured_compose_project_protects_the_whole_project(tmp_path) -> None:
    gateway = FakeDockerGateway(
        [
            _compose(CONTAINER_A_ID, "controller-1", "controller"),
            _compose(CONTAINER_B_ID, "database-1", "database"),
        ]
    )
    app = create_app(
        gateway,
        tmp_path / "protected-project.sqlite3",
        protected_target_kind="compose_project",
        protected_target="n8n",
    )

    with TestClient(app) as client:
        inventory = client.get("/api/v2/resources").json()

    project = inventory["items"][0]
    assert inventory["protection_status"] == "protected"
    assert project["target_kind"] == "compose_project"
    assert project["management_policy"] == "protected"
    assert project["protection_forced"] is True
    assert len(project["members"]) == 2


def test_configured_protection_absence_and_inconsistency_are_explicit(
    tmp_path,
) -> None:
    absent_app = create_app(
        FakeDockerGateway([]),
        tmp_path / "absent.sqlite3",
        protected_target_kind="standalone_container",
        protected_target=CONTAINER_A_ID,
    )
    member = _compose(CONTAINER_A_ID, "controller", "controller")
    inconsistent_app = create_app(
        FakeDockerGateway([member]),
        tmp_path / "inconsistent.sqlite3",
        protected_target_kind="standalone_container",
        protected_target=CONTAINER_A_ID,
    )

    with (
        TestClient(absent_app) as absent,
        TestClient(inconsistent_app) as inconsistent,
    ):
        assert absent.get("/api/v2/resources").json()[
            "protection_status"
        ] == "configured_absent"
        assert inconsistent.get("/api/v2/resources").json()[
            "protection_status"
        ] == "configured_inconsistent"
