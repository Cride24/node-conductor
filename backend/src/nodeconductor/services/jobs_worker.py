from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

from nodeconductor.repositories.jobs_repository import (
    claim_pending_job,
    fetch_job_by_id,
    fetch_next_pending_job,
    finish_running_job,
)
from nodeconductor.repositories.services_repository import update_service_status_row
from nodeconductor.schemas.jobs.common import Job
from nodeconductor.core.config import settings
from nodeconductor.services.events import record_event
from nodeconductor.services.worker_executors import (
    SimulationWorkerExecutor,
    WorkerExecutor,
    WorkerExecutionResult,
    WorkerMode,
    WorkerResult,
    build_worker_executor,
)


class WorkerJobConflictError(ValueError):
    """Erreur levee quand le worker ne peut pas executer un job."""


def run_job(
    job_id: int,
    result: WorkerResult | None = None,
    error_message: str | None = None,
    worker_mode: WorkerMode | None = None,
    executor: WorkerExecutor | None = None,
) -> Job | None:
    """Execute un job en deleguant l'action concrete a un executor."""
    job = fetch_job_by_id(job_id)
    if job is None:
        return None
    if job["status"] == "pending":
        job = claim_pending_job(job_id)
    if job["status"] != "running":
        raise WorkerJobConflictError(
            f"Job {job_id} is already {job['status']} and cannot be completed"
        )

    selected_mode = worker_mode or settings.worker_mode
    if executor is None:
        if result is not None or error_message is not None:
            executor = SimulationWorkerExecutor(result or "succeeded", error_message)
            selected_mode = "simulation"
        else:
            executor = build_worker_executor(selected_mode)

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

    executor_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="worker-job")
    execution_future = executor_pool.submit(executor.execute, job)
    try:
        execution_result = execution_future.result(
            timeout=settings.worker_execution_timeout_seconds,
        )
    except FutureTimeoutError:
        execution_future.cancel()
        execution_result = WorkerExecutionResult(
            "failed",
            (
                "worker execution timed out after "
                f"{settings.worker_execution_timeout_seconds} seconds"
            ),
        )
    except Exception as exc:
        execution_result = WorkerExecutionResult(
            "failed",
            str(exc)[:2_000],
        )
    finally:
        executor_pool.shutdown(wait=False, cancel_futures=True)

    finished_job = finish_running_job(
        job_id,
        execution_result.status,
        execution_result.error_message,
    )
    if execution_result.status == "succeeded":
        final_status = "on" if finished_job["action"] == "start" else "off"
    else:
        final_status = "error"
    update_service_status_row(finished_job["service_id"], final_status)
    event_type = (
        "job.succeeded" if execution_result.status == "succeeded" else "job.failed"
    )
    severity = "info" if execution_result.status == "succeeded" else "error"
    details = {
        "action": finished_job["action"],
        "error_message": execution_result.error_message,
    }
    if settings.event_level == "debug":
        details["worker_mode"] = selected_mode
        if finished_job["started_at"] and finished_job["finished_at"]:
            duration = finished_job["finished_at"] - finished_job["started_at"]
            details["duration_seconds"] = duration.total_seconds()
    record_event(
        event_type=event_type,
        severity=severity,
        message=f"Job {job_id} {execution_result.status}",
        service_id=finished_job["service_id"],
        job_id=job_id,
        actor_type="system",
        details=details,
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
    result: WorkerResult,
    error_message: str | None = None,
) -> Job | None:
    """Facade de dev utilisee par l'endpoint simulate-complete."""
    executor = SimulationWorkerExecutor(result, error_message)
    return run_job(job_id, worker_mode="simulation", executor=executor)


def run_next_pending_job() -> Job | None:
    """Execute au plus un job pending, puis rend la main."""
    job = fetch_next_pending_job()
    if job is None:
        return None
    return run_job(job["id"])
