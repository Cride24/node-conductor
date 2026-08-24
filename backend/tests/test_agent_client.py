from pathlib import Path
from uuid import UUID

import httpx
import pytest

from nodeconductor.services import agent_client
from nodeconductor.services.agent_client import (
    AgentClientConfigurationError,
    AgentResponseInvalidError,
    AgentTLSCredentials,
    AgentUnavailableError,
    HttpAgentClient,
)


def _client(handler, max_response_bytes: int = 4096) -> HttpAgentClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(
        base_url="http://agent.test",
        transport=transport,
        trust_env=False,
    )
    return HttpAgentClient(http_client, max_response_bytes)


def test_mock_transport_reads_valid_agent_contracts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/health"):
            return httpx.Response(
                200,
                json={
                    "agent_id": "agent-main",
                    "status": "ready",
                    "agent_version": "0.1.0",
                    "engine_status": "available",
                },
            )
        return httpx.Response(
            200,
            json={
                "agent_id": "agent-main",
                "agent_version": "0.1.0",
                "api_version": "v1",
                "engine_available": True,
                "engine_version": "27.1.1",
                "docker_api_version": "1.46",
                "capabilities": ["container_list"],
            },
        )

    client = _client(handler)

    assert client.health().agent_id == "agent-main"
    assert client.capabilities().api_version == "v1"
    client.close()


def test_typed_resource_client_reuses_snapshot_identifier() -> None:
    snapshot_id = UUID("018f4db8-6d79-7fc1-a921-4ec37e97fb14")
    requested = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append((request.url.path, dict(request.url.params)))
        return httpx.Response(
            200,
            json={
                "items": [],
                "limit": 50,
                "offset": 50,
                "total": 50,
                "snapshot_id": str(snapshot_id),
                "snapshot_observed_at": "2026-08-23T12:00:00Z",
                "protection_status": "not_configured",
            },
        )

    client = _client(handler)
    page = client.list_resources(50, 50, snapshot_id=snapshot_id)
    client.close()

    assert page.snapshot_id == snapshot_id
    assert requested == [
        (
            "/api/v2/resources",
            {
                "limit": "50",
                "offset": "50",
                "snapshot_id": str(snapshot_id),
            },
        )
    ]


def test_request_timeout_is_bounded_by_client_limits_and_remaining_time() -> None:
    received_timeouts = []

    def handler(request: httpx.Request) -> httpx.Response:
        received_timeouts.append(request.extensions["timeout"])
        return httpx.Response(
            200,
            json={
                "agent_id": "agent-main",
                "status": "ready",
                "agent_version": "0.1.0",
                "engine_status": "available",
            },
        )

    transport = httpx.MockTransport(
        handler
    )
    raw_client = httpx.Client(
        base_url="http://agent.test",
        transport=transport,
        trust_env=False,
    )
    client = HttpAgentClient(
        raw_client,
        max_response_bytes=4096,
        connect_timeout_seconds=2,
        response_timeout_seconds=5,
    )

    short = client._bounded_timeout(0.25)
    long = client._bounded_timeout(10)

    assert short.connect == 0.25
    assert short.read == 0.25
    assert short.write == 0.25
    assert short.pool == 0.25
    assert long.connect == 2
    assert long.read == 5
    assert long.write == 5
    assert long.pool == 2
    assert client.health(timeout_seconds=0.25).status == "ready"
    assert received_timeouts == [
        {"connect": 0.25, "read": 0.25, "write": 0.25, "pool": 0.25}
    ]
    client.close()


def test_response_size_and_invalid_payload_are_normalized() -> None:
    large_client = _client(
        lambda request: httpx.Response(200, json={"value": "x" * 100}),
        max_response_bytes=32,
    )
    invalid_client = _client(
        lambda request: httpx.Response(200, content=b"not-json"),
    )

    with pytest.raises(AgentResponseInvalidError) as large_error:
        large_client.health()
    with pytest.raises(AgentResponseInvalidError) as invalid_error:
        invalid_client.health()

    assert large_error.value.code == "agent_response_too_large"
    assert invalid_error.value.code == "agent_response_invalid"
    large_client.close()
    invalid_client.close()


def test_remote_error_body_is_never_exposed() -> None:
    client = _client(
        lambda request: httpx.Response(
            500,
            text="token=top-secret certificate=C:/secret/client.pem",
        )
    )

    with pytest.raises(AgentUnavailableError) as caught:
        client.health()

    assert str(caught.value) == "agent_unavailable"
    assert "secret" not in str(caught.value)
    client.close()


class FakeResolver:
    def __init__(self) -> None:
        self.references = []

    def resolve(self, credential_ref: str) -> AgentTLSCredentials:
        self.references.append(credential_ref)
        return AgentTLSCredentials(
            certificate=Path("external/client.crt"),
            private_key=Path("external/client.key"),
            server_ca=Path("external/server-ca.crt"),
        )


def test_unix_transport_uses_only_the_dedicated_socket(monkeypatch) -> None:
    captured = {}

    def fake_transport(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(agent_client.httpx, "HTTPTransport", fake_transport)

    result = agent_client._build_transport(
        {
            "transport": "unix_socket",
            "endpoint": "/run/nodeconductor-agent/agent.sock",
        },
        FakeResolver(),
    )

    assert result is not None
    assert captured == {
        "uds": "/run/nodeconductor-agent/agent.sock",
        "retries": 0,
    }


def test_https_transport_requires_credentials_and_mtls(monkeypatch) -> None:
    connection = {
        "transport": "https",
        "endpoint": "https://agent.example.test:8443",
        "credential_ref": "docker-main",
    }
    resolver = FakeResolver()
    context = object()
    captured = {}
    monkeypatch.setattr(agent_client, "_build_mtls_context", lambda value: context)
    monkeypatch.setattr(
        agent_client.httpx,
        "HTTPTransport",
        lambda **kwargs: captured.update(kwargs) or object(),
    )

    agent_client._build_transport(connection, resolver)

    assert resolver.references == ["docker-main"]
    assert captured == {"verify": context, "retries": 0}

    with pytest.raises(AgentClientConfigurationError):
        agent_client._build_transport(
            {**connection, "credential_ref": None},
            resolver,
        )


def test_https_rejects_plain_http_and_embedded_credentials() -> None:
    with pytest.raises(AgentClientConfigurationError):
        agent_client._base_url(
            {"transport": "https", "endpoint": "http://agent.test"}
        )
    with pytest.raises(AgentClientConfigurationError):
        agent_client._base_url(
            {
                "transport": "https",
                "endpoint": "https://user:password@agent.test",
            }
        )
