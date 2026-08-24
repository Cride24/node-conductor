"""Typed read-only Docker inventory and local-policy orchestration."""

from datetime import datetime, timezone
from threading import Lock
from uuid import uuid4
from collections.abc import Callable

from nodeconductor_agent import __version__
from nodeconductor_agent.docker_gateway import DockerGateway
from nodeconductor_agent.errors import (
    EngineUnavailableError,
    ProtectedResourceError,
    ResourceNotOperableError,
    InventorySnapshotError,
)
from nodeconductor_agent.models import (
    CapabilitiesResponse,
    ComposeState,
    ContainerListResponse,
    ContainerResponse,
    HealthResponse,
    HealthStatus,
    ManagementPolicy,
    PolicyUpdateResponse,
    ResourceListResponse,
    ResourceMemberResponse,
    ResourceResponse,
    TargetKind,
)
from nodeconductor_agent.policy_repository import PolicyRepository


BASE_CAPABILITIES = ["health", "capabilities"]
ENGINE_CAPABILITIES = [
    "container_list",
    "container_inspect",
    "resource_inventory_v1",
    "typed_management_policy",
]


class InventoryService:
    def __init__(
        self,
        agent_id: str,
        gateway: DockerGateway,
        policies: PolicyRepository,
        protected_target_kind: TargetKind | None = None,
        protected_target: str | None = None,
        action_capabilities: Callable[[], list[str]] | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.gateway = gateway
        self.policies = policies
        self.protected_target_kind = protected_target_kind
        self.protected_target = protected_target
        self.action_capabilities = action_capabilities or (lambda: [])
        self._snapshot_lock = Lock()
        self._snapshots: dict[str, tuple] = {}

    def health(self) -> HealthResponse:
        try:
            self.gateway.ping()
        except EngineUnavailableError:
            return HealthResponse(
                agent_id=self.agent_id,
                status="degraded",
                agent_version=__version__,
                engine_status="engine_unavailable",
            )
        return HealthResponse(
            agent_id=self.agent_id,
            status="ready",
            agent_version=__version__,
            engine_status="available",
        )

    def capabilities(self) -> CapabilitiesResponse:
        try:
            version = self.gateway.engine_version()
        except EngineUnavailableError:
            return CapabilitiesResponse(
                agent_id=self.agent_id,
                agent_version=__version__,
                api_version="v2",
                engine_available=False,
                engine_version=None,
                docker_api_version=None,
                capabilities=BASE_CAPABILITIES,
            )
        return CapabilitiesResponse(
            agent_id=self.agent_id,
            agent_version=__version__,
            api_version="v2",
            engine_available=True,
            engine_version=version.engine_version,
            docker_api_version=version.api_version,
            capabilities=(
                BASE_CAPABILITIES
                + ENGINE_CAPABILITIES
                + self.action_capabilities()
            ),
        )

    def list_resources(
        self,
        limit: int,
        offset: int,
        snapshot_id: str | None = None,
    ) -> ResourceListResponse:
        with self._snapshot_lock:
            if offset == 0 and snapshot_id is None:
                observed_at = datetime.now(timezone.utc)
                resources, protection_status = self._build_resources(observed_at)
                snapshot_id = str(uuid4())
                self._snapshots[snapshot_id] = (
                    resources,
                    observed_at,
                    protection_status,
                )
                while len(self._snapshots) > 4:
                    self._snapshots.pop(next(iter(self._snapshots)))
            elif snapshot_id in self._snapshots:
                resources, observed_at, protection_status = self._snapshots[
                    snapshot_id
                ]
            else:
                raise InventorySnapshotError()
        return ResourceListResponse(
            items=resources[offset : offset + limit],
            limit=limit,
            offset=offset,
            total=len(resources),
            snapshot_id=snapshot_id,
            snapshot_observed_at=observed_at,
            protection_status=protection_status,
        )

    def current_resources(self):
        """Build a fresh filtered snapshot for local policy/action decisions."""
        return self._build_resources(datetime.now(timezone.utc))

    def list_containers(self, limit: int, offset: int) -> ContainerListResponse:
        """Deprecated v1 view: only genuinely standalone containers are visible."""
        snapshots = [
            snapshot
            for snapshot in self.gateway.list_all_containers()
            if snapshot.compose_classification == "none"
        ]
        items = [
            self._standalone_container_response(snapshot)
            for snapshot in snapshots[offset : offset + limit]
        ]
        return ContainerListResponse(
            items=items,
            limit=limit,
            offset=offset,
            total=len(snapshots),
        )

    def inspect_container(self, container_id: str) -> ContainerResponse:
        snapshot = self.gateway.inspect_container(container_id)
        if snapshot.compose_classification != "none":
            raise ResourceNotOperableError()
        return self._standalone_container_response(snapshot)

    def update_container_policy(
        self,
        container_id: str,
        management_policy: ManagementPolicy,
        operation_id: str,
        actor: str,
    ) -> PolicyUpdateResponse:
        return self.update_policy(
            "standalone_container",
            container_id,
            management_policy,
            operation_id,
            actor,
        )

    def update_policy(
        self,
        target_kind: TargetKind,
        target: str,
        management_policy: ManagementPolicy,
        operation_id: str,
        actor: str,
    ) -> PolicyUpdateResponse:
        replay = self.policies.replay_operation(
            operation_id,
            target_kind,
            target,
            management_policy,
            actor,
        )
        if replay is not None:
            return replay
        if self._is_configured_protection(target_kind, target):
            if management_policy != "protected":
                raise ProtectedResourceError()
        resource = self._find_operational_resource(target_kind, target)
        return self.policies.set_policy(
            target_kind,
            target,
            resource.display_name,
            management_policy,
            operation_id,
            actor,
        )

    def _find_operational_resource(
        self,
        target_kind: TargetKind,
        target: str,
    ) -> ResourceResponse:
        resources, _ = self._build_resources(datetime.now(timezone.utc))
        for resource in resources:
            if (
                resource.classification == "operational"
                and resource.target_kind == target_kind
                and resource.target == target
            ):
                return resource
        if target_kind == "standalone_container":
            snapshot = self.gateway.inspect_container(target)
            if snapshot.compose_classification != "none":
                raise ResourceNotOperableError()
        raise ResourceNotOperableError()

    def _build_resources(self, observed_at: datetime):
        snapshots = self.gateway.list_all_containers()
        projects: dict[str, list] = {}
        resources: list[ResourceResponse] = []
        configured_inconsistent = False
        for snapshot in snapshots:
            if snapshot.compose_classification == "coherent":
                projects.setdefault(snapshot.compose_project, []).append(snapshot)
                if self._is_configured_protection(
                    "standalone_container", snapshot.id
                ):
                    configured_inconsistent = True
                continue
            if snapshot.compose_classification == "ambiguous":
                resources.append(
                    ResourceResponse(
                        classification="ambiguous",
                        target_kind=None,
                        target=snapshot.id,
                        display_name=snapshot.name,
                        state=snapshot.state,
                        health_status=snapshot.health_status,
                        management_policy=None,
                        operable=False,
                        diagnostic_status=(
                            "compose_labels_incomplete_or_invalid"
                        ),
                    )
                )
                if self._is_configured_protection(
                    "standalone_container", snapshot.id
                ):
                    configured_inconsistent = True
                if (
                    snapshot.compose_project is not None
                    and self._is_configured_protection(
                        "compose_project", snapshot.compose_project
                    )
                ):
                    configured_inconsistent = True
                continue
            resources.append(self._standalone_resource(snapshot))
        for project, members in projects.items():
            resources.append(self._compose_resource(project, members, observed_at))

        resources.sort(
            key=lambda item: (
                item.classification != "operational",
                item.target_kind or "",
                item.target,
            )
        )
        if self.protected_target_kind is None:
            protection_status = "not_configured"
        elif any(item.protection_forced for item in resources):
            protection_status = "protected"
        elif configured_inconsistent:
            protection_status = "configured_inconsistent"
        else:
            protection_status = "configured_absent"
        return resources, protection_status

    def _standalone_resource(self, snapshot) -> ResourceResponse:
        forced = self._is_configured_protection(
            "standalone_container", snapshot.id
        )
        policy = self._policy(
            "standalone_container", snapshot.id, snapshot.name, forced
        )
        return ResourceResponse(
            classification="operational",
            target_kind="standalone_container",
            target=snapshot.id,
            display_name=snapshot.name,
            state=snapshot.state,
            health_status=snapshot.health_status,
            management_policy=policy,
            operable=True,
            protection_forced=forced,
        )

    def _compose_resource(
        self,
        project: str,
        snapshots: list,
        observed_at: datetime,
    ) -> ResourceResponse:
        members = [
            ResourceMemberResponse(
                docker_id=snapshot.id,
                name=snapshot.name,
                compose_service=snapshot.compose_service,
                state=snapshot.state,
                health_status=snapshot.health_status,
                last_observed_at=observed_at,
            )
            for snapshot in sorted(snapshots, key=lambda item: item.id)
        ]
        forced = self._is_configured_protection("compose_project", project)
        policy = self._policy("compose_project", project, project, forced)
        return ResourceResponse(
            classification="operational",
            target_kind="compose_project",
            target=project,
            display_name=project,
            state=aggregate_compose_state(members),
            health_status=aggregate_health_status(members),
            management_policy=policy,
            operable=True,
            protection_forced=forced,
            members=members,
        )

    def _standalone_container_response(self, snapshot) -> ContainerResponse:
        forced = self._is_configured_protection(
            "standalone_container", snapshot.id
        )
        policy = self._policy(
            "standalone_container", snapshot.id, snapshot.name, forced
        )
        return ContainerResponse(
            id=snapshot.id,
            name=snapshot.name,
            state=snapshot.state,
            health_status=snapshot.health_status,
            created_at=snapshot.created_at,
            management_policy=policy,
        )

    def _policy(
        self,
        target_kind: TargetKind,
        target: str,
        display_name: str,
        forced: bool,
    ) -> ManagementPolicy:
        if forced:
            self.policies.force_protected(target_kind, target, display_name)
            return "protected"
        return self.policies.observe(target_kind, target, display_name)

    def _is_configured_protection(
        self,
        target_kind: TargetKind,
        target: str,
    ) -> bool:
        return (
            self.protected_target_kind == target_kind
            and self.protected_target == target
        )


def aggregate_compose_state(members: list[ResourceMemberResponse]) -> ComposeState:
    """Deterministic inventory aggregate; it is never a readiness result."""
    if not members:
        return "unknown"
    states = {member.state for member in members}
    health = {member.health_status for member in members}
    if states & {"unknown", "removing", "dead"} or "unknown" in health:
        return "unknown"
    stopped = {"created", "exited"}
    active = {"running", "restarting", "paused"}
    if states <= stopped:
        return "stopped"
    if states & stopped and states & active:
        return "partial"
    if "unhealthy" in health or "paused" in states:
        return "degraded"
    if "restarting" in states or "starting" in health:
        return "starting"
    if states == {"running"}:
        return "running"
    return "unknown"


def aggregate_health_status(
    members: list[ResourceMemberResponse],
) -> HealthStatus:
    statuses = {member.health_status for member in members}
    if not statuses or "unknown" in statuses:
        return "unknown"
    if "unhealthy" in statuses:
        return "unhealthy"
    if "starting" in statuses:
        return "starting"
    if statuses == {"none"}:
        return "none"
    return "healthy"
