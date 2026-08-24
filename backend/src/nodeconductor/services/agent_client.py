"""Client HTTP borne vers l'API metier restreinte d'un Agent."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import ssl
from typing import Protocol
from uuid import UUID
from urllib.parse import urlparse

import httpx
from pydantic import ValidationError

from nodeconductor.schemas.agent_api import (
    AgentCapabilities,
    AgentContainerPage,
    AgentHealth,
    AgentResourcePage,
)


class AgentClientError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class AgentUnavailableError(AgentClientError):
    pass


class AgentResponseInvalidError(AgentClientError):
    pass


class AgentClientConfigurationError(AgentClientError):
    pass


class AgentClient(Protocol):
    def health(self, timeout_seconds: float | None = None) -> AgentHealth: ...

    def capabilities(
        self,
        timeout_seconds: float | None = None,
    ) -> AgentCapabilities: ...

    def list_containers(
        self,
        limit: int,
        offset: int,
        timeout_seconds: float | None = None,
    ) -> AgentContainerPage: ...

    def list_resources(
        self,
        limit: int,
        offset: int,
        timeout_seconds: float | None = None,
        snapshot_id: UUID | None = None,
    ) -> AgentResourcePage: ...


@dataclass(frozen=True)
class AgentTLSCredentials:
    certificate: Path
    private_key: Path
    server_ca: Path


class AgentCredentialResolver(Protocol):
    def resolve(self, credential_ref: str) -> AgentTLSCredentials: ...


class EnvironmentCredentialResolver:
    """Resout des chemins TLS depuis l'environnement, jamais depuis PostgreSQL."""

    def resolve(self, credential_ref: str) -> AgentTLSCredentials:
        normalized = re.sub(r"[^A-Za-z0-9]", "_", credential_ref).upper()
        prefix = f"NODECONDUCTOR_AGENT_CREDENTIAL_{normalized}"
        return AgentTLSCredentials(
            certificate=self._required_path(f"{prefix}_CERTIFICATE"),
            private_key=self._required_path(f"{prefix}_PRIVATE_KEY"),
            server_ca=self._required_path(f"{prefix}_SERVER_CA"),
        )

    @staticmethod
    def _required_path(name: str) -> Path:
        value = os.getenv(name, "").strip()
        if not value or not Path(value).is_file():
            raise AgentClientConfigurationError("agent_credentials_unavailable")
        return Path(value)


class HttpAgentClient:
    def __init__(
        self,
        client: httpx.Client,
        max_response_bytes: int,
        connect_timeout_seconds: float | None = None,
        response_timeout_seconds: float | None = None,
    ) -> None:
        self._client = client
        self._max_response_bytes = max_response_bytes
        self._connect_timeout_seconds = connect_timeout_seconds
        self._response_timeout_seconds = response_timeout_seconds

    def health(self, timeout_seconds: float | None = None) -> AgentHealth:
        return self._get(
            "/api/v1/health",
            AgentHealth,
            timeout_seconds=timeout_seconds,
        )

    def capabilities(
        self,
        timeout_seconds: float | None = None,
    ) -> AgentCapabilities:
        return self._get(
            "/api/v1/capabilities",
            AgentCapabilities,
            timeout_seconds=timeout_seconds,
        )

    def list_containers(
        self,
        limit: int,
        offset: int,
        timeout_seconds: float | None = None,
    ) -> AgentContainerPage:
        return self._get(
            "/api/v1/containers",
            AgentContainerPage,
            params={"limit": limit, "offset": offset},
            timeout_seconds=timeout_seconds,
        )

    def list_resources(
        self,
        limit: int,
        offset: int,
        timeout_seconds: float | None = None,
        snapshot_id: UUID | None = None,
    ) -> AgentResourcePage:
        return self._get(
            "/api/v2/resources",
            AgentResourcePage,
            params={
                "limit": limit,
                "offset": offset,
                **(
                    {"snapshot_id": str(snapshot_id)}
                    if snapshot_id is not None
                    else {}
                ),
            },
            timeout_seconds=timeout_seconds,
        )

    def close(self) -> None:
        self._client.close()

    def _get(self, path: str, model, params=None, timeout_seconds=None):
        request_options = {}
        if timeout_seconds is not None:
            request_options["timeout"] = self._bounded_timeout(timeout_seconds)
        try:
            with self._client.stream(
                "GET",
                path,
                params=params,
                **request_options,
            ) as response:
                if response.status_code != 200:
                    raise AgentUnavailableError("agent_unavailable")
                payload = self._read_json(response)
        except AgentClientError:
            raise
        except httpx.HTTPError as error:
            raise AgentUnavailableError("agent_unavailable") from error
        try:
            return model.model_validate(payload)
        except ValidationError as error:
            raise AgentResponseInvalidError("agent_response_invalid") from error

    def _bounded_timeout(self, remaining_seconds: float) -> httpx.Timeout:
        if remaining_seconds <= 0:
            raise AgentClientConfigurationError("agent_deadline_expired")
        connect = min(
            remaining_seconds,
            self._connect_timeout_seconds or remaining_seconds,
        )
        response = min(
            remaining_seconds,
            self._response_timeout_seconds or remaining_seconds,
        )
        return httpx.Timeout(
            connect=connect,
            read=response,
            write=response,
            pool=connect,
        )

    def _read_json(self, response: httpx.Response) -> dict:
        body = bytearray()
        for chunk in response.iter_bytes():
            body.extend(chunk)
            if len(body) > self._max_response_bytes:
                raise AgentResponseInvalidError("agent_response_too_large")
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AgentResponseInvalidError("agent_response_invalid") from error
        if not isinstance(payload, dict):
            raise AgentResponseInvalidError("agent_response_invalid")
        return payload


def build_http_agent_client(
    connection: dict,
    credential_resolver: AgentCredentialResolver,
    connect_timeout_seconds: int,
    response_timeout_seconds: int,
    max_response_bytes: int,
) -> HttpAgentClient:
    timeout = httpx.Timeout(
        connect=connect_timeout_seconds,
        read=response_timeout_seconds,
        write=response_timeout_seconds,
        pool=connect_timeout_seconds,
    )
    base_url = _base_url(connection)
    transport = _build_transport(connection, credential_resolver)
    client = httpx.Client(
        base_url=base_url,
        transport=transport,
        timeout=timeout,
        follow_redirects=False,
        trust_env=False,
        limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
    )
    return HttpAgentClient(
        client,
        max_response_bytes,
        connect_timeout_seconds,
        response_timeout_seconds,
    )


def _base_url(connection: dict) -> str:
    if connection["transport"] == "unix_socket":
        return "http://nodeconductor-agent"
    endpoint = connection["endpoint"]
    parsed = urlparse(endpoint)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise AgentClientConfigurationError("agent_https_endpoint_invalid")
    return endpoint.rstrip("/")


def _build_transport(connection: dict, resolver: AgentCredentialResolver):
    if connection["transport"] == "unix_socket":
        return httpx.HTTPTransport(uds=connection["endpoint"], retries=0)
    if connection["transport"] != "https":
        raise AgentClientConfigurationError("agent_transport_invalid")
    credential_ref = connection.get("credential_ref")
    if not credential_ref:
        raise AgentClientConfigurationError("agent_credentials_unavailable")
    credentials = resolver.resolve(credential_ref)
    context = _build_mtls_context(credentials)
    return httpx.HTTPTransport(verify=context, retries=0)


def _build_mtls_context(credentials: AgentTLSCredentials) -> ssl.SSLContext:
    try:
        context = ssl.create_default_context(
            ssl.Purpose.SERVER_AUTH,
            cafile=credentials.server_ca,
        )
        context.load_cert_chain(
            certfile=credentials.certificate,
            keyfile=credentials.private_key,
        )
    except (OSError, ssl.SSLError) as error:
        raise AgentClientConfigurationError("agent_credentials_invalid") from error
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context
