from nodeconductor.repositories.jobs_repository import (
    cancel_pending_job,
    fetch_job_by_id,
    request_job_for_service_atomically,
)
from nodeconductor.schemas.jobs.common import Job, ServiceActionResponse
from nodeconductor.schemas.jobs.create import JobRequestContext
from nodeconductor.services.jobs_worker import (
    WorkerJobConflictError,
    run_simulated_job,
)
from nodeconductor.services.events import record_event


class ServiceActionConflictError(ValueError):
    """Erreur metier levee quand une action contredit l'etat courant."""


class JobConflictError(ValueError):
    """Erreur metier levee quand un job ne peut pas changer d'etat."""


def _record_action_rejected(
    service_id: int,
    action: str,
    context: JobRequestContext,
    reason: str,
) -> None:
    record_event(
        event_type="action.rejected",
        severity="warning",
        message=f"{action} rejected for service {service_id}: {reason}",
        service_id=service_id,
        actor_type=context.requested_by_type,
        actor_id=context.requested_by_id,
        details={"action": action, "reason": reason},
    )


def _request_service_action(
    service_id: int,
    action: str,
    required_status: str,
    satisfied_status: str,
    context: JobRequestContext,
) -> ServiceActionResponse | None:
    result = request_job_for_service_atomically(
        service_id,
        action,
        required_status,
        context.requested_by_type,
        context.requested_by_id,
    )
    if result["outcome"] == "missing":
        return None
    if result["outcome"] == "target_not_pilotable":
        reason = "target_not_pilotable"
        _record_action_rejected(service_id, action, context, reason)
        raise ServiceActionConflictError(
            f"Service {service_id} target is not pilotable"
        )

    service_status = result["service_status"]
    active_job = result["job"]
    if result["outcome"] == "active":
        if active_job["action"] == action:
            return ServiceActionResponse(
                job_id=active_job["id"],
                service_id=service_id,
                action=action,
                job_status=active_job["status"],
                service_status=service_status,
                message=f"Service {action} is already requested",
            )
        reason = f"active_{active_job['action']}_job"
        _record_action_rejected(service_id, action, context, reason)
        raise ServiceActionConflictError(
            f"Service {service_id} already has an active "
            f"{active_job['action']} job"
        )

    if result["outcome"] == "state":
        if service_status == satisfied_status:
            return ServiceActionResponse(
                service_id=service_id,
                action=action,
                service_status=service_status,
                message=f"Service is already {satisfied_status}",
            )
        _record_action_rejected(
            service_id,
            action,
            context,
            f"service_{service_status}",
        )
        raise ServiceActionConflictError(
            f"Service {service_id} is currently {service_status}"
        )

    job = result["job"]
    record_event(
        event_type="job.requested",
        severity="info",
        message=f"{action.capitalize()} requested for service {service_id}",
        service_id=service_id,
        job_id=job["id"],
        actor_type=context.requested_by_type,
        actor_id=context.requested_by_id,
        details={"action": action},
    )
    return ServiceActionResponse(
        job_id=job["id"],
        service_id=service_id,
        action=action,
        job_status=job["status"],
        service_status=service_status,
    )


def request_service_start(
    service_id: int,
    context: JobRequestContext,
) -> ServiceActionResponse | None:
    return _request_service_action(service_id, "start", "off", "on", context)


def request_service_stop(
    service_id: int,
    context: JobRequestContext,
) -> ServiceActionResponse | None:
    return _request_service_action(service_id, "stop", "on", "off", context)


def get_job(job_id: int) -> Job | None:
    row = fetch_job_by_id(job_id)
    if row is None:
        return None
    return Job(**row)


def cancel_job(job_id: int) -> Job | None:
    """Annule seulement une demande non prise par le worker."""
    job = fetch_job_by_id(job_id)
    if job is None:
        return None
    if job["status"] == "cancelled":
        return Job(**job)
    if job["status"] != "pending":
        raise JobConflictError(
            f"Job {job_id} is already {job['status']} and cannot be cancelled"
        )

    cancelled_job = cancel_pending_job(job_id)
    if cancelled_job is None:
        current_job = fetch_job_by_id(job_id)
        if current_job is None:
            return None
        raise JobConflictError(
            f"Job {job_id} is already {current_job['status']} "
            "and cannot be cancelled"
        )
    record_event(
        event_type="job.cancelled",
        severity="info",
        message=f"Job {job_id} cancelled",
        service_id=cancelled_job["service_id"],
        job_id=job_id,
        actor_type="system",
        details={"action": cancelled_job["action"]},
    )
    return Job(**cancelled_job)


def simulate_job_completion(
    job_id: int,
    result: str,
    error_message: str | None = None,
) -> Job | None:
    """Simule le worker MVP qui fait evoluer job.status et services.status."""
    try:
        return run_simulated_job(job_id, result, error_message)
    except WorkerJobConflictError as exc:
        raise JobConflictError(str(exc)) from exc
