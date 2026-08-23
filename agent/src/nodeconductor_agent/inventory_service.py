"""Inventory and local-policy orchestration independent from HTTP and Docker SDK."""

from nodeconductor_agent import __version__
from nodeconductor_agent.docker_gateway import DockerGateway
from nodeconductor_agent.errors import EngineUnavailableError
from nodeconductor_agent.models import (
    CapabilitiesResponse,
    ContainerListResponse,
    ContainerResponse,
    HealthResponse,
    ManagementPolicy,
    PolicyUpdateResponse,
)
from nodeconductor_agent.policy_repository import PolicyRepository


BASE_CAPABILITIES = ["health", "capabilities"]
ENGINE_CAPABILITIES = [
    "container_list",
    "container_inspect",
    "management_policy",
]


class InventoryService:
    def __init__(
        self,
        gateway: DockerGateway,
        policies: PolicyRepository,
    ) -> None:
        self.gateway = gateway
        self.policies = policies

    def health(self) -> HealthResponse:
        try:
            self.gateway.ping()
        except EngineUnavailableError:
            return HealthResponse(
                status="degraded",
                agent_version=__version__,
                engine_status="engine_unavailable",
            )
        return HealthResponse(
            status="ready",
            agent_version=__version__,
            engine_status="available",
        )

    def capabilities(self) -> CapabilitiesResponse:
        try:
            version = self.gateway.engine_version()
        except EngineUnavailableError:
            return CapabilitiesResponse(
                agent_version=__version__,
                api_version="v1",
                engine_available=False,
                engine_version=None,
                docker_api_version=None,
                capabilities=BASE_CAPABILITIES,
            )
        return CapabilitiesResponse(
            agent_version=__version__,
            api_version="v1",
            engine_available=True,
            engine_version=version.engine_version,
            docker_api_version=version.api_version,
            capabilities=BASE_CAPABILITIES + ENGINE_CAPABILITIES,
        )

    def list_containers(self, limit: int, offset: int) -> ContainerListResponse:
        page = self.gateway.list_containers(limit, offset)
        items = [self._with_policy(snapshot) for snapshot in page.items]
        return ContainerListResponse(
            items=items,
            limit=limit,
            offset=offset,
            total=page.total,
        )

    def inspect_container(self, container_id: str) -> ContainerResponse:
        snapshot = self.gateway.inspect_container(container_id)
        return self._with_policy(snapshot)

    def update_policy(
        self,
        container_id: str,
        management_policy: ManagementPolicy,
        operation_id: str,
        actor: str,
    ) -> PolicyUpdateResponse:
        replay = self.policies.replay_operation(
            operation_id,
            container_id,
            management_policy,
            actor,
        )
        if replay is not None:
            return replay
        snapshot = self.gateway.inspect_container(container_id)
        return self.policies.set_policy(
            snapshot.id,
            snapshot.name,
            management_policy,
            operation_id,
            actor,
        )

    def _with_policy(self, snapshot) -> ContainerResponse:
        policy = self.policies.observe(snapshot.id, snapshot.name)
        return ContainerResponse(
            id=snapshot.id,
            name=snapshot.name,
            state=snapshot.state,
            health_status=snapshot.health_status,
            created_at=snapshot.created_at,
            management_policy=policy,
        )
