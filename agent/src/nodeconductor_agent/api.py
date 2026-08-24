"""Restricted Agent API: health, capabilities, inventory and local policies."""

from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, Path as ApiPath, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from nodeconductor_agent import __version__
from nodeconductor_agent.action_repository import ActionRepository
from nodeconductor_agent.action_service import ActionService
from nodeconductor_agent.compose_registry import ComposeProjectRegistry
from nodeconductor_agent.compose_runner import ComposeRunner, SubprocessComposeRunner
from nodeconductor_agent.docker_gateway import DockerGateway, DockerSDKGateway
from nodeconductor_agent.errors import AgentError
from nodeconductor_agent.inventory_service import InventoryService
from nodeconductor_agent.middleware import RequestBodyLimitMiddleware
from nodeconductor_agent.models import (
    CapabilitiesResponse,
    ContainerListResponse,
    ContainerResponse,
    ErrorResponse,
    HealthResponse,
    PolicyUpdateRequest,
    PolicyUpdateResponse,
    ResourceListResponse,
    ResourceActionRequest,
    ResourceActionResponse,
    TargetKind,
)
from nodeconductor_agent.policy_repository import PolicyRepository


ContainerId = Annotated[
    str,
    ApiPath(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
        description="Full immutable Docker container ID",
    ),
]
ResourceTarget = Annotated[
    str,
    ApiPath(
        min_length=1,
        max_length=255,
        pattern=r"^[^/\\\x00-\x1f]+$",
        description="Typed Docker resource identity",
    ),
]


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


def create_app(
    gateway: DockerGateway | None = None,
    database_path: str | Path = "agent.sqlite3",
    docker_timeout_seconds: int = 5,
    max_request_body_bytes: int = 16_384,
    agent_id: str = "docker-agent-local",
    protected_target_kind: TargetKind | None = None,
    protected_target: str | None = None,
    compose_registry_path: str | Path = (
        "/etc/nodeconductor-agent/compose-projects.toml"
    ),
    compose_registry: ComposeProjectRegistry | None = None,
    compose_runner: ComposeRunner | None = None,
    container_stop_timeout_seconds: int = 30,
) -> FastAPI:
    docker_gateway = gateway or DockerSDKGateway(
        max(docker_timeout_seconds, container_stop_timeout_seconds + 5)
    )
    policies = PolicyRepository(database_path)
    operations = ActionRepository(database_path)
    local_registry = compose_registry or ComposeProjectRegistry.load_or_unavailable(
        compose_registry_path
    )
    local_runner = compose_runner or SubprocessComposeRunner()
    service = InventoryService(
        agent_id,
        docker_gateway,
        policies,
        protected_target_kind,
        protected_target,
    )
    action_service = ActionService(
        service,
        docker_gateway,
        operations,
        local_registry,
        local_runner,
        container_stop_timeout_seconds=container_stop_timeout_seconds,
    )
    service.action_capabilities = action_service.capabilities
    app = FastAPI(
        title="NodeConductor Agent API",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.policy_repository = policies
    app.state.action_repository = operations
    app.state.action_service = action_service
    app.add_middleware(
        RequestBodyLimitMiddleware,
        max_body_bytes=max_request_body_bytes,
    )

    @app.exception_handler(AgentError)
    async def agent_error_handler(
        request: Request,
        error: AgentError,
    ) -> JSONResponse:
        return _error_response(error.status_code, error.code, error.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        return _error_response(422, "invalid_request", "Request validation failed")

    @app.get(
        "/api/v1/health",
        response_model=HealthResponse,
        responses={503: {"model": ErrorResponse}},
    )
    def health() -> HealthResponse:
        return service.health()

    @app.get(
        "/api/v1/capabilities",
        response_model=CapabilitiesResponse,
    )
    def capabilities() -> CapabilitiesResponse:
        return service.capabilities()

    @app.get(
        "/api/v2/resources",
        response_model=ResourceListResponse,
        responses={503: {"model": ErrorResponse}},
    )
    def list_resources(
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
        snapshot_id: UUID | None = None,
    ) -> ResourceListResponse:
        return service.list_resources(
            limit,
            offset,
            str(snapshot_id) if snapshot_id is not None else None,
        )

    @app.get(
        "/api/v1/containers",
        response_model=ContainerListResponse,
        responses={503: {"model": ErrorResponse}},
    )
    def list_containers(
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    ) -> ContainerListResponse:
        return service.list_containers(limit, offset)

    @app.get(
        "/api/v1/containers/{container_id}",
        response_model=ContainerResponse,
        responses={
            404: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
    )
    def inspect_container(container_id: ContainerId) -> ContainerResponse:
        return service.inspect_container(container_id)

    @app.put(
        "/api/v1/containers/{container_id}/management-policy",
        response_model=PolicyUpdateResponse,
        responses={
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
    )
    def update_management_policy(
        container_id: ContainerId,
        request: PolicyUpdateRequest,
    ) -> PolicyUpdateResponse:
        return service.update_container_policy(
            container_id,
            request.management_policy,
            str(request.operation_id),
            request.actor,
        )

    @app.put(
        "/api/v2/resources/{target_kind}/{target}/management-policy",
        response_model=PolicyUpdateResponse,
        responses={
            409: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
    )
    def update_typed_management_policy(
        target_kind: TargetKind,
        target: ResourceTarget,
        request: PolicyUpdateRequest,
    ) -> PolicyUpdateResponse:
        return service.update_policy(
            target_kind,
            target,
            request.management_policy,
            str(request.operation_id),
            request.actor,
        )

    @app.post(
        "/api/v2/resources/{target_kind}/{target}/actions",
        response_model=ResourceActionResponse,
        responses={
            409: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
        },
    )
    def execute_resource_action(
        target_kind: TargetKind,
        target: ResourceTarget,
        request: ResourceActionRequest,
    ) -> ResourceActionResponse:
        return action_service.execute(target_kind, target, request)

    return app
