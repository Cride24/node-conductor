from nodeconductor.repositories.jobs_repository import (
    cancel_pending_job,
    create_job_for_service,
    fetch_active_job_for_service,
    fetch_job_by_id,
)
from nodeconductor.repositories.services_repository import fetch_row_by_id
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


def request_service_start(
    service_id: int,
    context: JobRequestContext,
) -> ServiceActionResponse | None:
    """Cree une demande start sans piloter directement l'infra."""
    service = fetch_row_by_id(service_id)
    if service is None:
        return None

    # Les jobs actifs portent l'idempotence et les conflits: Docs/Jobs-et-actions.md.
    active_job = fetch_active_job_for_service(service_id)
    if active_job is not None:
        if active_job["action"] == "start":
            return ServiceActionResponse(
                job_id=active_job["id"],
                service_id=service_id,
                action="start",
                job_status=active_job["status"],
                service_status=service["status"],
                message="Service start is already requested",
            )
        _record_action_rejected(
            service_id,
            "start",
            context,
            f"active_{active_job['action']}_job",
        )
        raise ServiceActionConflictError(
            f"Service {service_id} already has an active {active_job['action']} job"
        )

    current_status = service["status"]
    if current_status == "off":
        # L'API cree seulement le job; le worker changera services.status.
        job = create_job_for_service(
            service_id,
            "start",
            context.requested_by_type,
            context.requested_by_id,
        )
        record_event(
            event_type="job.requested",
            severity="info",
            message=f"Start requested for service {service_id}",
            service_id=service_id,
            job_id=job["id"],
            actor_type=context.requested_by_type,
            actor_id=context.requested_by_id,
            details={"action": "start"},
        )
        return ServiceActionResponse(
            job_id=job["id"],
            service_id=service_id,
            action="start",
            job_status=job["status"],
            service_status="off",
        )
    if current_status == "on":
        return ServiceActionResponse(
            service_id=service_id,
            action="start",
            service_status="on",
            message="Service is already on",
        )
    _record_action_rejected(service_id, "start", context, f"service_{current_status}")
    raise ServiceActionConflictError(
        f"Service {service_id} is currently {current_status}"
    )


def request_service_stop(
    service_id: int,
    context: JobRequestContext,
) -> ServiceActionResponse | None:
    """Cree une demande stop sans piloter directement l'infra."""
    service = fetch_row_by_id(service_id)
    if service is None:
        return None

    # Meme verrou logique que start: une action active par service.
    active_job = fetch_active_job_for_service(service_id)
    if active_job is not None:
        if active_job["action"] == "stop":
            return ServiceActionResponse(
                job_id=active_job["id"],
                service_id=service_id,
                action="stop",
                job_status=active_job["status"],
                service_status=service["status"],
                message="Service stop is already requested",
            )
        _record_action_rejected(
            service_id,
            "stop",
            context,
            f"active_{active_job['action']}_job",
        )
        raise ServiceActionConflictError(
            f"Service {service_id} already has an active {active_job['action']} job"
        )

    current_status = service["status"]
    if current_status == "on":
        # Le service reste on tant que le worker n'a pas pris le job.
        job = create_job_for_service(
            service_id,
            "stop",
            context.requested_by_type,
            context.requested_by_id,
        )
        record_event(
            event_type="job.requested",
            severity="info",
            message=f"Stop requested for service {service_id}",
            service_id=service_id,
            job_id=job["id"],
            actor_type=context.requested_by_type,
            actor_id=context.requested_by_id,
            details={"action": "stop"},
        )
        return ServiceActionResponse(
            job_id=job["id"],
            service_id=service_id,
            action="stop",
            job_status=job["status"],
            service_status="on",
        )
    if current_status == "off":
        return ServiceActionResponse(
            service_id=service_id,
            action="stop",
            service_status="off",
            message="Service is already off",
        )
    _record_action_rejected(service_id, "stop", context, f"service_{current_status}")
    raise ServiceActionConflictError(
        f"Service {service_id} is currently {current_status}"
    )


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
