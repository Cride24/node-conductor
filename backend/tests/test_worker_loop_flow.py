import asyncio

from fastapi.testclient import TestClient

from nodeconductor.main import app
from nodeconductor.repositories.services_repository import reset_rows
from nodeconductor.services.jobs_worker import run_next_pending_job
from nodeconductor.services.worker_loop import WorkerLoopController


client = TestClient(app)


def setup_function() -> None:
    reset_rows()


def test_run_next_pending_job_processes_one_job() -> None:
    start_response = client.post("/api/v1/services/1/start", json={})
    assert start_response.status_code == 202

    job = run_next_pending_job()

    assert job is not None
    assert job.status == "succeeded"
    service_response = client.get("/api/v1/services/1")
    assert service_response.status_code == 200
    assert service_response.json()["status"] == "on"


def test_run_next_pending_job_returns_none_when_queue_is_empty() -> None:
    job = run_next_pending_job()

    assert job is None


def test_worker_loop_processes_pending_job_without_tight_loop() -> None:
    start_response = client.post("/api/v1/services/1/start", json={})
    assert start_response.status_code == 202

    async def run_loop_once() -> None:
        controller = WorkerLoopController(interval_seconds=0.05)
        controller.start()
        await asyncio.sleep(0.1)
        await controller.stop()

    asyncio.run(run_loop_once())

    service_response = client.get("/api/v1/services/1")
    assert service_response.status_code == 200
    assert service_response.json()["status"] == "on"
