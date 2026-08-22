from fastapi import APIRouter, HTTPException, Path

from nodeconductor.schemas.jobs.common import Job
from nodeconductor.schemas.jobs.simulate import SimulateJobCompletionRequest
from nodeconductor.services.jobs import (
    JobConflictError,
    cancel_job,
    get_job,
    simulate_job_completion,
)


router = APIRouter()


@router.get("/api/v1/jobs/{job_id}", response_model=Job)
def get_job_endpoint(job_id: int = Path(ge=1)) -> Job:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/api/v1/jobs/{job_id}/cancel", response_model=Job)
def cancel_job_endpoint(job_id: int = Path(ge=1)) -> Job:
    # Le MVP n'annule que les jobs pending: details dans Docs/Jobs-et-actions.md.
    try:
        job = cancel_job(job_id)
    except JobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/api/v1/jobs/{job_id}/simulate-complete", response_model=Job)
def simulate_job_completion_endpoint(
    completion: SimulateJobCompletionRequest,
    job_id: int = Path(ge=1),
) -> Job:
    # Endpoint de demonstration: il remplace temporairement le futur worker.
    try:
        job = simulate_job_completion(
            job_id,
            completion.result,
            completion.error_message,
        )
    except JobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
