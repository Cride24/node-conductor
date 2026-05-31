from nodeconductor.repositories.jobs_repository import (
    fetch_job_by_id,
    finish_running_job,
    mark_job_running,
)
from nodeconductor.repositories.services_repository import update_service_status_row
from nodeconductor.schemas.jobs.common import Job


class WorkerJobConflictError(ValueError):
    """Erreur levee quand le worker ne peut pas executer un job."""


def run_simulated_job(
    job_id: int,
    result: str,
    error_message: str | None = None,
) -> Job | None:
    """Execute un job avec le worker MVP simule."""
    job = fetch_job_by_id(job_id)
    if job is None:
        return None
    if job["status"] == "pending":
        job = mark_job_running(job_id)
    if job["status"] != "running":
        raise WorkerJobConflictError(
            f"Job {job_id} is already {job['status']} and cannot be completed"
        )

    running_status = "starting" if job["action"] == "start" else "stopping"
    update_service_status_row(job["service_id"], running_status)

    finished_job = finish_running_job(job_id, result, error_message)
    if result == "succeeded":
        final_status = "on" if finished_job["action"] == "start" else "off"
    else:
        final_status = "error"
    update_service_status_row(finished_job["service_id"], final_status)
    return Job(**finished_job)
