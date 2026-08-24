from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from nodeconductor.core.config import settings
from nodeconductor.main import app
from nodeconductor.repositories.jobs_repository import (
    claim_pending_job,
    create_job_for_service,
    ensure_running_job_operation_id,
    fetch_job_by_id,
    finish_running_job,
)
from nodeconductor.repositories.services_repository import _connect, reset_rows
from nodeconductor.services.jobs_worker import run_job
from nodeconductor.services.worker_executors import (
    WorkerExecutionContext,
    WorkerExecutionFailedError,
    WorkerExecutionIndeterminateError,
    WorkerExecutionResult,
)


client = TestClient(app)


def setup_function() -> None:
    reset_rows()


class FakeMonotonicClock:
    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _request_start(service_id: int = 1) -> None:
    response = client.post(f"/api/v1/services/{service_id}/start", json={})
    assert response.status_code == 202


def test_execution_context_uses_injectable_monotonic_clock() -> None:
    clock = FakeMonotonicClock()
    operation_id = uuid4()
    context = WorkerExecutionContext.for_timeout(operation_id, 5, clock)

    assert context.operation_id == operation_id
    assert context.deadline == 105.0
    assert context.remaining_seconds() == 5.0
    assert context.is_expired() is False

    clock.advance(5)

    assert context.remaining_seconds() == 0.0
    assert context.is_expired() is True
    with pytest.raises(TimeoutError, match="deadline expired"):
        context.raise_if_expired()


class MustNotDispatchExecutor:
    def __init__(self) -> None:
        self.called = False

    def execute(
        self,
        job: dict,
        context: WorkerExecutionContext,
    ) -> WorkerExecutionResult:
        self.called = True
        return WorkerExecutionResult("succeeded")


def test_deadline_expired_before_dispatch_is_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _request_start()
    monkeypatch.setattr(settings, "worker_execution_timeout_seconds", 1)
    executor = MustNotDispatchExecutor()
    clock_values = iter([10.0, 11.0])

    job = run_job(1, executor=executor, clock=lambda: next(clock_values))

    assert job is not None
    assert job.status == "failed"
    assert executor.called is False
    assert "deadline expired" in (job.error_message or "")


class UnknownAfterDispatchExecutor:
    def execute(
        self,
        job: dict,
        context: WorkerExecutionContext,
    ) -> WorkerExecutionResult:
        context.raise_if_expired()
        assert context.operation_id == job["operation_id"]
        raise WorkerExecutionIndeterminateError(
            "agent request may have been dispatched"
        )


class ConfirmedFailureExecutor:
    def execute(
        self,
        job: dict,
        context: WorkerExecutionContext,
    ) -> WorkerExecutionResult:
        context.raise_if_expired()
        raise WorkerExecutionFailedError("agent rejected the operation")


def test_unknown_outcome_after_dispatch_is_indeterminate_and_unknown() -> None:
    _request_start()

    job = run_job(1, executor=UnknownAfterDispatchExecutor())

    assert job is not None
    assert job.status == "indeterminate"
    assert client.get("/api/v1/services/1").json()["status"] == "unknown"


def test_confirmed_executor_failure_is_failed() -> None:
    _request_start()

    job = run_job(1, executor=ConfirmedFailureExecutor())

    assert job is not None
    assert job.status == "failed"
    assert client.get("/api/v1/services/1").json()["status"] == "error"


def test_operation_id_is_stable_for_same_job_and_unique_between_jobs() -> None:
    _request_start()
    first_claim = claim_pending_job(1)
    assert first_claim is not None
    assert isinstance(first_claim["operation_id"], UUID)

    same_job = ensure_running_job_operation_id(1, candidate=uuid4())

    assert same_job is not None
    assert same_job["operation_id"] == first_claim["operation_id"]
    finish_running_job(1, "succeeded")

    second_job = create_job_for_service(2, "stop")
    second_claim = claim_pending_job(second_job["id"])
    assert second_claim is not None
    assert second_claim["operation_id"] != first_claim["operation_id"]

    with pytest.raises(psycopg.errors.UniqueViolation):
        with _connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE jobs SET operation_id = %s WHERE id = %s",
                    (first_claim["operation_id"], second_claim["id"]),
                )

    assert fetch_job_by_id(1)["operation_id"] == first_claim["operation_id"]
