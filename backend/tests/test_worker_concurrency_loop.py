import asyncio
from threading import Event, Lock

from fastapi.testclient import TestClient

from nodeconductor.main import app
from nodeconductor.repositories.jobs_repository import fetch_job_by_id
from nodeconductor.repositories.services_repository import reset_rows
from nodeconductor.repositories.worker_contracts_repository import (
    create_agent_connection_row,
    create_service_target_binding_row,
    create_target_row,
)
from nodeconductor.services.worker_executors import WorkerExecutionResult
from nodeconductor.services.worker_loop import WorkerLoopController


client = TestClient(app)


def setup_function() -> None:
    reset_rows()


class BlockingExecutor:
    def __init__(self, expected_starts: int) -> None:
        self.expected_starts = expected_starts
        self.all_started = Event()
        self.release = Event()
        self.lock = Lock()
        self.started_job_ids: list[int] = []
        self.active_count = 0
        self.max_active_count = 0

    def execute(self, job: dict) -> WorkerExecutionResult:
        with self.lock:
            self.started_job_ids.append(job["id"])
            self.active_count += 1
            self.max_active_count = max(self.max_active_count, self.active_count)
            if len(self.started_job_ids) == self.expected_starts:
                self.all_started.set()
        try:
            if not self.release.wait(timeout=10):
                raise AssertionError("test executor was not released")
            return WorkerExecutionResult("succeeded")
        finally:
            with self.lock:
                self.active_count -= 1


class SequencedExecutor:
    def __init__(self) -> None:
        self.first_started = Event()
        self.release_first = Event()
        self.second_started = Event()
        self.release_second = Event()

    def execute(self, job: dict) -> WorkerExecutionResult:
        if job["id"] == 1:
            self.first_started.set()
            assert self.release_first.wait(timeout=10)
        else:
            self.second_started.set()
            assert self.release_second.wait(timeout=10)
        return WorkerExecutionResult("succeeded")


def _create_service(name: str) -> int:
    response = client.post(
        "/api/v1/services/",
        json={
            "name": name,
            "type": "LXC",
            "category": "test",
            "description": f"Service loop {name}",
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def _create_connection(connection_id: str) -> None:
    create_agent_connection_row(
        {
            "id": connection_id,
            "description": f"Agent {connection_id}",
            "transport": "unix_socket",
            "endpoint": f"/run/{connection_id}.sock",
        }
    )


def _prepare_jobs(connection_ids: list[str]) -> None:
    for connection_id in sorted(set(connection_ids)):
        _create_connection(connection_id)
    for index, connection_id in enumerate(connection_ids):
        service_id = _create_service(f"loop-{index}")
        target = create_target_row(
            {
                "driver": "docker",
                "connection_id": connection_id,
                "target": f"container-{index}",
            }
        )
        create_service_target_binding_row(
            {
                "service_id": service_id,
                "target_id": target["id"],
                "readiness_check": "docker_state",
            }
        )
        response = client.post(f"/api/v1/services/{service_id}/start", json={})
        assert response.status_code == 202


async def _wait_for_started(executor: BlockingExecutor) -> None:
    started = await asyncio.to_thread(executor.all_started.wait, 10)
    assert started, "worker did not fill the expected execution slots"


async def _stop_while_blocked(
    controller: WorkerLoopController,
    executor: BlockingExecutor,
) -> None:
    stop_task = asyncio.create_task(controller.stop())
    await asyncio.sleep(0)
    assert not stop_task.done()
    executor.release.set()
    await stop_task


def test_different_targets_execute_in_parallel() -> None:
    _prepare_jobs(["connection-a", "connection-a"])
    executor = BlockingExecutor(expected_starts=2)

    async def scenario() -> None:
        controller = WorkerLoopController(10, 2, 2, executor)
        controller.start()
        await _wait_for_started(executor)
        assert executor.max_active_count == 2
        await _stop_while_blocked(controller, executor)

    asyncio.run(scenario())


def test_global_limit_and_graceful_stop_leave_unclaimed_job_pending() -> None:
    _prepare_jobs(["connection-a", "connection-b", "connection-c"])
    executor = BlockingExecutor(expected_starts=2)

    async def scenario() -> None:
        controller = WorkerLoopController(10, 2, 2, executor)
        controller.start()
        await _wait_for_started(executor)
        assert len(executor.started_job_ids) == 2
        await _stop_while_blocked(controller, executor)

    asyncio.run(scenario())

    assert len(executor.started_job_ids) == 2
    assert fetch_job_by_id(3)["status"] == "pending"


def test_connection_limit_skips_to_another_connection() -> None:
    _prepare_jobs(
        ["connection-a", "connection-a", "connection-a", "connection-b"]
    )
    executor = BlockingExecutor(expected_starts=3)

    async def scenario() -> None:
        controller = WorkerLoopController(10, 4, 2, executor)
        controller.start()
        await _wait_for_started(executor)
        assert set(executor.started_job_ids) == {1, 2, 4}
        await _stop_while_blocked(controller, executor)

    asyncio.run(scenario())

    assert fetch_job_by_id(3)["status"] == "pending"


def test_finished_slot_is_refilled_without_waiting_for_poll_interval() -> None:
    _prepare_jobs(["connection-a", "connection-b"])
    executor = SequencedExecutor()

    async def scenario() -> None:
        controller = WorkerLoopController(10, 1, 1, executor)
        controller.start()
        assert await asyncio.to_thread(executor.first_started.wait, 10)
        executor.release_first.set()
        assert await asyncio.to_thread(executor.second_started.wait, 2)
        stop_task = asyncio.create_task(controller.stop())
        await asyncio.sleep(0)
        assert not stop_task.done()
        executor.release_second.set()
        await stop_task

    asyncio.run(scenario())
