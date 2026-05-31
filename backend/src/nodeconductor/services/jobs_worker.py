from nodeconductor.repositories.jobs_repository import (
    claim_pending_job,
    fetch_job_by_id,
    fetch_next_pending_job,
    finish_running_job,
)
from nodeconductor.repositories.services_repository import update_service_status_row
from nodeconductor.schemas.jobs.common import Job
from nodeconductor.services.events import record_event


class WorkerJobConflictError(ValueError):
    """Erreur levee quand le worker ne peut pas executer un job."""


def run_job(
    job_id: int,
    result: str = "succeeded",
    error_message: str | None = None,
) -> Job | None:
    """Execute manuellement un job avec le worker MVP."""
    job = fetch_job_by_id(job_id)
    if job is None:
        return None
    if job["status"] == "pending":
        job = claim_pending_job(job_id)
    if job["status"] != "running":
        raise WorkerJobConflictError(
            f"Job {job_id} is already {job['status']} and cannot be completed"
        )

    record_event(
        event_type="job.started",
        severity="info",
        message=f"Job {job_id} started",
        service_id=job["service_id"],
        job_id=job_id,
        actor_type="system",
        details={"action": job["action"]},
    )
    running_status = "starting" if job["action"] == "start" else "stopping"
    update_service_status_row(job["service_id"], running_status)
    record_event(
        event_type="service.status_changed",
        severity="info",
        message=f"Service {job['service_id']} status changed to {running_status}",
        service_id=job["service_id"],
        job_id=job_id,
        actor_type="system",
        details={"new_status": running_status},
    )

    finished_job = finish_running_job(job_id, result, error_message)
    if result == "succeeded":
        final_status = "on" if finished_job["action"] == "start" else "off"
    else:
        final_status = "error"
    update_service_status_row(finished_job["service_id"], final_status)
    event_type = "job.succeeded" if result == "succeeded" else "job.failed"
    severity = "info" if result == "succeeded" else "error"
    record_event(
        event_type=event_type,
        severity=severity,
        message=f"Job {job_id} {result}",
        service_id=finished_job["service_id"],
        job_id=job_id,
        actor_type="system",
        details={"action": finished_job["action"], "error_message": error_message},
    )
    record_event(
        event_type="service.status_changed",
        severity=severity,
        message=f"Service {finished_job['service_id']} status changed to {final_status}",
        service_id=finished_job["service_id"],
        job_id=job_id,
        actor_type="system",
        details={"new_status": final_status},
    )
    return Job(**finished_job)


def run_simulated_job(
    job_id: int,
    result: str,
    error_message: str | None = None,
) -> Job | None:
    """Facade de dev utilisee par l'endpoint simulate-complete."""
    return run_job(job_id, result, error_message)


def run_next_pending_job() -> Job | None:
    """Execute au plus un job pending, puis rend la main."""
    job = fetch_next_pending_job()
    if job is None:
        return None
    return run_job(job["id"])
