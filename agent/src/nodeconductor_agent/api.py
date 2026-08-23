"""Restricted Agent API: health, capabilities, inventory and local policies."""

from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Path as ApiPath, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from nodeconductor_agent import __version__
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
) -> FastAPI:
    policies = PolicyRepository(database_path)
    service = InventoryService(
        gateway or DockerSDKGateway(docker_timeout_seconds),
        policies,
    )
    app = FastAPI(
        title="NodeConductor Agent API",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.policy_repository = policies
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
        return service.update_policy(
            container_id,
            request.management_policy,
            str(request.operation_id),
            request.actor,
        )

    return app
