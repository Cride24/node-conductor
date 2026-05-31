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


class ServiceActionConflictError(ValueError):
    """Erreur metier levee quand une action contredit l'etat courant."""


class JobConflictError(ValueError):
    """Erreur metier levee quand un job ne peut pas changer d'etat."""


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
