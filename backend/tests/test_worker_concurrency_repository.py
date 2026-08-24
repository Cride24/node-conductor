from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock

import psycopg
import pytest
from fastapi.testclient import TestClient

from nodeconductor.main import app
from nodeconductor.repositories.jobs_repository import (
    claim_next_pending_job,
    fetch_job_by_id,
)
from nodeconductor.repositories.services_repository import _connect, reset_rows
from nodeconductor.repositories.worker_contracts_repository import (
    create_agent_connection_row,
    create_service_target_binding_row,
    create_target_row,
)
from nodeconductor.schemas.jobs.create import JobRequestContext
from nodeconductor.services.jobs import (
    ServiceActionConflictError,
    request_service_start,
    request_service_stop,
)
from nodeconductor.services.jobs_worker import WorkerJobConflictError, run_job
from nodeconductor.services.worker_executors import (
    WorkerExecutionContext,
    WorkerExecutionResult,
)


client = TestClient(app)


def setup_function() -> None:
    reset_rows()


def _create_connection(connection_id: str = "docker-main") -> None:
    create_agent_connection_row(
        {
            "id": connection_id,
            "description": f"Agent {connection_id}",
            "transport": "unix_socket",
            "endpoint": f"/run/{connection_id}.sock",
        }
    )


def _create_service(name: str) -> int:
    response = client.post(
        "/api/v1/services/",
        json={
            "name": name,
            "type": "LXC",
            "category": "test",
            "description": f"Service concurrent {name}",
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def _bind_target(service_id: int, connection_id: str, target_name: str) -> int:
    target = create_target_row(
        {
            "driver": "docker",
            "connection_id": connection_id,
            "target": target_name,
        }
    )
    create_service_target_binding_row(
        {
            "service_id": service_id,
            "target_id": target["id"],
            "readiness_check": "docker_state",
        }
    )
    return target["id"]


class CountingBlockingExecutor:
    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()
        self.lock = Lock()
        self.call_count = 0

    def execute(
        self,
        job: dict,
        context: WorkerExecutionContext,
    ) -> WorkerExecutionResult:
        with self.lock:
            self.call_count += 1
        self.started.set()
        assert self.release.wait(timeout=10)
        return WorkerExecutionResult("succeeded")


def test_simultaneous_identical_requests_create_one_active_job() -> None:
    barrier = Barrier(2)
    context = JobRequestContext()

    def request_start():
        barrier.wait()
        return request_service_start(1, context)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: request_start(), range(2)))

    assert {response.job_id for response in responses} == {1}
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) AS total
                FROM jobs
                WHERE service_id = 1 AND status IN ('pending', 'running')
                """
            )
            assert cursor.fetchone()["total"] == 1


def test_simultaneous_opposite_requests_never_create_incompatible_jobs() -> None:
    barrier = Barrier(2)
    context = JobRequestContext()

    def request(action: str):
        barrier.wait()
        try:
            if action == "start":
                return request_service_start(1, context)
            return request_service_stop(1, context)
        except ServiceActionConflictError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(request, ["start", "stop"]))

    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT action
                FROM jobs
                WHERE service_id = 1 AND status IN ('pending', 'running')
                """
            )
            active_jobs = cursor.fetchall()
    assert active_jobs == [{"action": "start"}]


def test_job_snapshots_target_and_active_indexes_reject_duplicates() -> None:
    _create_connection()
    target_id = _bind_target(1, "docker-main", "minecraft")

    response = client.post("/api/v1/services/1/start", json={})

    assert response.status_code == 202
    assert fetch_job_by_id(1)["target_id"] == target_id
    with pytest.raises(psycopg.errors.UniqueViolation):
        with _connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO jobs (service_id, target_id, action)
                    VALUES (1, %s, 'stop')
                    """,
                    (target_id,),
                )


def test_one_target_cannot_be_bound_to_two_services() -> None:
    _create_connection()
    target_id = _bind_target(1, "docker-main", "minecraft")

    with pytest.raises(psycopg.errors.UniqueViolation):
        create_service_target_binding_row(
            {
                "service_id": 2,
                "target_id": target_id,
                "readiness_check": "docker_state",
            }
        )


def test_target_operational_triplet_is_immutable() -> None:
    _create_connection()
    target_id = _bind_target(1, "docker-main", "minecraft")

    with pytest.raises(psycopg.errors.CheckViolation):
        with _connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE targets SET target = 'renamed' WHERE id = %s",
                    (target_id,),
                )


def test_two_claimers_never_claim_the_same_job() -> None:
    response = client.post("/api/v1/services/1/start", json={})
    assert response.status_code == 202
    barrier = Barrier(2)

    def claim():
        barrier.wait()
        return claim_next_pending_job(4, 2)

    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed = list(pool.map(lambda _: claim(), range(2)))

    claimed_ids = [job["id"] for job in claimed if job is not None]
    assert claimed_ids == [1]
    assert fetch_job_by_id(1)["status"] == "running"


def test_two_manual_workers_never_execute_the_same_job() -> None:
    response = client.post("/api/v1/services/1/start", json={})
    assert response.status_code == 202
    barrier = Barrier(2)
    executor = CountingBlockingExecutor()

    def execute():
        barrier.wait()
        try:
            return run_job(1, executor=executor)
        except WorkerJobConflictError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(execute) for _ in range(2)]
        assert executor.started.wait(timeout=10)
        executor.release.set()
        results = [future.result(timeout=10) for future in futures]

    assert executor.call_count == 1
    assert sum(result is not None for result in results) == 1


def test_claim_respects_global_capacity() -> None:
    service_ids = [_create_service(f"global-{index}") for index in range(3)]
    for service_id in service_ids:
        response = client.post(f"/api/v1/services/{service_id}/start", json={})
        assert response.status_code == 202

    first = claim_next_pending_job(2, 2)
    second = claim_next_pending_job(2, 2)
    blocked = claim_next_pending_job(2, 2)

    assert {first["id"], second["id"]} == {1, 2}
    assert blocked is None


def test_concurrent_claimers_share_the_global_capacity() -> None:
    service_ids = [_create_service(f"claim-{index}") for index in range(3)]
    for service_id in service_ids:
        response = client.post(f"/api/v1/services/{service_id}/start", json={})
        assert response.status_code == 202
    barrier = Barrier(3)

    def claim():
        barrier.wait()
        return claim_next_pending_job(2, 2)

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: claim(), range(3)))

    claimed_ids = {job["id"] for job in results if job is not None}
    assert len(claimed_ids) == 2


def test_claim_skips_a_saturated_connection() -> None:
    _create_connection("connection-a")
    _create_connection("connection-b")
    services = [_create_service(f"target-{index}") for index in range(4)]
    for index, service_id in enumerate(services):
        connection_id = "connection-a" if index < 3 else "connection-b"
        _bind_target(service_id, connection_id, f"container-{index}")
        response = client.post(f"/api/v1/services/{service_id}/start", json={})
        assert response.status_code == 202

    claimed = [claim_next_pending_job(4, 2) for _ in range(3)]
    blocked = claim_next_pending_job(4, 2)

    assert [job["id"] for job in claimed] == [1, 2, 4]
    assert blocked is None
    assert fetch_job_by_id(3)["status"] == "pending"
