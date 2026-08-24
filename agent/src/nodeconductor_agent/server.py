"""System-service entrypoint; plain unauthenticated TCP is unsupported."""

import ssl

import uvicorn

from nodeconductor_agent.api import create_app
from nodeconductor_agent.config import AgentSettings


def main() -> None:
    settings = AgentSettings.from_env()
    app = create_app(
        agent_id=settings.agent_id,
        database_path=settings.database_path,
        docker_timeout_seconds=settings.docker_timeout_seconds,
        max_request_body_bytes=settings.max_request_body_bytes,
        protected_target_kind=settings.protected_target_kind,
        protected_target=settings.protected_target,
        compose_registry_path=settings.compose_registry_path,
        container_stop_timeout_seconds=(
            settings.container_stop_timeout_seconds
        ),
    )
    common = {
        "app": app,
        "limit_concurrency": 100,
        "timeout_keep_alive": 5,
        "server_header": False,
    }
    if settings.transport == "unix_socket":
        settings.unix_socket_path.parent.mkdir(parents=True, exist_ok=True)
        uvicorn.run(uds=str(settings.unix_socket_path), **common)
        return
    uvicorn.run(
        host=settings.https_host,
        port=settings.https_port,
        ssl_certfile=str(settings.server_certificate),
        ssl_keyfile=str(settings.server_key),
        ssl_ca_certs=str(settings.client_ca),
        ssl_cert_reqs=ssl.CERT_REQUIRED,
        **common,
    )


if __name__ == "__main__":
    main()
