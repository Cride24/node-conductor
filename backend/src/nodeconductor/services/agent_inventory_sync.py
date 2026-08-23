"""Validation et synchronisation read-only d'un inventaire Agent complet."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from nodeconductor.core.config import settings
from nodeconductor.repositories.agent_inventory_repository import (
    synchronize_inventory_rows,
)
from nodeconductor.repositories.worker_contracts_repository import (
    fetch_agent_connection_row,
)
from nodeconductor.services.agent_client import (
    AgentClient,
    AgentClientConfigurationError,
    AgentCredentialResolver,
    AgentResponseInvalidError,
    AgentUnavailableError,
    EnvironmentCredentialResolver,
    HttpAgentClient,
    build_http_agent_client,
)
from nodeconductor.services.events import record_event


EXPECTED_AGENT_API_VERSION = "v1"
REQUIRED_CAPABILITIES = {"container_list"}


@dataclass(frozen=True)
class AgentInventorySyncResult:
    status: Literal["synchronized", "unavailable", "rejected"]
    connection_id: str
    agent_id: str
    pages: int = 0
    total_count: int = 0
    created_count: int = 0
    updated_count: int = 0
    absent_count: int = 0
    error_code: str | None = None


class AgentConnectionMissingError(Exception):
    pass


def synchronize_agent_inventory(
    connection_id: str,
    client: AgentClient | None = None,
    credential_resolver: AgentCredentialResolver | None = None,
    observed_at: datetime | None = None,
) -> AgentInventorySyncResult:
    connection = fetch_agent_connection_row(connection_id)
    if connection is None:
        raise AgentConnectionMissingError(connection_id)
    owned_client = None
    try:
        if client is None:
            owned_client = _build_client(connection, credential_resolver)
            client = owned_client
        health = client.health()
        capabilities = client.capabilities()
        _validate_agent_contract(connection, health, capabilities)
        containers, pages = _fetch_complete_inventory(client)
        sync = synchronize_inventory_rows(
            connection_id,
            [container.model_dump(mode="python") for container in containers],
            observed_at or datetime.now(timezone.utc),
        )
    except AgentUnavailableError as error:
        return _record_failure(connection, "unavailable", error.code)
    except (AgentResponseInvalidError, AgentClientConfigurationError) as error:
        return _record_failure(connection, "rejected", error.code)
    finally:
        if owned_client is not None:
            owned_client.close()
    _record_success(connection, sync, pages)
    return AgentInventorySyncResult(
        status="synchronized",
        connection_id=connection_id,
        agent_id=connection["agent_id"],
        pages=pages,
        total_count=sync["total_count"],
        created_count=sync["created_count"],
        updated_count=sync["updated_count"],
        absent_count=sync["absent_count"],
    )


def _build_client(
    connection: dict,
    resolver: AgentCredentialResolver | None,
) -> HttpAgentClient:
    return build_http_agent_client(
        connection,
        resolver or EnvironmentCredentialResolver(),
        settings.agent_connect_timeout_seconds,
        settings.agent_response_timeout_seconds,
        settings.agent_max_response_bytes,
    )


def _validate_agent_contract(connection, health, capabilities) -> None:
    expected_agent_id = connection["agent_id"]
    if health.agent_id != expected_agent_id:
        raise AgentResponseInvalidError("agent_identity_mismatch")
    if capabilities.agent_id != expected_agent_id:
        raise AgentResponseInvalidError("agent_identity_mismatch")
    if health.agent_version != capabilities.agent_version:
        raise AgentResponseInvalidError("agent_version_mismatch")
    if capabilities.api_version != EXPECTED_AGENT_API_VERSION:
        raise AgentResponseInvalidError("agent_api_version_unsupported")
    if not REQUIRED_CAPABILITIES.issubset(capabilities.capabilities):
        raise AgentResponseInvalidError("agent_capability_missing")
    if health.status != "ready" or health.engine_status != "available":
        raise AgentUnavailableError("engine_unavailable")
    if not capabilities.engine_available:
        raise AgentUnavailableError("engine_unavailable")


def _fetch_complete_inventory(client: AgentClient):
    page_size = settings.agent_sync_page_size
    max_pages = settings.agent_sync_max_pages
    containers = []
    seen_ids: set[str] = set()
    expected_total = None
    offset = 0
    for page_number in range(1, max_pages + 1):
        page = client.list_containers(page_size, offset)
        _validate_page(page, page_size, offset, expected_total)
        expected_total = page.total
        for container in page.items:
            if container.id in seen_ids:
                raise AgentResponseInvalidError("agent_inventory_duplicate")
            seen_ids.add(container.id)
            containers.append(container)
        if len(containers) == expected_total:
            return containers, page_number
        offset = len(containers)
    raise AgentResponseInvalidError("agent_inventory_incomplete")


def _validate_page(page, page_size, offset, expected_total) -> None:
    if page.limit != page_size or page.offset != offset:
        raise AgentResponseInvalidError("agent_pagination_invalid")
    if expected_total is not None and page.total != expected_total:
        raise AgentResponseInvalidError("agent_pagination_changed")
    if page.total > page_size * settings.agent_sync_max_pages:
        raise AgentResponseInvalidError("agent_inventory_too_large")
    remaining = max(page.total - offset, 0)
    if len(page.items) != min(page_size, remaining):
        raise AgentResponseInvalidError("agent_pagination_incomplete")


def _record_failure(connection: dict, status: str, error_code: str):
    event_type = (
        "agent.inventory_unavailable"
        if status == "unavailable"
        else "agent.inventory_rejected"
    )
    record_event(
        event_type=event_type,
        severity="warning",
        message="Agent inventory synchronization was not applied",
        actor_type="system",
        actor_id=connection["agent_id"],
        details={
            "connection_id": connection["id"],
            "expected_agent_id": connection["agent_id"],
            "reason": error_code,
        },
    )
    return AgentInventorySyncResult(
        status=status,
        connection_id=connection["id"],
        agent_id=connection["agent_id"],
        error_code=error_code,
    )


def _record_success(connection: dict, sync: dict, pages: int) -> None:
    for target in sync["discovered"]:
        record_event(
            event_type="target.discovered",
            severity="info",
            message="Docker target discovered",
            actor_type="system",
            actor_id=connection["agent_id"],
            details={
                "connection_id": connection["id"],
                "target_id": target["id"],
                "docker_id": target["target"],
                "display_name": target["display_name"],
                "management_policy": target["management_policy"],
            },
        )
    record_event(
        event_type="agent.inventory_synchronized",
        severity="info",
        message="Agent inventory synchronized",
        actor_type="system",
        actor_id=connection["agent_id"],
        details={
            "connection_id": connection["id"],
            "pages": pages,
            "total_count": sync["total_count"],
            "created_count": sync["created_count"],
            "updated_count": sync["updated_count"],
            "absent_count": sync["absent_count"],
        },
    )
