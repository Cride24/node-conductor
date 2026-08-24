from datetime import datetime, timezone
from uuid import uuid4

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from nodeconductor.core.config import settings
from nodeconductor.main import app
from nodeconductor.repositories.agent_inventory_repository import (
    fetch_compose_member_rows,
    fetch_inventory_issue_rows,
    fetch_inventory_target_rows,
)
from nodeconductor.repositories.events_repository import fetch_events
from nodeconductor.repositories.services_repository import _connect, reset_rows
from nodeconductor.repositories.worker_contracts_repository import (
    create_service_target_binding_row,
    create_target_row,
    create_agent_connection_row,
    fetch_agent_connection_row,
    update_target_management_policy_row,
)
from nodeconductor.schemas.agent_api import (
    AgentCapabilities,
    AgentHealth,
    AgentResource,
    AgentResourceMember,
    AgentResourcePage,
)
from nodeconductor.services.agent_client import (
    AgentUnavailableError,
    HttpAgentClient,
)
from nodeconductor.services.agent_inventory_sync import (
    synchronize_agent_inventory,
)


API_CLIENT = TestClient(app)
CONTAINER_A = "a" * 64
CONTAINER_B = "b" * 64
CONTAINER_C = "c" * 64
OBSERVED_AT = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)


def setup_function() -> None:
    reset_rows()


def _create_connection(**overrides) -> dict:
    payload = {
        "id": "docker-main",
        "agent_id": "agent-main",
        "description": "Agent Docker principal",
        "transport": "unix_socket",
        "endpoint": "/run/nodeconductor-agent/agent.sock",
        **overrides,
    }
    return create_agent_connection_row(payload)


def _container(container_id: str, name: str, policy="discovered"):
    return AgentResource(
        classification="operational",
        target_kind="standalone_container",
        target=container_id,
        display_name=name,
        state="running",
        health_status="healthy",
        management_policy=policy,
        operable=True,
        protection_forced=False,
        diagnostic_status=None,
        members=[],
    )


def _member(container_id: str, name: str, service: str):
    return AgentResourceMember(
        docker_id=container_id,
        name=name,
        compose_service=service,
        state="running",
        health_status="healthy",
        is_present=True,
        last_observed_at=OBSERVED_AT,
    )


def _project(name: str, members, policy="discovered", forced=False):
    return AgentResource(
        classification="operational",
        target_kind="compose_project",
        target=name,
        display_name=name,
        state="running",
        health_status="healthy",
        management_policy=policy,
        operable=True,
        protection_forced=forced,
        diagnostic_status=None,
        members=members,
    )


def _ambiguous(container_id: str, name: str):
    return AgentResource(
        classification="ambiguous",
        target_kind=None,
        target=container_id,
        display_name=name,
        state="running",
        health_status="none",
        management_policy=None,
        operable=False,
        protection_forced=False,
        diagnostic_status="compose_labels_incomplete_or_invalid",
        members=[],
    )


class FakeAgentClient:
    def __init__(
        self,
        containers,
        agent_id="agent-main",
        fail_offset=None,
        invalid_offset=False,
        api_version="v2",
        capabilities=None,
    ) -> None:
        self.containers = containers
        self.agent_id = agent_id
        self.fail_offset = fail_offset
        self.invalid_offset = invalid_offset
        self.api_version = api_version
        self.available_capabilities = capabilities or [
            "health",
            "capabilities",
            "resource_inventory_v1",
        ]
        self.snapshot_id = uuid4()

    def health(self) -> AgentHealth:
        return AgentHealth(
            agent_id=self.agent_id,
            status="ready",
            agent_version="0.1.0",
            engine_status="available",
        )

    def capabilities(self) -> AgentCapabilities:
        return AgentCapabilities(
            agent_id=self.agent_id,
            agent_version="0.1.0",
            api_version=self.api_version,
            engine_available=True,
            engine_version="27.1.1",
            docker_api_version="1.46",
            capabilities=self.available_capabilities,
        )

    def list_resources(
        self,
        limit: int,
        offset: int,
        timeout_seconds=None,
        snapshot_id=None,
    ) -> AgentResourcePage:
        if offset == self.fail_offset:
            raise AgentUnavailableError("agent_unavailable")
        return AgentResourcePage(
            items=self.containers[offset : offset + limit],
            limit=limit,
            offset=offset + 1 if self.invalid_offset else offset,
            total=len(self.containers),
            snapshot_id=self.snapshot_id,
            snapshot_observed_at=OBSERVED_AT,
            protection_status="not_configured",
        )


def test_complete_pagination_creates_canonical_targets_and_events(
    monkeypatch,
) -> None:
    _create_connection()
    monkeypatch.setattr(settings, "agent_sync_page_size", 2)
    monkeypatch.setattr(settings, "agent_sync_max_pages", 3)
    client = FakeAgentClient(
        [
            _container(CONTAINER_A, "alpha"),
            _container(CONTAINER_B, "beta"),
            _container(CONTAINER_C, "gamma"),
        ]
    )

    result = synchronize_agent_inventory(
        "docker-main",
        client=client,
        observed_at=OBSERVED_AT,
    )

    assert result.status == "synchronized"
    assert result.pages == 2
    assert result.created_count == 3
    rows = fetch_inventory_target_rows("docker-main")
    assert [row["target"] for row in rows] == [
        CONTAINER_A,
        CONTAINER_B,
        CONTAINER_C,
    ]
    assert all(row["is_present"] for row in rows)
    assert rows[0]["display_name"] == "alpha"
    assert rows[0]["observed_state"] == "running"
    assert rows[0]["observed_health_status"] == "healthy"
    assert rows[0]["last_seen_at"] == OBSERVED_AT
    event_types = [event["event_type"] for event in fetch_events(limit=20)]
    assert event_types.count("target.discovered") == 3
    assert event_types.count("agent.inventory_synchronized") == 1


def test_repeated_sync_is_idempotent_and_agent_policy_is_authoritative() -> None:
    _create_connection()
    first_client = FakeAgentClient([_container(CONTAINER_A, "old-name")])
    synchronize_agent_inventory(
        "docker-main",
        client=first_client,
        observed_at=OBSERVED_AT,
    )
    changed = _container(CONTAINER_A, "new-name", policy="protected")
    changed = changed.model_copy(
        update={"state": "exited", "health_status": "none"}
    )

    result = synchronize_agent_inventory(
        "docker-main",
        client=FakeAgentClient([changed]),
        observed_at=OBSERVED_AT,
    )

    assert result.created_count == 0
    assert result.updated_count == 1
    rows = fetch_inventory_target_rows("docker-main")
    assert len(rows) == 1
    assert rows[0]["display_name"] == "new-name"
    assert rows[0]["management_policy"] == "protected"
    assert rows[0]["observed_state"] == "exited"
    events = fetch_events(limit=20)
    assert sum(event["event_type"] == "target.discovered" for event in events) == 1


def test_complete_sync_marks_disappeared_target_absent() -> None:
    _create_connection()
    synchronize_agent_inventory(
        "docker-main",
        client=FakeAgentClient(
            [_container(CONTAINER_A, "alpha"), _container(CONTAINER_B, "beta")]
        ),
        observed_at=OBSERVED_AT,
    )

    result = synchronize_agent_inventory(
        "docker-main",
        client=FakeAgentClient([_container(CONTAINER_A, "alpha")]),
        observed_at=OBSERVED_AT,
    )

    assert result.absent_count == 1
    rows = fetch_inventory_target_rows("docker-main")
    assert rows[0]["is_present"] is True
    assert rows[1]["is_present"] is False


def test_complete_empty_sync_marks_every_target_absent() -> None:
    _create_connection()
    synchronize_agent_inventory(
        "docker-main",
        client=FakeAgentClient([_container(CONTAINER_A, "alpha")]),
        observed_at=OBSERVED_AT,
    )

    result = synchronize_agent_inventory(
        "docker-main",
        client=FakeAgentClient([]),
        observed_at=OBSERVED_AT,
    )

    assert result.status == "synchronized"
    assert result.total_count == 0
    assert result.absent_count == 1
    rows = fetch_inventory_target_rows("docker-main")
    assert len(rows) == 1
    assert rows[0]["is_present"] is False
    assert rows[0]["last_seen_at"] == OBSERVED_AT


def test_partial_pagination_keeps_previous_inventory(monkeypatch) -> None:
    _create_connection()
    monkeypatch.setattr(settings, "agent_sync_page_size", 2)
    monkeypatch.setattr(settings, "agent_sync_max_pages", 3)
    initial = [_container(CONTAINER_A, "alpha"), _container(CONTAINER_B, "beta")]
    synchronize_agent_inventory(
        "docker-main",
        client=FakeAgentClient(initial),
        observed_at=OBSERVED_AT,
    )
    partial = FakeAgentClient(
        initial + [_container(CONTAINER_C, "gamma")],
        fail_offset=2,
    )

    result = synchronize_agent_inventory("docker-main", client=partial)

    assert result.status == "unavailable"
    rows = fetch_inventory_target_rows("docker-main")
    assert len(rows) == 2
    assert all(row["is_present"] for row in rows)
    assert all(row["last_seen_at"] == OBSERVED_AT for row in rows)


def test_wrong_identity_and_invalid_page_never_apply_inventory() -> None:
    _create_connection()

    identity = synchronize_agent_inventory(
        "docker-main",
        client=FakeAgentClient(
            [_container(CONTAINER_A, "alpha")],
            agent_id="unexpected-agent",
        ),
    )
    invalid_page = synchronize_agent_inventory(
        "docker-main",
        client=FakeAgentClient(
            [_container(CONTAINER_A, "alpha")],
            invalid_offset=True,
        ),
    )

    assert identity.status == "rejected"
    assert identity.error_code == "agent_identity_mismatch"
    assert invalid_page.status == "rejected"
    assert invalid_page.error_code == "agent_pagination_invalid"
    assert fetch_inventory_target_rows("docker-main") == []


def test_api_version_and_capabilities_are_checked_before_inventory() -> None:
    _create_connection()

    wrong_version = synchronize_agent_inventory(
        "docker-main",
        client=FakeAgentClient(
            [_container(CONTAINER_A, "alpha")],
            api_version="v1",
        ),
    )
    missing_capability = synchronize_agent_inventory(
        "docker-main",
        client=FakeAgentClient(
            [_container(CONTAINER_A, "alpha")],
            capabilities=["health", "capabilities"],
        ),
    )

    assert wrong_version.error_code == "agent_api_version_unsupported"
    assert missing_capability.error_code == "agent_capability_missing"
    assert fetch_inventory_target_rows("docker-main") == []


def test_unavailable_agent_preserves_inventory_and_hides_remote_secrets() -> None:
    _create_connection()
    synchronize_agent_inventory(
        "docker-main",
        client=FakeAgentClient([_container(CONTAINER_A, "alpha")]),
        observed_at=OBSERVED_AT,
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            500,
            text="token=top-secret C:/certificates/client.key",
        )
    )
    raw_client = httpx.Client(
        base_url="http://agent.test",
        transport=transport,
        trust_env=False,
    )
    client = HttpAgentClient(raw_client, max_response_bytes=4096)

    result = synchronize_agent_inventory("docker-main", client=client)
    response = API_CLIENT.get("/api/v1/events", params={"limit": 20})
    client.close()

    assert result.status == "unavailable"
    assert fetch_inventory_target_rows("docker-main")[0]["is_present"] is True
    assert response.status_code == 200
    assert "top-secret" not in response.text
    assert "client.key" not in response.text
    assert "credential_ref" not in response.text


def test_postgresql_stores_only_credential_reference() -> None:
    row = _create_connection(
        transport="https",
        endpoint="https://agent.example.test:8443",
        credential_ref="docker-main-mtls",
    )

    stored = fetch_agent_connection_row(row["id"])

    assert stored["credential_ref"] == "docker-main-mtls"
    assert set(stored) == {
        "id",
        "agent_id",
        "description",
        "transport",
        "endpoint",
        "default_management_policy",
        "credential_ref",
    }
    assert all("certificate" not in key for key in stored)


def test_compose_project_members_and_diagnostic_issues_are_persisted() -> None:
    _create_connection()
    project = _project(
        "n8n",
        [
            _member(CONTAINER_A, "n8n-app-1", "app"),
            _member(CONTAINER_B, "n8n-db-1", "db"),
        ],
    )

    result = synchronize_agent_inventory(
        "docker-main",
        client=FakeAgentClient(
            [project, _container(CONTAINER_C, "standalone")]
        ),
        observed_at=OBSERVED_AT,
    )

    assert result.status == "synchronized"
    assert result.member_count == 2
    targets = fetch_inventory_target_rows("docker-main")
    assert {
        (row["target_kind"], row["target"]) for row in targets
    } == {
        ("compose_project", "n8n"),
        ("standalone_container", CONTAINER_C),
    }
    members = fetch_compose_member_rows("docker-main")
    assert {row["docker_id"] for row in members} == {
        CONTAINER_A,
        CONTAINER_B,
    }
    assert all(row["is_present"] for row in members)

    issue_result = synchronize_agent_inventory(
        "docker-main",
        client=FakeAgentClient([_ambiguous(CONTAINER_A, "ambiguous")]),
        observed_at=OBSERVED_AT,
    )
    issues = fetch_inventory_issue_rows("docker-main")
    assert issue_result.issue_count == 1
    assert issues[0]["docker_id"] == CONTAINER_A
    assert issues[0]["diagnostic_status"] == (
        "compose_labels_incomplete_or_invalid"
    )
    assert all(
        not row["is_present"]
        for row in fetch_inventory_target_rows("docker-main")
    )


def test_member_and_project_disappearance_are_tracked_separately() -> None:
    _create_connection()
    synchronize_agent_inventory(
        "docker-main",
        client=FakeAgentClient(
            [
                _project(
                    "n8n",
                    [
                        _member(CONTAINER_A, "n8n-app-1", "app"),
                        _member(CONTAINER_B, "n8n-db-1", "db"),
                    ],
                )
            ]
        ),
        observed_at=OBSERVED_AT,
    )

    one_missing = synchronize_agent_inventory(
        "docker-main",
        client=FakeAgentClient(
            [
                _project(
                    "n8n",
                    [_member(CONTAINER_A, "n8n-app-1", "app")],
                )
            ]
        ),
        observed_at=OBSERVED_AT,
    )
    members = fetch_compose_member_rows("docker-main")
    assert one_missing.member_absent_count == 1
    assert [row["is_present"] for row in members] == [True, False]

    synchronize_agent_inventory(
        "docker-main",
        client=FakeAgentClient([]),
        observed_at=OBSERVED_AT,
    )
    assert fetch_inventory_target_rows("docker-main")[0]["is_present"] is False
    assert all(
        not row["is_present"]
        for row in fetch_compose_member_rows("docker-main")
    )


def test_legacy_container_member_is_preserved_but_cannot_receive_jobs() -> None:
    _create_connection()
    legacy = create_target_row(
        {
            "driver": "docker",
            "connection_id": "docker-main",
            "target": CONTAINER_A,
        }
    )
    update_target_management_policy_row(legacy["id"], "managed")
    create_service_target_binding_row(
        {
            "service_id": 1,
            "target_id": legacy["id"],
            "readiness_check": "docker_state",
        }
    )

    synchronize_agent_inventory(
        "docker-main",
        client=FakeAgentClient(
            [
                _project(
                    "n8n",
                    [_member(CONTAINER_A, "n8n-app-1", "app")],
                )
            ]
        ),
        observed_at=OBSERVED_AT,
    )

    rows = fetch_inventory_target_rows("docker-main")
    legacy_after = next(
        row for row in rows
        if row["target_kind"] == "standalone_container"
    )
    assert legacy_after["id"] == legacy["id"]
    assert legacy_after["management_policy"] == "managed"
    assert legacy_after["is_pilotable"] is False
    assert legacy_after["is_present"] is False
    response = API_CLIENT.post("/api/v1/services/1/start", json={})
    assert response.status_code == 409
    assert "not pilotable" in response.json()["detail"]


def test_forced_protection_cannot_be_removed_by_controller_repository() -> None:
    _create_connection()
    protected = _container(CONTAINER_A, "controller", policy="protected")
    protected = protected.model_copy(update={"protection_forced": True})
    synchronize_agent_inventory(
        "docker-main",
        client=FakeAgentClient([protected]),
        observed_at=OBSERVED_AT,
    )
    target = fetch_inventory_target_rows("docker-main")[0]

    updated = update_target_management_policy_row(target["id"], "managed")

    assert updated is None
    stored = fetch_inventory_target_rows("docker-main")[0]
    assert stored["management_policy"] == "protected"
    assert stored["protection_forced"] is True

    with pytest.raises(psycopg.errors.CheckViolation):
        with _connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE targets
                    SET protection_forced = FALSE
                    WHERE id = %s
                    """,
                    (target["id"],),
                )


def test_member_cannot_also_be_exposed_as_standalone_target() -> None:
    _create_connection()
    client = FakeAgentClient(
        [
            _project(
                "n8n",
                [_member(CONTAINER_A, "n8n-app-1", "app")],
            ),
            _container(CONTAINER_A, "incorrect-standalone"),
        ]
    )

    result = synchronize_agent_inventory("docker-main", client=client)

    assert result.status == "rejected"
    assert result.error_code == "agent_member_exposed_as_target"
    assert fetch_inventory_target_rows("docker-main") == []
