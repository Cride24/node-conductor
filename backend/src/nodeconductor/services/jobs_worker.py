from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

from nodeconductor.core.config import settings
from nodeconductor.repositories.jobs_repository import (
    claim_next_pending_job,
    claim_pending_job,
    fetch_job_by_id,
    finish_running_job,
)
from nodeconductor.repositories.services_repository import update_service_status_row
from nodeconductor.schemas.jobs.common import Job
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


def _select_executor(
    result: WorkerResult | None,
    error_message: str | None,
    worker_mode: WorkerMode | None,
    executor: WorkerExecutor | None,
) -> tuple[WorkerMode, WorkerExecutor]:
    selected_mode = worker_mode or settings.worker_mode
    if executor is not None:
        return selected_mode, executor
    if result is not None or error_message is not None:
        return "simulation", SimulationWorkerExecutor(
            result or "succeeded",
            error_message,
        )
    return selected_mode, build_worker_executor(selected_mode)


def _execute_with_timeout(
    executor: WorkerExecutor,
    job: dict,
) -> WorkerExecutionResult:
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="worker-job")
    future = pool.submit(executor.execute, job)
    try:
        return future.result(timeout=settings.worker_execution_timeout_seconds)
    except FutureTimeoutError:
        future.cancel()
        return WorkerExecutionResult(
            "failed",
            (
                "worker execution timed out after "
                f"{settings.worker_execution_timeout_seconds} seconds"
            ),
        )
    except Exception as exc:
        return WorkerExecutionResult("failed", str(exc)[:2_000])
    finally:
        # Un thread Python deja lance ne peut pas etre tue proprement.
        pool.shutdown(wait=True, cancel_futures=True)


def _record_job_started(job: dict) -> None:
    record_event(
        event_type="job.started",
        severity="info",
        message=f"Job {job['id']} started",
        service_id=job["service_id"],
        job_id=job["id"],
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
        job_id=job["id"],
        actor_type="system",
        details={"new_status": running_status},
    )


def _final_service_status(job: dict, result: WorkerExecutionResult) -> str:
    if result.status == "succeeded":
        return "on" if job["action"] == "start" else "off"
    if result.status == "indeterminate":
        return "unknown"
    return "error"


def _record_job_finished(
    job: dict,
    result: WorkerExecutionResult,
    final_status: str,
    worker_mode: WorkerMode,
) -> None:
    event_type = {
        "succeeded": "job.succeeded",
        "failed": "job.failed",
        "indeterminate": "job.indeterminate",
    }[result.status]
    severity = {
        "succeeded": "info",
        "failed": "error",
        "indeterminate": "warning",
    }[result.status]
    details = {"action": job["action"], "error_message": result.error_message}
    if settings.event_level == "debug":
        details["worker_mode"] = worker_mode
        if job["started_at"] and job["finished_at"]:
            duration = job["finished_at"] - job["started_at"]
            details["duration_seconds"] = duration.total_seconds()
    record_event(
        event_type=event_type,
        severity=severity,
        message=f"Job {job['id']} {result.status}",
        service_id=job["service_id"],
        job_id=job["id"],
        actor_type="system",
        details=details,
    )
    record_event(
        event_type="service.status_changed",
        severity=severity,
        message=f"Service {job['service_id']} status changed to {final_status}",
        service_id=job["service_id"],
        job_id=job["id"],
        actor_type="system",
        details={"new_status": final_status},
    )


def run_claimed_job(
    job: dict,
    worker_mode: WorkerMode | None = None,
    executor: WorkerExecutor | None = None,
) -> Job:
    """Execute uniquement une ligne deja claim en running."""
    if job["status"] != "running":
        raise WorkerJobConflictError(
            f"Job {job['id']} is {job['status']} and was not claimed"
        )
    selected_mode, selected_executor = _select_executor(
        None,
        None,
        worker_mode,
        executor,
    )
    _record_job_started(job)
    execution_result = _execute_with_timeout(selected_executor, job)
    finished_job = finish_running_job(
        job["id"],
        execution_result.status,
        execution_result.error_message,
    )
    if finished_job is None:
        raise WorkerJobConflictError(f"Job {job['id']} is no longer running")
    final_status = _final_service_status(finished_job, execution_result)
    update_service_status_row(finished_job["service_id"], final_status)
    _record_job_finished(
        finished_job,
        execution_result,
        final_status,
        selected_mode,
    )
    return Job(**finished_job)


def run_job(
    job_id: int,
    result: WorkerResult | None = None,
    error_message: str | None = None,
    worker_mode: WorkerMode | None = None,
    executor: WorkerExecutor | None = None,
) -> Job | None:
    """Facade manuelle: claim atomique d'un id, puis execution synchrone."""
    claimed_job = claim_pending_job(job_id)
    if claimed_job is None:
        current_job = fetch_job_by_id(job_id)
        if current_job is None:
            return None
        raise WorkerJobConflictError(
            f"Job {job_id} is already {current_job['status']} "
            "and cannot be completed"
        )
    selected_mode, selected_executor = _select_executor(
        result,
        error_message,
        worker_mode,
        executor,
    )
    return run_claimed_job(claimed_job, selected_mode, selected_executor)


def run_simulated_job(
    job_id: int,
    result: WorkerResult,
    error_message: str | None = None,
) -> Job | None:
    executor = SimulationWorkerExecutor(result, error_message)
    return run_job(job_id, worker_mode="simulation", executor=executor)


def claim_next_job(
    max_concurrency: int | None = None,
    max_concurrency_per_connection: int | None = None,
) -> dict | None:
    return claim_next_pending_job(
        settings.worker_max_concurrency
        if max_concurrency is None
        else max_concurrency,
        settings.worker_max_concurrency_per_connection
        if max_concurrency_per_connection is None
        else max_concurrency_per_connection,
    )


def run_next_pending_job() -> Job | None:
    """Claim atomiquement puis execute au plus un job admissible."""
    job = claim_next_job()
    if job is None:
        return None
    return run_claimed_job(job)
