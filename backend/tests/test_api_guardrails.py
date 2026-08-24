import asyncio
from threading import Event
from time import monotonic
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nodeconductor.core.config import settings
from nodeconductor.core.middleware import (
    RequestBodyLimitMiddleware,
    RequestTimeoutMiddleware,
)
from nodeconductor.main import app
from nodeconductor.repositories.services_repository import reset_rows
from nodeconductor.services.jobs_worker import _execute_cooperatively
from nodeconductor.services.worker_executors import (
    WorkerExecutionContext,
    WorkerExecutionResult,
)


client = TestClient(app)


@pytest.fixture
def reset_database() -> None:
    reset_rows()


def test_oversized_request_body_returns_413() -> None:
    response = client.post(
        "/api/v1/services/",
        json={
            "name": "forge",
            "type": "LXC",
            "category": "game",
            "description": "x" * settings.api_max_request_body_bytes,
        },
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "Request body too large"


def test_streamed_request_body_is_also_limited() -> None:
    downstream_called = False
    sent_messages: list[dict] = []
    incoming_messages = [
        {"type": "http.request", "body": b"a" * 40, "more_body": True},
        {"type": "http.request", "body": b"b" * 40, "more_body": False},
    ]

    async def downstream(scope, receive, send) -> None:
        nonlocal downstream_called
        downstream_called = True

    async def receive() -> dict:
        return incoming_messages.pop(0)

    async def send(message: dict) -> None:
        sent_messages.append(message)

    middleware = RequestBodyLimitMiddleware(downstream, max_body_bytes=64)
    asyncio.run(
        middleware(
            {"type": "http", "headers": []},
            receive,
            send,
        )
    )

    assert downstream_called is False
    assert sent_messages[0]["status"] == 413


def test_service_dependencies_are_limited() -> None:
    response = client.post(
        "/api/v1/services/",
        json={
            "name": "forge",
            "type": "LXC",
            "category": "game",
            "description": "instance minecraft forge",
            "dependencies": list(range(1, 52)),
        },
    )

    assert response.status_code == 422


def test_request_actor_id_is_limited_to_database_capacity() -> None:
    response = client.post(
        "/api/v1/services/1/start",
        json={"requested_by_type": "llm", "requested_by_id": "a" * 101},
    )

    assert response.status_code == 422


def test_services_listing_is_paginated(reset_database: None) -> None:
    response = client.get("/api/v1/services", params={"limit": 1, "offset": 1})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["limit"] == 1
    assert body["offset"] == 1
    assert len(body["services"]) == 1
    assert body["services"][0]["id"] == 2


def test_services_listing_rejects_excessive_limit() -> None:
    response = client.get("/api/v1/services", params={"limit": 201})

    assert response.status_code == 422


def test_request_timeout_returns_504() -> None:
    timeout_app = FastAPI()
    timeout_app.add_middleware(RequestTimeoutMiddleware, timeout_seconds=0.01)

    @timeout_app.get("/slow")
    async def slow_endpoint() -> dict[str, bool]:
        await asyncio.sleep(0.1)
        return {"ok": True}

    response = TestClient(timeout_app).get("/slow")

    assert response.status_code == 504
    assert response.json()["detail"] == "Request processing timed out"


class SlowWorkerExecutor:
    def execute(
        self,
        job: dict,
        context: WorkerExecutionContext,
    ) -> WorkerExecutionResult:
        Event().wait(timeout=context.remaining_seconds())
        context.raise_if_expired()
        raise AssertionError("deadline wait returned before expiration")


def test_cooperative_worker_deadline_returns_quickly() -> None:
    context = WorkerExecutionContext.for_timeout(uuid4(), 0.01)
    started_at = monotonic()
    result = _execute_cooperatively(SlowWorkerExecutor(), {}, context)
    elapsed = monotonic() - started_at

    assert result.status == "failed"
    assert "deadline expired" in (result.error_message or "")
    assert elapsed < 0.25


def test_non_positive_path_identifier_is_rejected() -> None:
    response = client.get("/api/v1/services/0")

    assert response.status_code == 422
