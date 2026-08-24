import pytest

from nodeconductor_agent.config import AgentSettings


def test_transport_defaults_to_unix_socket(monkeypatch) -> None:
    monkeypatch.delenv("NODECONDUCTOR_AGENT_ID", raising=False)
    monkeypatch.delenv("NODECONDUCTOR_AGENT_TRANSPORT", raising=False)
    monkeypatch.delenv("NODECONDUCTOR_AGENT_UNIX_SOCKET", raising=False)
    monkeypatch.delenv(
        "NODECONDUCTOR_AGENT_PROTECTED_TARGET_KIND", raising=False
    )
    monkeypatch.delenv("NODECONDUCTOR_AGENT_PROTECTED_TARGET", raising=False)
    monkeypatch.delenv("NODECONDUCTOR_AGENT_COMPOSE_REGISTRY", raising=False)
    monkeypatch.delenv(
        "NODECONDUCTOR_AGENT_CONTAINER_STOP_TIMEOUT_SECONDS", raising=False
    )

    settings = AgentSettings.from_env()

    assert settings.transport == "unix_socket"
    assert settings.agent_id == "docker-agent-local"
    assert str(settings.unix_socket_path).endswith("nodeconductor-agent.sock")
    assert settings.https_port is None
    assert settings.protected_target_kind is None
    assert str(settings.compose_registry_path).endswith("compose-projects.toml")
    assert settings.container_stop_timeout_seconds == 30


def test_plain_tcp_transport_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("NODECONDUCTOR_AGENT_TRANSPORT", "tcp")

    with pytest.raises(ValueError, match="unix_socket or https"):
        AgentSettings.from_env()


def test_invalid_agent_id_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("NODECONDUCTOR_AGENT_ID", "agent id with spaces")

    with pytest.raises(ValueError, match="AGENT_ID is invalid"):
        AgentSettings.from_env()


def test_https_requires_server_certificate_key_and_client_ca(monkeypatch) -> None:
    monkeypatch.setenv("NODECONDUCTOR_AGENT_TRANSPORT", "https")
    monkeypatch.delenv("NODECONDUCTOR_AGENT_TLS_CERTIFICATE", raising=False)
    monkeypatch.delenv("NODECONDUCTOR_AGENT_TLS_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("NODECONDUCTOR_AGENT_TLS_CLIENT_CA", raising=False)

    with pytest.raises(ValueError, match="TLS_CERTIFICATE is required"):
        AgentSettings.from_env()


def test_https_rejects_invalid_certificate_material(monkeypatch, tmp_path) -> None:
    cert = tmp_path / "server.crt"
    key = tmp_path / "server.key"
    ca = tmp_path / "client-ca.crt"
    cert.write_text("invalid certificate", encoding="utf-8")
    key.write_text("invalid private key", encoding="utf-8")
    ca.write_text("invalid ca", encoding="utf-8")
    monkeypatch.setenv("NODECONDUCTOR_AGENT_TRANSPORT", "https")
    monkeypatch.setenv("NODECONDUCTOR_AGENT_TLS_CERTIFICATE", str(cert))
    monkeypatch.setenv("NODECONDUCTOR_AGENT_TLS_PRIVATE_KEY", str(key))
    monkeypatch.setenv("NODECONDUCTOR_AGENT_TLS_CLIENT_CA", str(ca))

    with pytest.raises(ValueError, match="certificates or private key are invalid"):
        AgentSettings.from_env()


def test_protected_identity_requires_kind_and_target(monkeypatch) -> None:
    monkeypatch.setenv(
        "NODECONDUCTOR_AGENT_PROTECTED_TARGET_KIND", "compose_project"
    )
    monkeypatch.delenv("NODECONDUCTOR_AGENT_PROTECTED_TARGET", raising=False)

    with pytest.raises(ValueError, match="PROTECTED_TARGET is invalid"):
        AgentSettings.from_env()


def test_standalone_protection_requires_full_docker_id(monkeypatch) -> None:
    monkeypatch.setenv(
        "NODECONDUCTOR_AGENT_PROTECTED_TARGET_KIND",
        "standalone_container",
    )
    monkeypatch.setenv(
        "NODECONDUCTOR_AGENT_PROTECTED_TARGET", "container-name"
    )

    with pytest.raises(ValueError, match="full Docker ID"):
        AgentSettings.from_env()


@pytest.mark.parametrize("value", ["0", "301", "not-an-integer"])
def test_container_stop_timeout_is_strictly_bounded(monkeypatch, value) -> None:
    monkeypatch.setenv(
        "NODECONDUCTOR_AGENT_CONTAINER_STOP_TIMEOUT_SECONDS", value
    )

    with pytest.raises(ValueError, match="CONTAINER_STOP_TIMEOUT_SECONDS"):
        AgentSettings.from_env()
