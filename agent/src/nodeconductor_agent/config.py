"""Environment configuration for safe Unix-socket or HTTPS-mTLS startup."""

from dataclasses import dataclass
import os
from pathlib import Path
import re
import ssl

from nodeconductor_agent.models import TargetKind


def _positive_int(name: str, default: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if value <= 0 or value > maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}")
    return value


def _agent_id() -> str:
    value = os.getenv(
        "NODECONDUCTOR_AGENT_ID",
        "docker-agent-local",
    ).strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", value):
        raise ValueError("NODECONDUCTOR_AGENT_ID is invalid")
    return value


def _required_file(name: str) -> Path:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required for HTTPS transport")
    path = Path(value)
    if not path.is_file():
        raise ValueError(f"{name} must reference a readable file")
    return path


def _validate_mtls(cert: Path, key: Path, client_ca: Path) -> None:
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    try:
        context.load_cert_chain(certfile=cert, keyfile=key)
        context.load_verify_locations(cafile=client_ca)
    except (OSError, ssl.SSLError) as error:
        raise ValueError("HTTPS certificates or private key are invalid") from error
    context.verify_mode = ssl.CERT_REQUIRED


def _protected_identity() -> tuple[TargetKind | None, str | None]:
    kind = os.getenv(
        "NODECONDUCTOR_AGENT_PROTECTED_TARGET_KIND", ""
    ).strip()
    target = os.getenv("NODECONDUCTOR_AGENT_PROTECTED_TARGET", "").strip()
    if not kind and not target:
        return None, None
    if kind not in {"compose_project", "standalone_container"}:
        raise ValueError(
            "NODECONDUCTOR_AGENT_PROTECTED_TARGET_KIND is invalid"
        )
    if (
        not target
        or len(target) > 255
        or "/" in target
        or "\\" in target
        or any(ord(character) < 32 for character in target)
    ):
        raise ValueError("NODECONDUCTOR_AGENT_PROTECTED_TARGET is invalid")
    if kind == "standalone_container" and not re.fullmatch(
        r"[0-9a-f]{64}", target
    ):
        raise ValueError(
            "standalone protected target must be a full Docker ID"
        )
    return kind, target


@dataclass(frozen=True)
class AgentSettings:
    agent_id: str
    transport: str
    database_path: Path
    docker_timeout_seconds: int
    max_request_body_bytes: int
    compose_registry_path: Path
    container_stop_timeout_seconds: int
    protected_target_kind: TargetKind | None = None
    protected_target: str | None = None
    unix_socket_path: Path | None = None
    https_host: str | None = None
    https_port: int | None = None
    server_certificate: Path | None = None
    server_key: Path | None = None
    client_ca: Path | None = None

    @classmethod
    def from_env(cls) -> "AgentSettings":
        transport = os.getenv(
            "NODECONDUCTOR_AGENT_TRANSPORT",
            "unix_socket",
        ).strip().lower()
        protected_target_kind, protected_target = _protected_identity()
        common = {
            "agent_id": _agent_id(),
            "transport": transport,
            "database_path": Path(
                os.getenv(
                    "NODECONDUCTOR_AGENT_DATABASE_PATH",
                    "/var/lib/nodeconductor-agent/agent.sqlite3",
                )
            ),
            "docker_timeout_seconds": _positive_int(
                "NODECONDUCTOR_AGENT_DOCKER_TIMEOUT_SECONDS",
                5,
                30,
            ),
            "max_request_body_bytes": _positive_int(
                "NODECONDUCTOR_AGENT_MAX_REQUEST_BODY_BYTES",
                16_384,
                1_048_576,
            ),
            "compose_registry_path": Path(
                os.getenv(
                    "NODECONDUCTOR_AGENT_COMPOSE_REGISTRY",
                    "/etc/nodeconductor-agent/compose-projects.toml",
                )
            ),
            "container_stop_timeout_seconds": _positive_int(
                "NODECONDUCTOR_AGENT_CONTAINER_STOP_TIMEOUT_SECONDS",
                30,
                300,
            ),
            "protected_target_kind": protected_target_kind,
            "protected_target": protected_target,
        }
        if transport == "unix_socket":
            return cls(
                **common,
                unix_socket_path=Path(
                    os.getenv(
                        "NODECONDUCTOR_AGENT_UNIX_SOCKET",
                        "/run/nodeconductor-agent/nodeconductor-agent.sock",
                    )
                ),
            )
        if transport != "https":
            raise ValueError(
                "NODECONDUCTOR_AGENT_TRANSPORT must be unix_socket or https"
            )
        cert = _required_file("NODECONDUCTOR_AGENT_TLS_CERTIFICATE")
        key = _required_file("NODECONDUCTOR_AGENT_TLS_PRIVATE_KEY")
        client_ca = _required_file("NODECONDUCTOR_AGENT_TLS_CLIENT_CA")
        _validate_mtls(cert, key, client_ca)
        return cls(
            **common,
            https_host=os.getenv(
                "NODECONDUCTOR_AGENT_HTTPS_HOST",
                "127.0.0.1",
            ).strip(),
            https_port=_positive_int(
                "NODECONDUCTOR_AGENT_HTTPS_PORT",
                8443,
                65_535,
            ),
            server_certificate=cert,
            server_key=key,
            client_ca=client_ca,
        )
