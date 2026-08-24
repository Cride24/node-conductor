"""Policy-enforcing orchestration for the two allowed Docker actions."""

from datetime import datetime, timezone
import re
from threading import Event, Lock

from nodeconductor_agent.action_errors import ActionExecutionError
from nodeconductor_agent.action_repository import ActionRepository
from nodeconductor_agent.compose_registry import (
    ComposeProjectDefinition,
    ComposeProjectRegistry,
    PROJECT_NAME_PATTERN,
)
from nodeconductor_agent.compose_runner import ComposeRunner
from nodeconductor_agent.docker_gateway import DockerGateway
from nodeconductor_agent.errors import (
    ContainerNotFoundError,
    EngineUnavailableError,
    InvalidActionTargetError,
    OperationConflictError,
)
from nodeconductor_agent.inventory_service import InventoryService
from nodeconductor_agent.models import (
    ActionResourceState,
    ResourceAction,
    ResourceActionRequest,
    ResourceActionResponse,
    ResourceResponse,
    TargetKind,
)


CONTAINER_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ActionService:
    def __init__(
        self,
        inventory: InventoryService,
        gateway: DockerGateway,
        operations: ActionRepository,
        compose_registry: ComposeProjectRegistry,
        compose_runner: ComposeRunner,
        *,
        container_stop_timeout_seconds: int = 30,
    ) -> None:
        if not 1 <= container_stop_timeout_seconds <= 300:
            raise ValueError("Container stop timeout must be between 1 and 300")
        self.inventory = inventory
        self.gateway = gateway
        self.operations = operations
        self.compose_registry = compose_registry
        self.compose_runner = compose_runner
        self.container_stop_timeout_seconds = container_stop_timeout_seconds
        self._coordination_lock = Lock()
        self._active_operations: dict[str, tuple[tuple, Event]] = {}
        self._resource_locks_guard = Lock()
        self._resource_locks: dict[tuple[TargetKind, str], Lock] = {}

    def capabilities(self) -> list[str]:
        capabilities = ["standalone_start_stop"]
        if self.compose_registry.has_projects and self.compose_runner.is_available():
            capabilities.append("compose_start_stop")
        return capabilities

    def execute(
        self,
        target_kind: TargetKind,
        target: str,
        request: ResourceActionRequest,
    ) -> ResourceActionResponse:
        self._validate_target(target_kind, target)
        operation_id = str(request.operation_id)
        fingerprint = (target_kind, target, request.actor, request.action)
        with self._coordination_lock:
            active = self._active_operations.get(operation_id)
            if active is None:
                completion = Event()
                self._active_operations[operation_id] = (fingerprint, completion)
                leader = True
            else:
                active_fingerprint, completion = active
                if active_fingerprint != fingerprint:
                    raise OperationConflictError()
                leader = False
        if not leader:
            completion.wait()
            replay = self.operations.replay(
                operation_id,
                target_kind,
                target,
                request.actor,
                request.action,
            )
            if replay is None:
                raise RuntimeError("completed operation result is unavailable")
            return replay
        try:
            return self._execute_leader(target_kind, target, request)
        finally:
            with self._coordination_lock:
                _, completion = self._active_operations.pop(operation_id)
                completion.set()

    def _execute_leader(
        self,
        target_kind: TargetKind,
        target: str,
        request: ResourceActionRequest,
    ) -> ResourceActionResponse:
        operation_id = str(request.operation_id)
        begin = self.operations.begin(
            operation_id,
            target_kind,
            target,
            request.actor,
            request.action,
        )
        if begin.response is not None:
            return begin.response
        if begin.kind == "in_progress":
            raise RuntimeError("operation is active outside this Agent process")
        resource_lock = self._resource_lock(target_kind, target)
        if not resource_lock.acquire(blocking=False):
            return self.operations.finish(
                operation_id,
                "rejected",
                "resource_busy",
                "Another action is active for this resource",
            )
        dispatched = False
        try:
            try:
                resource = self._current_target(target_kind, target)
            except ContainerNotFoundError:
                return self.operations.finish(
                    operation_id,
                    "rejected",
                    "resource_not_found",
                    "Docker resource is not present",
                )
            rejection = self._preflight_rejection(resource)
            if rejection is not None:
                status, code, message = rejection
                return self.operations.finish(
                    operation_id,
                    status,
                    code,
                    message,
                    self._filtered(resource),
                )
            project = None
            if target_kind == "compose_project":
                registry_failure, project = self._compose_preflight(target)
                if registry_failure is not None:
                    status, code, message = registry_failure
                    return self.operations.finish(
                        operation_id,
                        status,
                        code,
                        message,
                        self._filtered(resource),
                    )
            if self._desired_state_observed(resource, request.action):
                return self.operations.finish(
                    operation_id,
                    "completed",
                    "already_in_desired_state",
                    "Requested Docker state was already observed",
                    self._filtered(resource),
                )
            if (
                target_kind == "compose_project"
                and not self.compose_runner.is_available()
            ):
                return self.operations.finish(
                    operation_id,
                    "failed",
                    "compose_runner_unavailable",
                    "Docker Compose runner is unavailable",
                    self._filtered(resource),
                )
            self.operations.mark_dispatched(operation_id)
            dispatched = True
            if target_kind == "standalone_container":
                if request.action == "start":
                    self.gateway.start_container(target)
                else:
                    self.gateway.stop_container(
                        target,
                        self.container_stop_timeout_seconds,
                    )
            else:
                self.compose_runner.execute(project, request.action)
            try:
                observed = self._current_target(target_kind, target)
            except (EngineUnavailableError, ContainerNotFoundError):
                return self.operations.finish(
                    operation_id,
                    "indeterminate",
                    "post_dispatch_state_unknown",
                    "Infrastructure action was dispatched but final state is unknown",
                )
            if self._desired_state_observed(observed, request.action):
                return self.operations.finish(
                    operation_id,
                    "completed",
                    "action_completed",
                    "Infrastructure action completed and requested Docker state was observed",
                    self._filtered(observed),
                )
            return self.operations.finish(
                operation_id,
                "failed",
                "requested_state_not_observed",
                "Infrastructure action ended but requested Docker state was not observed",
                self._filtered(observed),
            )
        except ActionExecutionError as error:
            status = "indeterminate" if error.uncertain else "failed"
            message = (
                "Infrastructure action may have been dispatched; outcome is unknown"
                if error.uncertain
                else "Infrastructure action failed"
            )
            return self.operations.finish(
                operation_id,
                status,
                error.result_code,
                message,
                self._try_filtered_target(target_kind, target),
            )
        except (EngineUnavailableError, ContainerNotFoundError):
            status = "indeterminate" if dispatched else "failed"
            code = "post_dispatch_state_unknown" if dispatched else "pre_dispatch_failed"
            message = (
                "Infrastructure action was dispatched but final state is unknown"
                if dispatched
                else "Infrastructure action could not be dispatched"
            )
            return self.operations.finish(operation_id, status, code, message)
        except Exception:
            status = "indeterminate" if dispatched else "failed"
            code = "unexpected_post_dispatch_failure" if dispatched else "pre_dispatch_failed"
            message = (
                "Infrastructure action may have been dispatched; outcome is unknown"
                if dispatched
                else "Infrastructure action could not be dispatched"
            )
            return self.operations.finish(operation_id, status, code, message)
        finally:
            resource_lock.release()

    def _current_target(
        self,
        target_kind: TargetKind,
        target: str,
    ) -> ResourceResponse:
        resources, _ = self.inventory.current_resources()
        for resource in resources:
            if resource.target_kind == target_kind and resource.target == target:
                return resource
        if target_kind == "standalone_container":
            try:
                snapshot = self.gateway.inspect_container(target)
            except ContainerNotFoundError:
                raise
            if snapshot.compose_classification == "coherent":
                return self._non_operable_snapshot_resource(snapshot, "compose_member")
            if snapshot.compose_classification == "ambiguous":
                return self._non_operable_snapshot_resource(snapshot, "ambiguous")
        raise ContainerNotFoundError()

    @staticmethod
    def _non_operable_snapshot_resource(snapshot, reason: str) -> ResourceResponse:
        return ResourceResponse(
            classification="ambiguous",
            target_kind=None,
            target=snapshot.id,
            display_name=snapshot.name,
            state=snapshot.state,
            health_status=snapshot.health_status,
            management_policy=None,
            operable=False,
            diagnostic_status="compose_labels_incomplete_or_invalid",
        )

    def _preflight_rejection(self, resource: ResourceResponse):
        if resource.classification != "operational" or not resource.operable:
            return (
                "rejected",
                "resource_not_pilotable",
                "Docker resource is not a pilotable target",
            )
        if resource.protection_forced:
            return (
                "rejected",
                "nodeconductor_target_protected",
                "NodeConductor hosting resource is protected",
            )
        if resource.management_policy == "protected":
            return (
                "rejected",
                "protected_resource",
                "Protected Docker resources cannot be acted on",
            )
        if resource.management_policy != "managed":
            return (
                "rejected",
                "management_policy_not_managed",
                "Docker resource policy does not authorize actions",
            )
        return None

    def _compose_preflight(
        self,
        target: str,
    ) -> tuple[tuple[str, str, str] | None, ComposeProjectDefinition | None]:
        if not self.compose_registry.usable:
            return (
                (
                    "failed",
                    "compose_registry_unavailable",
                    "Local Compose registry is unavailable or invalid",
                ),
                None,
            )
        project = self.compose_registry.get(target)
        if project is None or project.project_name != target:
            return (
                (
                    "rejected",
                    "compose_project_not_registered",
                    "Compose project is not authorized by the local Agent registry",
                ),
                None,
            )
        return None, project

    @staticmethod
    def _desired_state_observed(
        resource: ResourceResponse,
        action: ResourceAction,
    ) -> bool:
        if resource.target_kind == "compose_project":
            states = {member.state for member in resource.members}
            if not states:
                return False
            if action == "start":
                return states == {"running"}
            return states <= {"created", "exited"}
        if action == "start":
            return resource.state == "running"
        return resource.state in {"created", "exited"}

    @staticmethod
    def _filtered(resource: ResourceResponse) -> ActionResourceState | None:
        if resource.target_kind is None or resource.management_policy is None:
            return None
        return ActionResourceState(
            target_kind=resource.target_kind,
            target=resource.target,
            state=resource.state,
            health_status=resource.health_status,
            management_policy=resource.management_policy,
            is_pilotable=resource.operable,
        )

    def _resource_lock(self, target_kind: TargetKind, target: str) -> Lock:
        identity = (target_kind, target)
        with self._resource_locks_guard:
            return self._resource_locks.setdefault(identity, Lock())

    def _try_filtered_target(
        self,
        target_kind: TargetKind,
        target: str,
    ) -> ActionResourceState | None:
        try:
            return self._filtered(self._current_target(target_kind, target))
        except Exception:
            return None

    @staticmethod
    def _validate_target(target_kind: TargetKind, target: str) -> None:
        valid = (
            bool(CONTAINER_ID_PATTERN.fullmatch(target))
            if target_kind == "standalone_container"
            else bool(PROJECT_NAME_PATTERN.fullmatch(target))
        )
        if not valid:
            raise InvalidActionTargetError()
